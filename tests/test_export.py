"""Export tests. Column headers are asserted against the REAL temp templates in
`Up load Item Temp/` so a template change is caught, not silently mismatched."""

import io
from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook
from sqlalchemy import select

from app.models import CodeGroup, CodeSystem, ExportBatch, Factory, ItemRequest
from app.services.exporter import build_workbook_bytes, export_pending
from app.services.requests import change_status, submit_request
from app.services.snapshots import import_snapshot
from tests.conftest import central_ids

TEMP_DIR = Path(__file__).resolve().parent / "fixtures"

TEMP_FILES = {
    "CBD": ("Temp Up Load Item - CBD.xlsx",
            {"CBD_ReleasedProduct_Template_RE": 1, "CBG_ItemWMSsetupEntity": 0}),
    "APM": ("Temp Up Load Item - APM.xlsx",
            {"Products_V2": 0, "Released_products_V2": 0,
             "Product_category_assignments": 0, "Default_order_settings": 0,
             "CBG_ItemWMSsetupEntity": 0}),
    "ACM": ("Temp Up Load Item - ACM.xlsx",
            {"ACM - Item Update": 0, "ACM Purecument Category": 0,
             "CBG_ItemWMSsetupEntity": 0}),
}


def _headers(path, sheet, hdr_row):
    wb = load_workbook(path, read_only=True)
    ws = wb[sheet]
    rows = list(ws.iter_rows(min_row=hdr_row + 1, max_row=hdr_row + 1, values_only=True))
    wb.close()
    return [("" if c is None else str(c)).strip() for c in rows[0] if c is not None]


def _submit_approve(db, factory_code, group_code="900", sub_code="01", **extra):
    factory, system, group, sub = central_ids(db, factory_code, group_code, sub_code)
    req = submit_request(
        db, requester_name="ทดสอบ", requester_email="t@example.com",
        factory_id=factory.id, code_system_id=system.id, group_id=group.id,
        subgroup_id=sub.id, item_name=extra.get("name", "Test item"),
        uom=extra.get("uom", "EA"), procurement_category=extra.get("cat", ""),
        purchase_price=extra.get("price", ""),
    )
    return change_status(db, req.id, new_status="approved", actor="test")


@pytest.mark.parametrize("factory_code", ["CBD", "APM", "ACM"])
def test_export_headers_match_real_template(db_session, factory_code):
    fname, sheets = TEMP_FILES[factory_code]
    temp_path = TEMP_DIR / fname
    if not temp_path.exists():
        pytest.skip(f"temp template not available: {fname}")

    _submit_approve(db_session, factory_code, "907", "01",
                    name="MA Cisco", cat="54050102 Computer expenses", price="2320")

    reqs = list(db_session.scalars(select(ItemRequest)))
    data = build_workbook_bytes(db_session, factory_code, reqs)
    wb = load_workbook(io.BytesIO(data))

    assert set(wb.sheetnames) == set(sheets), f"{factory_code} sheet names differ"
    for sheet, hdr_row in sheets.items():
        expected = _headers(temp_path, sheet, hdr_row)
        got = [c for c in next(wb[sheet].iter_rows(max_row=1, values_only=True)) if c]
        assert got == expected, f"{factory_code}/{sheet} header mismatch"


def test_export_populates_variable_fields(db_session):
    req = _submit_approve(
        db_session, "APM", "707", "01",
        name="MA Cisco Catalyst 9120AX", uom="JOB", cat="54050102 Computer expenses",
        price="2320",
    )
    data = build_workbook_bytes(db_session, "APM", [req])
    wb = load_workbook(io.BytesIO(data))
    prod = list(wb["Products_V2"].iter_rows(min_row=2, values_only=True))[0]
    assert prod[0] == req.generated_code
    assert "MA Cisco Catalyst 9120AX" in prod[1]
    assert prod[5] == "Service"
    cat = list(wb["Product_category_assignments"].iter_rows(min_row=2, values_only=True))[0]
    assert cat[1] == "54050102 Computer expenses"


def test_export_pending_marks_exported_and_batches(db_session):
    factory, _s, _g, _sub = central_ids(db_session, "APM")
    r1 = _submit_approve(db_session, "APM", name="A")
    r2 = _submit_approve(db_session, "APM", name="B")
    batch = export_pending(db_session, factory.id)
    assert batch.item_count == 2
    db_session.refresh(r1)
    db_session.refresh(r2)
    assert r1.status == "exported" and r1.export_batch_id == batch.id
    # nothing left pending -> second export raises
    from app.services.exporter import ExportError
    with pytest.raises(ExportError):
        export_pending(db_session, factory.id)


def test_exported_then_created_flow(db_session):
    factory, _s, _g, _sub = central_ids(db_session, "APG")
    _submit_approve(db_session, "APG", name="Bearing")
    batch = export_pending(db_session, factory.id)
    reqs = list(
        db_session.scalars(
            select(ItemRequest).where(ItemRequest.export_batch_id == batch.id)
        )
    )
    for r in reqs:
        change_status(db_session, r.id, new_status="created", actor="test")
    db_session.refresh(reqs[0])
    assert reqs[0].status == "created"
