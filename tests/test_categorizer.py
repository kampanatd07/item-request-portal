"""Category suggestion: learn from the classified master, and from corrections."""

import io

import pytest
from openpyxl import Workbook
from sqlalchemy import select

from app.models import ItemSnapshot
from app.services.categorizer import (
    AUTO_SELECT_CONFIDENCE,
    learn_from_correction,
    suggest_category,
)
from app.services.requests import (
    RequestForbidden,
    change_category,
    change_status,
    submit_request,
)
from app.services.snapshots import SnapshotError, import_labeled_master
from tests.conftest import account_for, central_ids


def _labeled_xlsx(rows: list[tuple[str, str, str, str]]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(["Item Number", "Product Name", "Category Code", "Sub-Category Code"])
    for r in rows:
        ws.append(list(r))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


BEARINGS = [
    ("90001000001", "BEARING - Ball Bearing SKF 6205", "900", "01"),
    ("90001000002", "BEARING - Ball Bearing SKF 6206", "900", "01"),
    ("90001000003", "BEARING - Roller Bearing NSK 22213", "900", "01"),
]
CALIB = [
    ("70201000001", "CALIBRATION - งานสอบเทียบเครื่องชั่ง", "702", "01"),
    ("70201000002", "CALIBRATION - งานสอบเทียบ pH meter", "702", "01"),
]


def _load(db, rows=None):
    return import_labeled_master(
        db, filename="master.xlsx", data=_labeled_xlsx(rows or BEARINGS + CALIB), uploaded_by="test@test.local")


def test_import_labeled_master_strips_category_prefix(db_session):
    imp = _load(db_session)
    assert imp.row_count == 5
    row = db_session.scalar(
        select(ItemSnapshot).where(ItemSnapshot.item_number == "90001000001")
    )
    assert row.group_code == "900" and row.sub_code == "01"
    # the searchable text is what a user types, not the CATEGORY prefix
    assert "bearing" in row.normalized_name and not row.normalized_name.startswith("bearing -")


def test_import_rejects_file_without_label_columns(db_session):
    wb = Workbook()
    wb.active.append(["Item number", "Product name"])
    wb.active.append(["1", "x"])
    buf = io.BytesIO()
    wb.save(buf)
    with pytest.raises(SnapshotError, match="Category Code"):
        import_labeled_master(db_session, filename="bad.xlsx", data=buf.getvalue(), uploaded_by="test@test.local")


def test_suggests_from_neighbours_with_evidence(db_session):
    _load(db_session)
    out = suggest_category(db_session, "Ball Bearing SKF 6205 2RS")
    assert out, "expected a suggestion"
    top = out[0]
    assert (top.group.code, top.sub.code) == ("900", "01")
    assert top.source == "neighbours"
    assert top.examples, "the user must be able to see why"


def test_thai_service_name_finds_its_category(db_session):
    _load(db_session)
    out = suggest_category(db_session, "งานสอบเทียบเครื่องวัดอุณหภูมิ")
    assert (out[0].group.code, out[0].sub.code) == ("702", "01")


def test_exact_match_is_confident_enough_to_auto_select(db_session):
    _load(db_session)
    out = suggest_category(db_session, "Ball Bearing SKF 6205")
    assert out[0].confidence >= AUTO_SELECT_CONFIDENCE


def test_ambiguous_name_is_not_auto_selected(db_session):
    _load(db_session, BEARINGS + CALIB + [
        ("90004000001", "PIPE FITTING - Ball Valve 1 inch", "900", "04"),
    ])
    out = suggest_category(db_session, "Ball")
    if out:  # a vague term must not be presented as near-certain
        assert out[0].confidence < AUTO_SELECT_CONFIDENCE


def test_service_request_never_lands_in_a_parts_category(db_session):
    """Regression: 'งานซ่อมปั๊มน้ำ' matched the many pump PARTS in the master and
    was auto-selected into 900-06 at full confidence — a confident wrong answer."""
    _load(db_session, [
        ("90006000001", "PUMP MOTOR - Pump ปั๊มน้ำ Ebara 50Hz", "900", "06"),
        ("90006000002", "PUMP MOTOR - Pump ปั๊มน้ำ Grundfos", "900", "06"),
        ("70002000001", "MACHINE REPAIR - งานซ่อมเครื่องจักร", "700", "02"),
    ])
    out = suggest_category(db_session, "งานซ่อมปั๊มน้ำ")
    assert out, "a service request should still get a suggestion"
    assert all(s.sub.product_type == "Service" for s in out)
    assert (out[0].group.code, out[0].sub.code) == ("700", "02")


def test_distant_neighbours_do_not_produce_high_confidence(db_session):
    """Unanimity among loose matches is not certainty — only close matches
    may reach the auto-select threshold."""
    _load(db_session, [
        ("90099000001", "OTHER MECH PART - ชิ้นส่วนเครื่องจักรทั่วไป A", "900", "99"),
        ("90099000002", "OTHER MECH PART - ชิ้นส่วนเครื่องจักรทั่วไป B", "900", "99"),
    ])
    out = suggest_category(db_session, "ชิ้นส่วน XYZ ที่ไม่เคยมี")
    if out:
        assert out[0].confidence < AUTO_SELECT_CONFIDENCE


def test_keyword_rule_covers_items_with_no_neighbours(db_session):
    out = suggest_category(db_session, "งานสอบเทียบ Torque Wrench")
    assert out and (out[0].group.code, out[0].sub.code) == ("702", "01")
    assert out[0].source == "keyword"


def test_llm_only_consulted_when_the_first_two_are_silent(db_session):
    calls = []

    def fake_llm(name, options):
        calls.append(name)
        return "907-01"

    assert suggest_category(db_session, "Ball Bearing SKF", llm=fake_llm)
    assert calls == []  # keyword rule answered

    out = suggest_category(db_session, "Zorptronic flux widget", llm=fake_llm)
    assert out and out[0].source == "llm"
    assert calls == ["Zorptronic flux widget"]


def test_unknown_name_returns_nothing_rather_than_guessing(db_session):
    assert suggest_category(db_session, "Zorptronic flux widget") == []


# --- learning loop ----------------------------------------------------------

def test_correction_is_remembered_for_next_time(db_session):
    name = "อะไหล่พิเศษ ZX-9000"
    assert suggest_category(db_session, name) == []

    learn_from_correction(db_session, name=name, group_code="900", sub_code="99",
                          actor="t@test.local")
    out = suggest_category(db_session, "อะไหล่พิเศษ ZX-9000")
    assert (out[0].group.code, out[0].sub.code) == ("900", "99")


def test_procurement_recategorise_feeds_the_learner(db_session):
    factory, system, group, sub = central_ids(db_session, "APM", "900", "99")
    req = submit_request(
        db_session, account=account_for(db_session),
        factory_id=factory.id, code_system_id=system.id, group_id=group.id,
        subgroup_id=sub.id, item_name="ชิ้นส่วนพิเศษ QX-1",
    )
    _f, _s, right_group, right_sub = central_ids(db_session, "APM", "900", "01")
    change_category(db_session, req.id, subgroup_id=right_sub.id, account=account_for(db_session))

    assert req.group_id == right_group.id and req.subgroup_id == right_sub.id
    assert [e.action for e in req.events][-1] == "category_changed"

    out = suggest_category(db_session, "ชิ้นส่วนพิเศษ QX-1")
    assert (out[0].group.code, out[0].sub.code) == ("900", "01")


def test_procurement_cannot_recategorise_once_a_code_is_issued(db_session):
    factory, system, group, sub = central_ids(db_session, "APM", "900", "01")
    req = submit_request(
        db_session, account=account_for(db_session),
        factory_id=factory.id, code_system_id=system.id, group_id=group.id,
        subgroup_id=sub.id, item_name="Ball Bearing",
    )
    change_status(db_session, req.id, new_status="approved", account=account_for(db_session, "administrator"))
    _f, _s, _g, other_sub = central_ids(db_session, "APM", "900", "02")
    with pytest.raises(RequestForbidden):
        change_category(db_session, req.id, subgroup_id=other_sub.id, account=account_for(db_session))
