"""STORY-009 ticket 05: Procurement sees resubmits clearly in the queue."""

import re

from sqlalchemy.orm import Session

from app.models import ItemRequest
from app.services.requests import (
    change_status,
    edit_name,
    requeue_request,
    resubmit_request,
    submit_request,
)
from tests.conftest import account_for, central_ids

REPLY = "เพิ่มขนาด 20 L แล้วครับ"
TYPED = "BEARING - Ball Bearing SKF รุ่นพิเศษ"


def _requester(db: Session):
    return account_for(db, "requester", plant="APM")


def _proc(db: Session):
    return account_for(db, "procurement")


def _submit(db: Session, base: str = "Ball Bearing") -> ItemRequest:
    factory, system, group, sub = central_ids(db)
    return submit_request(db, _requester(db), factory_id=factory.id, code_system_id=system.id,
                          group_id=group.id, subgroup_id=sub.id, item_name=base, brand="SKF")


def _needs_info(db: Session, req: ItemRequest) -> None:
    change_status(db, req.id, new_status="needs_info", note="ขอขนาด", account=_proc(db))


def _resubmit(db: Session, req: ItemRequest, **over) -> ItemRequest:
    db.expire_all()
    req = db.get(ItemRequest, req.id)
    fields = {"code_system_id": req.code_system_id, "group_id": req.group_id,
              "subgroup_id": req.subgroup_id, "item_name": req.base_name, "brand": req.brand,
              "size": req.size, "search_name": req.search_name}
    fields.update(over)
    return resubmit_request(db, req.id, _requester(db), reply=REPLY, **fields)


def _row(page: str, req: ItemRequest) -> str:
    """The queue table row of this request."""
    match = re.search(rf'<tr>\s*<td><a href="/queue/{req.id}">.*?</tr>', page, re.S)
    assert match, page
    return match.group(0)


def _summary(page: str) -> str:
    match = re.search(r'<div class="card" id="resubmit-summary".*?</div>', page, re.S)
    return match.group(0) if match else ""


# --- Queue badge ---------------------------------------------------------------------------------------

def test_the_badge_shows_on_a_resubmitted_request_only(client_as, app_db):
    new = _submit(app_db, base="Seal Ring")
    back = _submit(app_db)
    _needs_info(app_db, back)
    _resubmit(app_db, back, size="20 L")
    page = client_as("procurement").get("/queue").text
    assert "ส่งกลับแล้ว" in _row(page, back)
    assert "ส่งกลับแล้ว" not in _row(page, new)


def test_the_badge_shows_after_the_requeue_button_too(client_as, app_db):
    req = _submit(app_db)
    _needs_info(app_db, req)
    requeue_request(app_db, req.id, _proc(app_db), "ผู้ขอโทรมาแจ้งแล้ว")
    assert "ส่งกลับแล้ว" in _row(client_as("procurement").get("/queue").text, req)


def test_no_badge_once_the_request_moves_on(client_as, app_db):
    req = _submit(app_db)
    _needs_info(app_db, req)
    _resubmit(app_db, req)
    change_status(app_db, req.id, new_status="in_review", account=_proc(app_db))
    assert "ส่งกลับแล้ว" not in _row(client_as("procurement").get("/queue").text, req)


# --- Detail: reply and changes above the history ----------------------------------------------------------

def test_the_detail_shows_the_reply_and_changes_above_the_history(client_as, app_db):
    req = _submit(app_db)
    _needs_info(app_db, req)
    _resubmit(app_db, req, size="20 L")
    page = client_as("procurement").get(f"/queue/{req.id}").text
    summary = _summary(page)
    assert "ส่งกลับจากรอข้อมูล" in summary
    assert f"ข้อความตอบ:</strong> {REPLY}" in summary
    assert "<li>ขนาด: - → 20 L</li>" in summary
    assert "duplicate" not in summary.lower()
    assert page.index('id="resubmit-summary"') < page.index("<h3>ประวัติ</h3>")
    assert "แก้ไขข้อมูลคำขอ" in page  # the history row label, not the raw action


def test_no_summary_on_a_request_never_in_needs_info(client_as, app_db):
    req = _submit(app_db)
    assert 'id="resubmit-summary"' not in client_as("procurement").get(f"/queue/{req.id}").text


def test_no_summary_while_waiting_for_the_first_answer(client_as, app_db):
    req = _submit(app_db)
    _needs_info(app_db, req)
    assert 'id="resubmit-summary"' not in client_as("procurement").get(f"/queue/{req.id}").text


def test_a_resubmit_without_edits_says_so(client_as, app_db):
    req = _submit(app_db)
    _needs_info(app_db, req)
    _resubmit(app_db, req)
    summary = _summary(client_as("procurement").get(f"/queue/{req.id}").text)
    assert REPLY in summary and "ไม่ได้แก้ข้อมูล" in summary and "<li>" not in summary


def test_the_requeue_button_is_not_shown_as_the_requesters_reply(client_as, app_db):
    req = _submit(app_db)
    _needs_info(app_db, req)
    requeue_request(app_db, req.id, _proc(app_db), "ผู้ขอโทรมาแจ้งแล้ว")
    summary = _summary(client_as("procurement").get(f"/queue/{req.id}").text)
    assert "รับเข้าคิวใหม่โดยจัดซื้อ" in summary
    assert "หมายเหตุ:</strong> ผู้ขอโทรมาแจ้งแล้ว" in summary
    assert "ข้อความตอบ" not in summary and "ส่งกลับจากรอข้อมูล" not in summary


