"""STORY-013 ticket 05: the classified-master import uses the one Name Prefix rule."""

import io

from openpyxl import Workbook
from sqlalchemy import select

from app.models import ItemSnapshot
from app.services.snapshots import import_labeled_master, normalize

HEADER = ["Item Number", "Product Name", "Category Code", "Sub-Category Code"]


def _xlsx(rows) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(HEADER)
    for r in rows:
        ws.append(list(r))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _searchable(db, rows, item_number: str) -> str:
    import_labeled_master(db, filename="master.xlsx", data=_xlsx(rows),
                          uploaded_by="admin@test.local")
    return db.scalar(select(ItemSnapshot.normalized_name)
                     .where(ItemSnapshot.item_number == item_number))


def test_a_name_with_its_own_prefix_is_cut_as_before(db_session):
    # 900-01's Name Prefix is BEARING.
    got = _searchable(db_session, [("90001000001", "BEARING - Ball Bearing 6205 - 20 L", "900", "01")],
                      "90001000001")
    assert got == normalize("Ball Bearing 6205 - 20 L")


def test_the_prefix_is_matched_without_case(db_session):
    got = _searchable(db_session, [("90001000001", "Bearing - ตลับลูกปืน 6205", "900", "01")],
                      "90001000001")
    assert got == normalize("ตลับลูกปืน 6205")


def test_another_categorys_prefix_is_not_cut(db_session):
    # The old rule cut everything before the first " - " and kept "Oil Seal".
    got = _searchable(db_session, [("90001000001", "SEAL - Oil Seal", "900", "01")],
                      "90001000001")
    assert got == normalize("SEAL - Oil Seal")


def test_a_name_override_without_a_prefix_keeps_its_first_segment(db_session):
    # The old rule kept only "20 L".
    got = _searchable(db_session, [("90001000001", "Ball Bearing SKF - 20 L", "900", "01")],
                      "90001000001")
    assert got == normalize("Ball Bearing SKF - 20 L")


def test_a_name_without_any_separator_is_kept_whole(db_session):
    got = _searchable(db_session, [("90001000001", "Ball Bearing", "900", "01")],
                      "90001000001")
    assert got == normalize("Ball Bearing")


# --- Review 2026-10-20: a Sub-Category the portal does not know refuses the file ------------------------

def test_a_row_in_an_unknown_sub_category_refuses_the_whole_file(db_session):
    import pytest

    from app.services.snapshots import SnapshotError

    rows = [("90001000001", "BEARING - Ball Bearing 6205", "900", "01"),
            ("90027000001", "NEW CAT - Something new", "900", "27")]  # 900-27: not in the taxonomy
    with pytest.raises(SnapshotError) as refused:
        import_labeled_master(db_session, filename="master.xlsx", data=_xlsx(rows),
                              uploaded_by="admin@test.local")
    message = str(refused.value)
    assert "900-27" in message and "taxonomy" in message
    assert "อัปเดต" in message  # tells the uploader what to do first
    db_session.rollback()
    assert db_session.scalar(select(ItemSnapshot.id).where(  # nothing imported
        ItemSnapshot.item_number == "90001000001", ItemSnapshot.source == "CENTRAL")) is None


def test_check_only_callers_without_prefixes_are_unchanged():
    # Without the taxonomy, nothing is cut and no Sub-Category is refused.
    from app.services.snapshots import check_labeled_master

    check = check_labeled_master("m.xlsx", _xlsx([("90027000001", "NEW CAT - X", "900", "27")]))
    assert not check.invalid and check.valid[0]["searchable"] == "NEW CAT - X"


def test_an_unknown_sub_category_is_not_called_an_invalid_code(db_session):
    import pytest

    from app.services.snapshots import SnapshotError

    rows = [("90027000001", "NEW CAT - X", "900", "27"),
            ("90028000001", "NEW CAT - Y", "900", "28")]
    with pytest.raises(SnapshotError) as refused:
        import_labeled_master(db_session, filename="master.xlsx", data=_xlsx(rows),
                              uploaded_by="admin@test.local")
    message = str(refused.value)
    assert "พบหมวดที่ระบบไม่รู้จัก 2 แถว" in message
    assert "Central Code ที่ถูกต้อง" not in message and "รหัสไม่ถูกต้อง" not in message


def test_bad_codes_and_unknown_sub_categories_are_counted_apart(db_session):
    import pytest

    from app.services.snapshots import SnapshotError

    rows = [("90027000001", "NEW CAT - X", "900", "27"),     # unknown Sub-Category
            ("90001000001", "BEARING - X", "900", "02")]     # code does not match 900-02
    with pytest.raises(SnapshotError) as refused:
        import_labeled_master(db_session, filename="master.xlsx", data=_xlsx(rows),
                              uploaded_by="admin@test.local")
    message = str(refused.value)
    assert "พบรหัสที่ไม่ใช่ Central Code ที่ถูกต้อง 1 แถว" in message
    assert "พบหมวดที่ระบบไม่รู้จัก 1 แถว" in message
