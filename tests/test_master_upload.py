"""STORY-010 ticket 02: the classified master holds only valid Central Codes,
and its upload warns when the register is behind the group."""

import io

import pytest
from openpyxl import Workbook
from sqlalchemy import select

from app.models import ItemSnapshot, RunningRegister
from app.services.snapshots import (
    SnapshotError,
    check_labeled_master,
    import_labeled_master,
    register_lag,
)

HEADER = ["Item Number", "Product Name", "Category Code", "Sub-Category Code"]
GOOD = [
    ("90001000001", "BEARING - Ball Bearing SKF 6205", "900", "01"),
    ("90001000002", "BEARING - Ball Bearing SKF 6206", "900", "01"),
]


def _xlsx(rows, header=HEADER, title_rows=0) -> bytes:
    wb = Workbook()
    ws = wb.active
    for _ in range(title_rows):
        ws.append(["Carabao Group Item Master"])
    ws.append(header)
    for r in rows:
        ws.append(list(r))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _load(db, rows):
    return import_labeled_master(db, filename="master.xlsx", data=_xlsx(rows),
                                 uploaded_by="admin@test.local")


def _central(db) -> list[str]:
    return sorted(db.scalars(select(ItemSnapshot.item_number)
                             .where(ItemSnapshot.source == "CENTRAL")))


def _register(db, group="900", sub="01") -> int:
    return db.scalar(select(RunningRegister.last_running).where(
        RunningRegister.group_code == group, RunningRegister.sub_code == sub))


# --- Rows that reject the whole file ------------------------------------------------------------

@pytest.mark.parametrize("bad,reason", [
    (("9000100001", "BEARING - X", "900", "01"), "11 หลัก"),          # 10 digits
    (("90001000A01", "BEARING - X", "900", "01"), "11 หลัก"),         # not digits
    (("90101000003", "BEARING - X", "900", "01"), "หลัก 1–3"),        # wrong group
    (("90002000003", "BEARING - X", "900", "01"), "หลัก 4–5"),        # wrong sub
    (("90001010003", "BEARING - X", "900", "01"), "หลัก 6–7"),        # item type not 00
    (("90001000003", "BEARING - X", "", "01"), "Category Code"),      # blank category
    (("90001000003", "BEARING - X", "900", ""), "Category Code"),     # blank sub
    (("90001000003", "", "900", "01"), "Product Name"),               # blank name
])
def test_one_bad_coded_row_rejects_the_whole_file_and_keeps_the_old_load(db_session, bad, reason):
    _load(db_session, GOOD)
    with pytest.raises(SnapshotError) as e:
        _load(db_session, [GOOD[0], bad, GOOD[1]])
    assert "แถว 3" in str(e.value) and reason in str(e.value)  # header is row 1
    assert _central(db_session) == ["90001000001", "90001000002"]


def test_rows_without_an_item_number_are_skipped(db_session):
    imp = _load(db_session, GOOD + [("", "PENDING - รอตัดสินใจ", "900", "01"),
                                    (None, "PENDING - อีกรายการ", None, None)])
    assert imp.row_count == 2 and _central(db_session) == ["90001000001", "90001000002"]


def test_counts_total_valid_skipped_invalid_without_writing(db_session):
    rows = GOOD + [("", "PENDING", "900", "01"), ("123", "X - y", "900", "01")]
    check = check_labeled_master("master.xlsx", _xlsx(rows, title_rows=2))
    assert (check.total, len(check.valid), check.skipped, len(check.invalid)) == (4, 2, 1, 1)
    assert check.invalid[0].row == 7  # 2 title rows + header + 3 rows before it
    assert _central(db_session) == []  # nothing written


def test_numbers_stored_as_excel_numbers_read_as_the_same_code(db_session):
    _load(db_session, [(90001000001, "BEARING - A", 900, 1),
                       (90001000002.0, "BEARING - B", 900.0, 1.0)])
    assert _central(db_session) == ["90001000001", "90001000002"]


