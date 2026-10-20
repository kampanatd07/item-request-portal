"""STORY-013 ticket 03: a name without the old prefix is kept, with a warning."""

from sqlalchemy import select

from app.models import ItemRequest, RequestEvent
from app.services.requests import change_category, change_status, edit_name, submit_request
from tests.conftest import account_for, central_ids

PANEL_WARNING = "ชื่อไม่ได้ขึ้นต้นด้วย prefix ของหมวดเดิม (BEARING) — ตรวจและแก้ชื่อเอง"
NOTE = "ชื่อไม่ได้เปลี่ยน — ไม่ได้ขึ้นต้นด้วย prefix ของหมวดเดิม (BEARING)"
OVERRIDE = "Ball Bearing SKF - 20 L"  # a Name Override without any prefix


def _request(db) -> ItemRequest:
    factory, system, group, sub = central_ids(db)  # 900-01, BEARING
    req = submit_request(db, account_for(db, "requester", plant="APM"),
                         factory_id=factory.id, code_system_id=system.id, group_id=group.id,
                         subgroup_id=sub.id, item_name="Ball Bearing")
    edit_name(db, req.id, new_name=OVERRIDE, account=account_for(db, "procurement"))
    return req


def _seal(db):
    return central_ids(db, "APM", "900", "02")[3]


def _events(db, req: ItemRequest) -> list[RequestEvent]:
    db.expire_all()
    return list(db.scalars(select(RequestEvent).where(RequestEvent.request_id == req.id)
                           .order_by(RequestEvent.id)))


def test_the_move_goes_ahead_and_the_name_is_kept(app_db):
    req = _request(app_db)
    change_category(app_db, req.id, subgroup_id=_seal(app_db).id,
                    account=account_for(app_db, "procurement"))
    app_db.expire_all()
    req = app_db.get(ItemRequest, req.id)
    assert req.subgroup.code == "02" and req.item_name == OVERRIDE


def test_category_changed_says_the_name_did_not_change_and_nothing_is_renamed(app_db):
    req = _request(app_db)
    before = len(_events(app_db, req))
    change_category(app_db, req.id, subgroup_id=_seal(app_db).id,
                    account=account_for(app_db, "procurement"))
    new = _events(app_db, req)[before:]
    assert [e.action for e in new] == ["category_changed"]
    assert new[0].detail == f"900-01 -> 900-02\n{NOTE}"


def test_the_category_panel_warns_and_the_name_panel_keeps_warning(client_as, app_db):
    req = _request(app_db)
    r = client_as("procurement").post(f"/queue/{req.id}/category",
                                      data={"subgroup_id": _seal(app_db).id})
    assert r.status_code == 200, r.text
    category_part = r.text[:r.text.index('id="name-panel"')]
    assert PANEL_WARNING in category_part
    name_part = r.text[r.text.index('id="name-panel"'):]
    assert "ชื่อไม่ได้ขึ้นต้นด้วย prefix ของหมวดปัจจุบัน (SEAL)" in name_part  # ticket 01


def test_a_renamed_move_shows_no_kept_name_warning(client_as, app_db):
    factory, system, group, sub = central_ids(app_db)
    req = submit_request(app_db, account_for(app_db, "requester", plant="APM"),
                         factory_id=factory.id, code_system_id=system.id, group_id=group.id,
                         subgroup_id=sub.id, item_name="Ball Bearing")
    r = client_as("procurement").post(f"/queue/{req.id}/category",
                                      data={"subgroup_id": _seal(app_db).id})
    assert "prefix ของหมวดเดิม" not in r.text


def test_a_coded_move_keeps_the_name_and_still_reissues_the_code(app_db):
    req = _request(app_db)
    change_status(app_db, req.id, new_status="approved", account=account_for(app_db, "administrator"))
    app_db.expire_all()
    old_code = app_db.get(ItemRequest, req.id).generated_code
    before = len(_events(app_db, req))
    change_category(app_db, req.id, subgroup_id=_seal(app_db).id,
                    account=account_for(app_db, "administrator"))
    app_db.expire_all()
    req = app_db.get(ItemRequest, req.id)
    assert req.item_name == OVERRIDE and req.generated_code != old_code
    new = _events(app_db, req)[before:]
    assert [e.action for e in new] == ["category_changed", "code_reissued"]
    assert NOTE in new[0].detail


# --- Found while building this ticket: the move's response showed the old category -----------------
# On master too: after an uncoded move, req.subgroup still pointed at the old
# Sub-Category until a reload, so the category panel showed it and ticket 02's
# name panel warned against the old prefix.

def test_the_move_response_shows_the_new_category_and_no_stale_warning(client_as, app_db):
    factory, system, group, sub = central_ids(app_db)
    req = submit_request(app_db, account_for(app_db, "requester", plant="APM"),
                         factory_id=factory.id, code_system_id=system.id, group_id=group.id,
                         subgroup_id=sub.id, item_name="Ball Bearing")
    r = client_as("procurement").post(f"/queue/{req.id}/category",
                                      data={"subgroup_id": _seal(app_db).id})
    start = r.text.index("<h3>หมวดสินค้า</h3>")
    category_head = r.text[start:r.text.index("</p>", start)]
    assert "900-02" in category_head and "900-01" not in category_head
    assert "SEAL - Ball Bearing" in r.text
    assert "ชื่อไม่ได้ขึ้นต้นด้วย prefix" not in r.text


def test_the_history_keeps_the_notes_line_break(client_as, app_db):
    req = _request(app_db)
    change_category(app_db, req.id, subgroup_id=_seal(app_db).id,
                    account=account_for(app_db, "procurement"))
    page = client_as("procurement").get(f"/queue/{req.id}").text
    history = page[page.index("<h3>ประวัติ</h3>"):]
    cell = history[history.rindex("<td", 0, history.index(NOTE)):history.index(NOTE)]
    assert "white-space:pre-line" in cell
