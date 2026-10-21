"""STORY-013 ticket 02: a category move swaps the Name Prefix in the Item Name."""

import pytest
from sqlalchemy import select

from app.models import ItemRequest, RequestEvent, RunningRegister
from app.services.requests import (
    RequestError,
    change_category,
    change_status,
    edit_name,
    resubmit_request,
    submit_request,
)
from tests.conftest import account_for, central_ids


def _request(db, base: str = "Ball Bearing", **fields) -> ItemRequest:
    factory, system, group, sub = central_ids(db)  # 900-01, prefix BEARING
    return submit_request(db, account_for(db, "requester", plant="APM"),
                          factory_id=factory.id, code_system_id=system.id, group_id=group.id,
                          subgroup_id=sub.id, item_name=base, **fields)


def _sub(db, group: str, sub: str):
    return central_ids(db, "APM", group, sub)[3]


def _move(db, req: ItemRequest, group: str = "900", sub: str = "02", role: str = "procurement"):
    return change_category(db, req.id, subgroup_id=_sub(db, group, sub).id,
                           account=account_for(db, role))


def _fresh(db, req: ItemRequest) -> ItemRequest:
    db.expire_all()
    return db.get(ItemRequest, req.id)


def _actions(db, req: ItemRequest) -> list[tuple[str, str | None]]:
    db.expire_all()
    return [(e.action, e.detail) for e in db.scalars(
        select(RequestEvent).where(RequestEvent.request_id == req.id).order_by(RequestEvent.id))]


def _register(db, group: str, sub: str) -> int:
    return db.scalar(select(RunningRegister.last_running).where(
        RunningRegister.group_code == group, RunningRegister.sub_code == sub))


# --- AC1-3: only the prefix changes --------------------------------------------------------------------

def test_a_move_swaps_only_the_prefix(app_db):
    req = _request(app_db, brand="SKF", size="20 L")
    assert req.item_name == "BEARING - Ball Bearing SKF - 20 L"
    _move(app_db, req)  # → 900-02 SEAL
    assert _fresh(app_db, req).item_name == "SEAL - Ball Bearing SKF - 20 L"


def test_a_name_override_keeps_its_name_and_detail(app_db):
    req = _request(app_db)
    edit_name(app_db, req.id, new_name="BEARING - ลูกปืนพิเศษ 6205 - ขนาด 20 L",
              account=account_for(app_db, "procurement"))
    _move(app_db, req, "900", "04")  # PIPE FITTING
    assert _fresh(app_db, req).item_name == "PIPE FITTING - ลูกปืนพิเศษ 6205 - ขนาด 20 L"


def test_the_old_prefix_is_matched_without_case_and_written_upper(app_db):
    req = _request(app_db)
    edit_name(app_db, req.id, new_name="Bearing - Ball Bearing",
              account=account_for(app_db, "procurement"))
    _move(app_db, req)
    assert _fresh(app_db, req).item_name == "SEAL - Ball Bearing"


def test_a_move_to_another_item_group_before_a_code(app_db):
    req = _request(app_db)
    _move(app_db, req, "702", "01")
    assert _fresh(app_db, req).item_name == "CALIBRATION - Ball Bearing"


# --- AC6: the events ---------------------------------------------------------------------------------

def test_the_rename_is_its_own_event_after_category_changed(app_db):
    req = _request(app_db)
    before = len(_actions(app_db, req))
    _move(app_db, req)
    assert _actions(app_db, req)[before:] == [
        ("category_changed", "900-01 -> 900-02"),
        ("name_prefix_changed", "BEARING - Ball Bearing → SEAL - Ball Bearing"),
    ]


def test_the_history_labels_the_rename(client_as, app_db):
    req = _request(app_db)
    _move(app_db, req)
    assert "เปลี่ยน prefix ตามหมวด" in client_as("procurement").get(f"/queue/{req.id}").text


# --- AC7: an Administrator's move of a coded request --------------------------------------------------

def test_a_coded_move_reissues_the_code_and_renames(app_db):
    req = _request(app_db)
    change_status(app_db, req.id, new_status="approved", account=account_for(app_db, "administrator"))
    before = len(_actions(app_db, req))
    _move(app_db, req, role="administrator")
    req = _fresh(app_db, req)
    assert req.item_name == "SEAL - Ball Bearing" and req.generated_code.startswith("90002")
    assert [a for a, _ in _actions(app_db, req)[before:]] == [
        "category_changed", "name_prefix_changed", "code_reissued"]


# --- AC5: too long → refused, nothing changes ----------------------------------------------------------

def _long_override(db, req: ItemRequest) -> str:
    # 110 characters with BEARING (7); PACK MACH PART (14) would make it 117.
    name = "BEARING - " + "x" * 100
    edit_name(db, req.id, new_name=name, account=account_for(db, "procurement"))
    return name