def test_many_bad_rows_list_ten_and_count_the_rest(db_session):
    bad = [(f"9000100{i:04d}0", "BEARING - X", "900", "01") for i in range(13)]  # 12 digits
    with pytest.raises(SnapshotError) as e:
        _load(db_session, bad)
    assert "13 แถว" in str(e.value) and "และอีก 3 แถว" in str(e.value)


def test_blank_lines_are_not_counted(db_session):
    check = check_labeled_master("master.xlsx", _xlsx(GOOD + [(None, None, None, None)]))
    assert check.total == 2


# --- Register lag warning -----------------------------------------------------------------------

def test_register_lag_lists_only_sub_categories_ahead_of_the_register(db_session):
    r01, r02 = _register(db_session, "900", "01"), _register(db_session, "900", "02")
    numbers = [f"9000100{r01 + 5:04d}", f"9000100{r01:04d}",    # 900-01 ahead by 5
               f"9000200{r02:04d}",                              # 900-02 level
               f"9000300{max(_register(db_session, '900', '03') - 1, 0):04d}"]  # behind
    lags = register_lag(db_session, numbers)
    assert [(l.group_code, l.sub_code, l.register, l.master, l.gap) for l in lags] == [
        ("900", "01", r01, r01 + 5, 5)]


def test_upload_page_shows_the_warning_and_never_moves_the_register(client, app_db):
    r01 = _register(app_db)
    rows = [(f"9000100{r01 + 3:04d}", "BEARING - Ahead", "900", "01")]
    r = client.post("/admin/snapshots/labeled",
                    files={"file": ("master.xlsx", _xlsx(rows),
                                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.status_code == 200
    assert "Running Register ตามหลัง" in r.text and "STORY-005" in r.text
    assert f"<td>900-01</td><td>{r01}</td><td>{r01 + 3}</td><td>3</td>" in r.text
    assert _register(app_db) == r01


def test_no_warning_when_the_register_is_level(client, app_db):
    r01 = _register(app_db)
    rows = [(f"9000100{r01:04d}", "BEARING - Level", "900", "01")]
    r = client.post("/admin/snapshots/labeled",
                    files={"file": ("master.xlsx", _xlsx(rows),
                                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.status_code == 200 and "ตามหลัง" not in r.text


def test_rejected_upload_is_a_422_with_row_numbers(client):
    r = client.post("/admin/snapshots/labeled",
                    files={"file": ("master.xlsx", _xlsx([("123", "X - y", "900", "01")]),
                                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.status_code == 422 and "แถว 2" in r.text


def test_procurement_cannot_upload_the_master(client_as):
    r = client_as("procurement").post("/admin/snapshots/labeled",
                                      files={"file": ("m.xlsx", _xlsx(GOOD), "application/octet-stream")})
    assert r.status_code == 403


def test_float_cells_read_as_whole_numbers():
    # Excel may store a big code as 9.0001000002E+10, which openpyxl returns as
    # a float; str() of that would be "90001000002.0" and fail the 11-digit rule.
    from app.services.snapshots import _cell_text

    assert _cell_text(90001000002.0) == "90001000002"
    assert _cell_text(900.0) == "900" and _cell_text(1.0) == "1"
    assert _cell_text(12.5) == "12.5" and _cell_text(None) == "" and _cell_text(" a ") == "a"


@pytest.mark.parametrize("number,group,sub", [
    ("๙๐๐๐๑๐๐๐๐๐๑", "๙๐๐", "๐๑"),        # Thai numerals throughout
    ("๙๐๐๐๑00๐๐๐๑", "๙๐๐", "๐๑"),        # Thai, but ASCII "00": passes every other rule
    ("90001000001", "๙๐๐", "01"),            # Thai numerals in the category only
    ("９０００１０００００１", "900", "01"),   # fullwidth digits
])
def test_non_ascii_digits_are_invalid(db_session, number, group, sub):
    check = check_labeled_master("m.xlsx", _xlsx([(number, "BEARING - X", group, sub)]))
    assert len(check.invalid) == 1 and not check.valid
