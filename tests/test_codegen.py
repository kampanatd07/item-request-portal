import io

import pytest
from openpyxl import Workbook
from sqlalchemy import select

from app.models import CodeGroup, CodeSystem, Factory
from app.services.requests import RequestError, change_status, override_code, submit_request
from app.services.snapshots import import_snapshot


def _xlsx(rows: list[tuple[str, str]]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(["Item number", "Product name"])
    for r in rows:
        ws.append(list(r))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _submit(db, factory_code, system_code, group_code, sub_code=None, name="Test item"):
    factory = db.scalar(select(Factory).where(Factory.code == factory_code))
    system = db.scalar(select(CodeSystem).where(CodeSystem.code == system_code))
    group = db.scalar(
        select(CodeGroup).where(
            CodeGroup.code_system_id == system.id,
            CodeGroup.code == group_code,
            CodeGroup.parent_id.is_(None),
        )
    )
    sub = None
    if sub_code:
        sub = db.scalar(
            select(CodeGroup).where(
                CodeGroup.parent_id == group.id, CodeGroup.code == sub_code
            )
        )
    return submit_request(
        db,
        requester_name="ทดสอบ",
        requester_email="t@example.com",
        factory_id=factory.id,
        code_system_id=system.id,
        group_id=group.id,
        subgroup_id=sub.id if sub else None,
        item_name=name,
    )


def _approve(db, req):
    return change_status(db, req.id, new_status="approved", actor="test")


def test_d365_stock_continues_from_snapshot_max(db_session):
    import_snapshot(
        db_session, source="D365", filename="m.xlsx",
        data=_xlsx([("80000000203", "a"), ("80000000100", "b")]),
    )
    req = _approve(db_session, _submit(db_session, "APM", "D365_STOCK", "800"))
    assert req.generated_code == "80000000204"


def test_d365_service_starts_at_one_when_group_empty(db_session):
    req = _approve(db_session, _submit(db_session, "ACM", "D365_SERVICE", "710"))
    assert req.generated_code == "71000000001"


def test_d365_mould_uses_type_and_five_digit_running(db_session):
    import_snapshot(
        db_session, source="D365", filename="m.xlsx",
        data=_xlsx([("80600100015", "mould")]),
    )
    req = _approve(
        db_session, _submit(db_session, "APG", "D365_STOCK", "806", sub_code="001")
    )
    assert req.generated_code == "80600100016"


def test_cbd_stock_cat_sub_running(db_session):
    import_snapshot(
        db_session, source="CBD", filename="m.xlsx",
        data=_xlsx([("990501012260", "Bearing SKF 6205"), ("990501010295", "x")]),
    )
    req = _approve(
        db_session, _submit(db_session, "CBD", "CBD_STOCK", "01", sub_code="01")
    )
    assert req.generated_code == "990501012261"


def test_cbd_nonstock_six_digit_running(db_session):
    import_snapshot(
        db_session, source="CBD", filename="m.xlsx",
        data=_xlsx([("64BD000950", "ยางมะตอย")]),
    )
    req = _approve(db_session, _submit(db_session, "CBD", "CBD_NONSTOCK", "BD"))
    assert req.generated_code == "64BD000951"


def test_cbd_svsp_override_four_digit_running(db_session):
    import_snapshot(
        db_session, source="CBD", filename="m.xlsx",
        data=_xlsx([("64SVSP0313", "อะไหล่ซ่อม")]),
    )
    req = _approve(db_session, _submit(db_session, "CBD", "CBD_NONSTOCK", "SVSP"))
    assert req.generated_code == "64SVSP0314"


def test_svsp_snapshot_rows_do_not_pollute_sv_running(db_session):
    # 64SVSP0313 shares the '64SV' prefix but must not count as an SV item.
    import_snapshot(
        db_session, source="CBD", filename="m.xlsx",
        data=_xlsx([("64SVSP0313", "อะไหล่"), ("64SV000795", "งานซ่อม")]),
    )
    req = _approve(db_session, _submit(db_session, "CBD", "CBD_NONSTOCK", "SV"))
    assert req.generated_code == "64SV000796"


def test_two_approvals_same_group_get_distinct_codes(db_session):
    r1 = _approve(db_session, _submit(db_session, "APM", "D365_NONSTOCK", "907"))
    r2 = _approve(db_session, _submit(db_session, "APM", "D365_NONSTOCK", "907"))
    assert r1.generated_code == "90700000001"
    assert r2.generated_code == "90700000002"


def test_override_code_logs_and_rejects_duplicates(db_session):
    r1 = _approve(db_session, _submit(db_session, "APM", "D365_NONSTOCK", "907"))
    r2 = _approve(db_session, _submit(db_session, "APM", "D365_NONSTOCK", "907"))
    override_code(db_session, r2.id, new_code="90700009999", actor="test")
    assert r2.generated_code == "90700009999"
    with pytest.raises(RequestError):
        override_code(db_session, r1.id, new_code="90700009999", actor="test")
    assert [e.action for e in r2.events][-1] == "code_overridden"


def test_mould_without_subgroup_fails_cleanly(db_session):
    req = _submit(db_session, "APG", "D365_STOCK", "806", sub_code="001")
    # simulate config mistake: drop the subgroup after submission
    req.subgroup_id = None
    db_session.commit()
    with pytest.raises(RequestError, match="หมวดย่อย"):
        _approve(db_session, req)
