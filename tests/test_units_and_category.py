"""Size normalization + category-style search names (Peter feedback 2026-07-30)."""

import io

import pytest
from openpyxl import Workbook
from sqlalchemy import select

from app.models import CodeGroup, CodeSystem, Factory
from app.services.classifier import classify
from app.services.requests import submit_request
from app.services.snapshots import import_snapshot
from app.services.units import normalize_size


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("4 นิ้ว", '4"'),
        ("4นิ้ว", '4"'),
        ("4 inch", '4"'),
        ("4 IN", '4"'),
        ('4"', '4"'),
        ("25 CM", "25cm"),
        ("25cm.", "25cm"),
        ("25 ซม.", "25cm"),
        ("1000 มม.", "1000mm"),
        ("2 ลิตร", "2L"),
        ("500 มล.", "500ml"),
        ("1.5 กก.", "1.5kg"),
        ("10 X 20", "10x20"),
        ("10*20", "10x20"),
        ("10 x 20 x 5", "10x20x5"),
        ("10 mm. x 20 mm.", "10mmx20mm"),
        ("  4  cm  ", "4cm"),
        ("", ""),
        (None, ""),
    ],
)
def test_normalize_size_variants(raw, expected):
    assert normalize_size(raw) == expected


def test_labeled_dimensions_reorder_to_w_l_h():
    assert normalize_size("กว้าง 10 สูง 20") == "10x20"
    assert normalize_size("สูง 20 กว้าง 10") == "10x20"  # same spec, one form
    assert normalize_size("กว้าง 10 ยาว 30 สูง 20") == "10x30x20"


def test_bare_numbers_are_never_reordered():
    # 20x10 and 10x20 may mean different things — only formatting is touched
    assert normalize_size("20 X 10") == "20x10"


def test_thread_spec_preserved():
    assert normalize_size("M12 x 1.75 x 40") == "M12x1.75x40"


def test_thai_item_gets_thai_category_not_brand(db_session):
    """Regression: 'ตะปู' + brand XXX + model #12345 used to suggest 'XXX 12345'."""
    result = classify(db_session, "ตะปู")
    assert result["suggestion"] == "ตะปู"
    assert result["source"] == "dictionary"


def test_thai_categories_from_dictionary(db_session):
    assert classify(db_session, "ลูกปืน 6205")["suggestion"] == "ลูกปืน"
    assert classify(db_session, "สายไฟ VCT 2x1.5")["suggestion"] == "สายไฟ"
    assert classify(db_session, "งานสอบเทียบเครื่องชั่ง")["suggestion"] == "งานสอบเทียบ"


def test_unknown_name_falls_back_to_the_name_itself(db_session):
    r = classify(db_session, "ฟลักซ์คาปาซิเตอร์")
    assert r["source"] == "fallback"
    assert r["suggestion"] == "ฟลักซ์คาปาซิเตอร์"  # not brand/model garbage


def test_neighbour_vote_learns_category_from_master(db_session):
    wb = Workbook()
    wb.active.append(["Item number", "Product name"])
    for code, name in [
        ("64FQ000131", "ตะปู 2-1/2 #12 P"),
        ("64FQ000132", "ตะปู ยิงไม้ WT64"),
        ("64FQ000133", "ตะปู เกลียวปล่อย"),
    ]:
        wb.active.append([code, name])
    buf = io.BytesIO()
    wb.save(buf)
    import_snapshot(db_session, source="CBD", filename="m.xlsx", data=buf.getvalue())

    # a name the dictionary doesn't know, but the master's neighbours do
    r = classify(db_session, "ตะปูคอนกรีตพิเศษ", snapshot_source="CBD")
    assert r["suggestion"] == "ตะปู"
    assert r["source"] in {"dictionary", "neighbours"}


def test_submit_normalizes_size_in_name_and_field(db_session):
    factory = db_session.scalar(select(Factory).where(Factory.code == "CBD"))
    system = db_session.scalar(select(CodeSystem).where(CodeSystem.code == "CBD_NONSTOCK"))
    group = db_session.scalar(
        select(CodeGroup).where(
            CodeGroup.code_system_id == system.id, CodeGroup.code == "FQ",
            CodeGroup.parent_id.is_(None),
        )
    )
    req = submit_request(
        db_session, requester_name="p", requester_email="p@x.com",
        factory_id=factory.id, code_system_id=system.id, group_id=group.id,
        subgroup_id=None, item_name="ตะปู", brand="XXX", model="#12345",
        size="4 นิ้ว", variant="ดำ",
    )
    assert req.size == '4"'
    assert req.item_name == 'ตะปู XXX #12345 4" ดำ'
    assert req.search_name == "ตะปู"  # category, not 'XXX 12345'
