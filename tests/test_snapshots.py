import io

import pytest
from openpyxl import Workbook

from app.services.snapshots import (
    SnapshotError,
    import_snapshot,
    normalize,
    search_similar,
    similarity,
)


def _xlsx(rows: list[tuple[str, str, str]]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(["Item number", "Product name", "Item group"])
    for r in rows:
        ws.append(list(r))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


SAMPLE = [
    ("80000000048", "Bearing 3208 SKF", "IM-SP"),
    ("80000000053", "Bearing 6204 2RSSH SKF", "IM-SP"),
    ("80100000001", "น้ำมันไฮดรอลิค Shell Tellus S2 M46", "IM-Oil"),
    ("90700000012", "WEBCAM Logitech C270 Black", "IM-IT"),
]


def test_normalize_collapses_noise():
    assert normalize("  BALL-BEARING   SKF ") == "ball bearing skf"
    assert normalize("สกรูน๊อตมิลดำ M12 x 1.75") == normalize("สกรูน๊อตมิลดำ m12 X 1.75")


def test_similarity_orders_close_names_higher():
    close = similarity(normalize("Bearing 6204 SKF"), normalize("Bearing 6204 2RSSH SKF"))
    far = similarity(normalize("Bearing 6204 SKF"), normalize("WEBCAM Logitech C270"))
    assert close > far


def test_import_and_search_happy_path(db_session):
    imp = import_snapshot(
        db_session, source="D365", filename="master.xlsx", data=_xlsx(SAMPLE)
    )
    assert imp.row_count == 4

    hits = search_similar(db_session, source="D365", query="bearing 6204 skf")
    assert hits, "expected at least one match"
    assert hits[0][0].item_number == "80000000053"

    # Thai names match despite spacing/case differences
    hits_th = search_similar(db_session, source="D365", query="น้ำมันไฮดรอลิค shell")
    assert hits_th[0][0].item_number == "80100000001"


def test_reimport_replaces_source_rows(db_session):
    import_snapshot(db_session, source="D365", filename="a.xlsx", data=_xlsx(SAMPLE))
    import_snapshot(
        db_session, source="D365", filename="b.xlsx", data=_xlsx(SAMPLE[:1])
    )
    hits = search_similar(db_session, source="D365", query="webcam logitech")
    assert hits == []


def test_import_rejects_file_without_headers(db_session):
    wb = Workbook()
    wb.active.append(["foo", "bar"])
    buf = io.BytesIO()
    wb.save(buf)
    with pytest.raises(SnapshotError):
        import_snapshot(db_session, source="D365", filename="bad.xlsx", data=buf.getvalue())


def test_duplicate_fragment_and_submit_audit(client, db_session):
    from sqlalchemy import select

    from app.models import CodeGroup, CodeSystem, Factory, RequestEvent

    import_snapshot(db_session, source="D365", filename="m.xlsx", data=_xlsx(SAMPLE))
    factory = db_session.scalar(select(Factory).where(Factory.code == "APM"))

    resp = client.post(
        "/fragments/duplicates",
        data={"factory_id": factory.id, "item_name": "Bearing 6204", "brand": "SKF"},
    )
    assert resp.status_code == 200
    assert "80000000053" in resp.text

    system = db_session.scalar(select(CodeSystem).where(CodeSystem.code == "D365_STOCK"))
    group = db_session.scalar(
        select(CodeGroup).where(
            CodeGroup.code_system_id == system.id, CodeGroup.code == "800"
        )
    )
    client.post(
        "/requests",
        data={
            "requester_name": "ทดสอบ",
            "requester_email": "t@example.com",
            "factory_id": factory.id,
            "code_system_id": system.id,
            "group_id": group.id,
            "item_name": "Bearing 6204",
            "brand": "SKF",
        },
    )
    event = db_session.scalar(select(RequestEvent))
    assert event.detail and "80000000053" in event.detail