def test_the_latest_of_two_resubmits_is_shown(client_as, app_db):
    req = _submit(app_db)
    _needs_info(app_db, req)
    _resubmit(app_db, req, size="20 L")
    _needs_info(app_db, req)
    _resubmit(app_db, req, brand="NSK")
    summary = _summary(client_as("procurement").get(f"/queue/{req.id}").text)
    assert "แบรนด์: SKF → NSK" in summary and "ขนาด:" not in summary


# --- Replaced-name warning -----------------------------------------------------------------------------

WARNING = "ชื่อที่จัดซื้อแก้ไว้ถูกแทนที่"


def test_a_name_typed_before_needs_info_and_replaced_warns(client_as, app_db):
    req = _submit(app_db)
    edit_name(app_db, req.id, new_name=TYPED, account=_proc(app_db))  # while reviewing
    _needs_info(app_db, req)
    _resubmit(app_db, req, size="20 L")
    summary = _summary(client_as("procurement").get(f"/queue/{req.id}").text)
    assert f"{WARNING}: {TYPED} → BEARING - Ball Bearing SKF - 20 L" in summary


def test_a_name_typed_during_needs_info_and_replaced_warns(client_as, app_db):
    req = _submit(app_db)
    _needs_info(app_db, req)
    edit_name(app_db, req.id, new_name=TYPED, account=_proc(app_db))
    _resubmit(app_db, req, size="20 L")
    assert WARNING in _summary(client_as("procurement").get(f"/queue/{req.id}").text)


def test_no_warning_when_procurement_never_edited_the_name(client_as, app_db):
    req = _submit(app_db)
    _needs_info(app_db, req)
    _resubmit(app_db, req, size="20 L")
    assert WARNING not in client_as("procurement").get(f"/queue/{req.id}").text


def test_no_warning_when_the_resubmit_kept_the_name(client_as, app_db):
    req = _submit(app_db)
    edit_name(app_db, req.id, new_name=TYPED, account=_proc(app_db))
    _needs_info(app_db, req)
    _resubmit(app_db, req)  # nothing edited: the typed name stays
    page = client_as("procurement").get(f"/queue/{req.id}").text
    assert app_db.get(ItemRequest, req.id).item_name == TYPED
    assert WARNING not in page


def test_no_warning_for_a_name_typed_in_an_earlier_cycle(client_as, app_db):
    req = _submit(app_db)
    edit_name(app_db, req.id, new_name=TYPED, account=_proc(app_db))
    _needs_info(app_db, req)
    _resubmit(app_db, req, size="20 L")  # replaced here: that cycle warned
    _needs_info(app_db, req)
    _resubmit(app_db, req, brand="NSK")  # Procurement typed nothing this cycle
    assert WARNING not in client_as("procurement").get(f"/queue/{req.id}").text


def test_no_warning_once_procurement_typed_a_name_again(client_as, app_db):
    req = _submit(app_db)
    edit_name(app_db, req.id, new_name=TYPED, account=_proc(app_db))
    _needs_info(app_db, req)
    _resubmit(app_db, req, size="20 L")
    edit_name(app_db, req.id, new_name=TYPED + " 20 L", account=_proc(app_db))
    assert WARNING not in client_as("procurement").get(f"/queue/{req.id}").text


def test_a_typed_name_kept_through_a_requeue_then_replaced_warns(client_as, app_db):
    # Review 2026-10-19: a time window from the previous `submitted` missed this.
    req = _submit(app_db)
    edit_name(app_db, req.id, new_name=TYPED, account=_proc(app_db))
    _needs_info(app_db, req)
    requeue_request(app_db, req.id, _proc(app_db), "ผู้ขอโทรมาแจ้งแล้ว")
    _needs_info(app_db, req)
    _resubmit(app_db, req, size="20 L")
    summary = _summary(client_as("procurement").get(f"/queue/{req.id}").text)
    assert f"{WARNING}: {TYPED} → BEARING - Ball Bearing SKF - 20 L" in summary


def test_a_typed_name_kept_through_an_edit_free_resubmit_then_replaced_warns(client_as,
                                                                              app_db):
    req = _submit(app_db)
    edit_name(app_db, req.id, new_name=TYPED, account=_proc(app_db))
    _needs_info(app_db, req)
    _resubmit(app_db, req)  # keeps TYPED
    _needs_info(app_db, req)
    _resubmit(app_db, req, size="20 L")
    assert WARNING in _summary(client_as("procurement").get(f"/queue/{req.id}").text)


# --- Review 2026-10-19: one clock on the page ------------------------------------------------------

def test_the_history_shows_thai_time_like_the_card(client_as, app_db):
    from app.templating import thai_time

    req = _submit(app_db)
    _needs_info(app_db, req)
    _resubmit(app_db, req)
    app_db.expire_all()
    at = app_db.get(ItemRequest, req.id).events[-1].at
    page = client_as("procurement").get(f"/queue/{req.id}").text
    shown = thai_time(at, "%d/%m/%Y %H:%M")
    history = page[page.index("<h3>ประวัติ</h3>"):]
    assert shown in _summary(page) and shown in history
    assert at.strftime("%d/%m/%Y %H:%M") not in history  # UTC is 7 h off