def test_a_move_that_makes_the_name_too_long_is_refused(app_db):
    req = _request(app_db)
    name = _long_override(app_db, req)
    before = _actions(app_db, req)
    with pytest.raises(RequestError) as refused:
        _move(app_db, req, "900", "08")
    assert "117" in str(refused.value) and "110" in str(refused.value)
    req = _fresh(app_db, req)
    assert req.item_name == name and (req.group.code, req.subgroup.code) == ("900", "01")
    assert _actions(app_db, req) == before


def test_a_refused_coded_move_keeps_the_code_and_the_register(app_db):
    req = _request(app_db)
    change_status(app_db, req.id, new_status="approved", account=account_for(app_db, "administrator"))
    code = _fresh(app_db, req).generated_code
    _long_override(app_db, req)
    registers = (_register(app_db, "900", "01"), _register(app_db, "900", "08"))
    with pytest.raises(RequestError):
        _move(app_db, req, "900", "08", role="administrator")
    req = _fresh(app_db, req)
    assert req.generated_code == code and req.subgroup.code == "01"
    assert (_register(app_db, "900", "01"), _register(app_db, "900", "08")) == registers


def test_exactly_110_after_the_swap_is_allowed(app_db):
    req = _request(app_db)
    edit_name(app_db, req.id, new_name="BEARING - " + "x" * 93,  # 10 + 93 = 103
              account=account_for(app_db, "procurement"))
    _move(app_db, req, "900", "08")  # PACK MACH PART - x*93 = 17 + 93 = 110
    assert len(_fresh(app_db, req).item_name) == 110


# --- AC8: the name panel is updated with the category panel ---------------------------------------------

def test_the_move_response_updates_the_name_panel(client_as, app_db):
    req = _request(app_db)
    r = client_as("procurement").post(f"/queue/{req.id}/category",
                                      data={"subgroup_id": _sub(app_db, "900", "02").id})
    assert r.status_code == 200, r.text
    assert 'id="name-panel"' in r.text and 'hx-swap-oob="innerHTML"' in r.text
    oob = r.text[r.text.index('id="name-panel"'):]
    assert "SEAL - Ball Bearing" in oob


def test_a_refused_move_updates_nothing(client_as, app_db):
    req = _request(app_db)
    _long_override(app_db, req)
    r = client_as("procurement").post(f"/queue/{req.id}/category",
                                      data={"subgroup_id": _sub(app_db, "900", "08").id})
    assert r.status_code == 422 and "117" in r.text
    assert 'hx-swap-oob' not in r.text


# --- AC10: the rename is not a name setter for STORY-009's replaced-name warning --------------------

def test_a_typed_name_moved_then_replaced_by_a_resubmit_still_warns(client_as, app_db):
    req = _request(app_db, brand="SKF")
    proc = account_for(app_db, "procurement")
    edit_name(app_db, req.id, new_name="BEARING - Ball Bearing SKF แบบพิเศษ", account=proc)
    _move(app_db, req)  # SEAL - Ball Bearing SKF แบบพิเศษ
    change_status(app_db, req.id, new_status="needs_info", note="ขอขนาด", account=proc)
    req = _fresh(app_db, req)
    resubmit_request(app_db, req.id, account_for(app_db, "requester", plant="APM"),
                     reply="เพิ่มขนาดแล้ว", code_system_id=req.code_system_id,
                     group_id=req.group_id, subgroup_id=req.subgroup_id, item_name=req.base_name,
                     brand=req.brand, size="20 L", search_name=req.search_name)
    page = client_as("procurement").get(f"/queue/{req.id}").text
    assert ("ชื่อที่จัดซื้อแก้ไว้ถูกแทนที่: SEAL - Ball Bearing SKF แบบพิเศษ → "
            "SEAL - Ball Bearing SKF - 20 L") in page


# --- Review 2026-10-20: a Sub-Category without a Name Prefix (pinned) ---------------------------------
# The seed refuses an empty CENTRAL prefix, so this needs a hand-edited row.

def _without_prefix(db, group: str, sub: str) -> None:
    _sub(db, group, sub).name_prefix = None
    db.commit()


def test_a_move_into_a_category_without_a_prefix_drops_it_like_compose_name(app_db):
    from app.services.naming import compose_name

    req = _request(app_db)
    _without_prefix(app_db, "900", "02")
    _move(app_db, req)
    assert _fresh(app_db, req).item_name == compose_name("Ball Bearing") == "Ball Bearing"
    assert ("name_prefix_changed", "BEARING - Ball Bearing → Ball Bearing") in _actions(app_db, req)


def test_a_move_out_of_a_category_without_a_prefix_leaves_the_name(app_db):
    req = _request(app_db)
    _without_prefix(app_db, "900", "01")
    _move(app_db, req)
    assert _fresh(app_db, req).item_name == "BEARING - Ball Bearing"
    assert "name_prefix_changed" not in [a for a, _ in _actions(app_db, req)]
