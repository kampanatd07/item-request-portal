"""STORY-010 ticket 04: override in two steps — check (read-only), then confirm."""

import re

import pytest
from sqlalchemy import func, select

from app.models import ItemRequest, RequestEvent, RetiredCode, RunningRegister
from app.services import auth
from app.services.requests import change_status, submit_request
from app.services.sessions import COOKIE_NAME
from tests.conftest import TEST_PASSWORD, account_for, central_ids, load_master, login

REASON = "item มีใน master ของกลุ่มแล้ว"


def _approved(db):
    factory, system, group, sub = central_ids(db)
    req = submit_request(db, account_for(db), factory_id=factory.id, code_system_id=system.id,
                         group_id=group.id, subgroup_id=sub.id, item_name="Ball Bearing")
    return change_status(db, req.id, new_status="approved",
                         account=account_for(db, "administrator"))


def _last(db) -> int:
    db.expire_all()
    return db.scalar(select(RunningRegister.last_running).where(
        RunningRegister.group_code == "900", RunningRegister.sub_code == "01"))


def _code(n: int) -> str:
    return f"9000100{n:04d}"


def _state(db, req):
    db.expire_all()
    return (db.get(ItemRequest, req.id).generated_code, _last(db),
            db.scalar(select(func.count(RetiredCode.id))),
            db.scalar(select(func.count(RequestEvent.id))))


def _check(c, req, code):
    return c.post(f"/queue/{req.id}/code/check", data={"new_code": code})


def _token(html: str) -> str:
    return re.search(r'name="token" value="([^"]+)"', html).group(1)


def _confirm(c, req, token, reason=REASON, confirm=False):
    data = {"token": token, "reason": reason}
    if confirm:
        data["confirm_skip"] = "1"
    return c.post(f"/queue/{req.id}/code", data=data)


# --- Step 1: check is read-only and shows everything -------------------------------------------

def test_check_shows_the_preview_and_changes_nothing(client, app_db):
    req = _approved(app_db)
    last = _last(app_db)
    x, in_master = _code(last + 4), _code(last + 2)
    load_master(app_db, [x, in_master])
    before = _state(app_db, req)

    r = _check(client, req, x)
    assert r.status_code == 200
    html = r.text
    assert f"<code>{x}</code> — TEST - Item in group master {x}" in html      # item name
    assert f"<code>{req.generated_code}</code>" in html and "ถูกทิ้งถาวร" in html  # old code
    assert f"ขยับจาก {last} เป็น {last + 4}" in html
    assert "<strong>2 เลข</strong>" in html and _code(last + 1) in html      # to throw away
    assert "มีใน Master (ไม่ทิ้ง)</th><td>1 เลข" in html
    assert 'name="token"' in html and "ยืนยันใช้รหัสนี้" in html
    assert _state(app_db, req) == before


def test_check_with_an_error_shows_it_and_offers_no_confirm(client, app_db):
    req = _approved(app_db)
    load_master(app_db, [_code(_last(app_db) + 1)])
    r = _check(client, req, "90001000")
    assert r.status_code == 200 and "11 หลัก" in r.text
    assert 'name="token"' not in r.text and "ยืนยันใช้รหัสนี้" not in r.text


def test_long_list_to_throw_away_is_summarised(client, app_db):
    req = _approved(app_db)
    last = _last(app_db)
    x = _code(last + 30)
    load_master(app_db, [x])
    html = _check(client, req, x).text
    assert "<strong>29 เลข</strong>" in html
    assert ", …, " + _code(last + 29) in html and _code(last + 10) not in html
    assert "ยืนยันว่าเลข 29 ตัวจะถูกทิ้งถาวร" in html  # > 10: checkbox shown


# --- Step 2: confirm re-checks on the server -------------------------------------------------------

def test_confirm_saves_exactly_what_was_previewed(client, app_db):
    req = _approved(app_db)
    last = _last(app_db)
    x = _code(last + 3)
    load_master(app_db, [x])
    r = _confirm(client, req, _token(_check(client, req, x).text))
    assert r.status_code == 200 and x in r.text
    app_db.expire_all()
    assert app_db.get(ItemRequest, req.id).generated_code == x and _last(app_db) == last + 3
    actions = {e.action for e in app_db.scalars(select(RequestEvent).where(
        RequestEvent.request_id == req.id))}
    assert {"code_overridden", "register_advanced"} <= actions


def test_register_moving_between_check_and_confirm_is_refused(client, app_db):
    req = _approved(app_db)
    last = _last(app_db)
    x = _code(last + 5)
    load_master(app_db, [x])
    token = _token(_check(client, req, x).text)
    _approved(app_db)  # someone approves in 900-01 meanwhile: register +1
    before = _state(app_db, req)

    r = _confirm(client, req, token)
    assert r.status_code == 422
    assert "ข้อมูลเปลี่ยนไปหลังตรวจรหัส" in r.text and "เลขล่าสุดของ register" in r.text
    assert "ตรวจสอบรหัสใหม่" in r.text
    assert _state(app_db, req) == before  # nothing saved on the new numbers


def test_code_changed_by_someone_else_meanwhile_is_refused(client, app_db):
    req = _approved(app_db)
    last = _last(app_db)
    x, other = _code(last + 1), _code(last + 2)
    load_master(app_db, [x, other])
    token = _token(_check(client, req, x).text)
    _confirm(client, req, _token(_check(client, req, other).text))  # first save wins
    r = _confirm(client, req, token)
    assert r.status_code == 422 and "ตรวจสอบรหัสใหม่" in r.text


def test_confirm_without_a_token_is_refused(client, app_db):
    req = _approved(app_db)
    before = _state(app_db, req)
    r = client.post(f"/queue/{req.id}/code", data={"reason": REASON, "new_code": _code(1)})
    assert r.status_code == 422 and "ตรวจสอบรหัสใหม่" in r.text
    assert _state(app_db, req) == before


def test_tampered_token_is_refused(client, app_db):
    req = _approved(app_db)
    x = _code(_last(app_db) + 1)
    load_master(app_db, [x])
    token = _token(_check(client, req, x).text)
    r = _confirm(client, req, token[:-4] + "AAAA")
    assert r.status_code == 422 and "ไม่พบผลการตรวจรหัสที่ถูกต้อง" in r.text


def test_session_cookie_cannot_stand_in_for_a_token(client, app_db):
    req = _approved(app_db)
    r = _confirm(client, req, client.cookies.get(COOKIE_NAME))
    assert r.status_code == 422 and "ไม่พบผลการตรวจรหัสที่ถูกต้อง" in r.text


def test_token_for_another_request_is_refused(client, app_db):
    first, second = _approved(app_db), _approved(app_db)
    x = _code(_last(app_db) + 1)
    load_master(app_db, [x])
    token = _token(_check(client, first, x).text)
    r = _confirm(client, second, token)
    assert r.status_code == 422 and "คำขออื่น" in r.text


def test_another_administrator_cannot_use_the_token(client, app_db, anon_client):
    req = _approved(app_db)
    x = _code(_last(app_db) + 1)
    load_master(app_db, [x])
    token = _token(_check(client, req, x).text)
    auth.create_account(app_db, "second.admin@test.local", "Second", "administrator",
                        TEST_PASSWORD, must_change_password=False)
    login(anon_client, "second.admin@test.local")
    before = _state(app_db, req)
    r = _confirm(anon_client, req, token)
    assert r.status_code == 422 and "ผู้ใช้อื่น" in r.text
    assert _state(app_db, req) == before


def test_token_expires_after_10_minutes(clock, client, app_db):
    req = _approved(app_db)
    x = _code(_last(app_db) + 1)
    load_master(app_db, [x])
    token = _token(_check(client, req, x).text)
    clock.advance(minutes=10, seconds=1)
    r = _confirm(client, req, token)
    assert r.status_code == 422 and "หมดอายุ" in r.text


def test_token_just_under_10_minutes_still_works(clock, client, app_db):
    req = _approved(app_db)
    x = _code(_last(app_db) + 1)
    load_master(app_db, [x])
    token = _token(_check(client, req, x).text)
    clock.advance(minutes=10)
    assert _confirm(client, req, token).status_code == 200


def test_big_jump_needs_the_checkbox_on_the_server_too(client, app_db):
    req = _approved(app_db)
    last = _last(app_db)
    x = _code(last + 13)  # 12 to throw away
    load_master(app_db, [x])
    token = _token(_check(client, req, x).text)
    r = _confirm(client, req, token)  # browser 'required' bypassed
    assert r.status_code == 422 and "ยืนยัน" in r.text
    assert _last(app_db) == last
    assert _confirm(client, req, token, confirm=True).status_code == 200


def test_reason_is_required_and_the_form_survives(client, app_db):
    req = _approved(app_db)
    x = _code(_last(app_db) + 1)
    load_master(app_db, [x])
    r = _confirm(client, req, _token(_check(client, req, x).text), reason="  ")
    assert r.status_code == 422 and "เหตุผล" in r.text  # shown in the form's error slot


def test_history_shows_the_reason(client, app_db):
    req = _approved(app_db)
    x = _code(_last(app_db) + 1)
    load_master(app_db, [x])
    _confirm(client, req, _token(_check(client, req, x).text))
    page = client.get(f"/queue/{req.id}").text
    assert f"เหตุผล: {REASON}" in page


# --- Access ------------------------------------------------------------------------------------

@pytest.mark.parametrize("path", ["/code/check", "/code"])
def test_procurement_gets_403_on_both_steps(client_as, app_db, path):
    req = _approved(app_db)
    r = client_as("procurement").post(f"/queue/{req.id}{path}", data={"new_code": "x", "token": "x"})
    assert r.status_code == 403


def test_procurement_never_sees_the_override_form(client_as, app_db):
    req = _approved(app_db)
    assert "/code/check" not in client_as("procurement").get(f"/queue/{req.id}").text
    assert "/code/check" in client_as("administrator").get(f"/queue/{req.id}").text


def test_a_value_signed_with_the_session_salt_is_not_a_token(client, app_db):
    # Same secret, same payload shape as a real preview token, but the session
    # cookie's salt: the separate salt alone must refuse it.
    from itsdangerous import URLSafeSerializer

    from app.config import settings
    from app.services.override_preview import _epoch, plan_of
    from app.services.requests import check_override

    req = _approved(app_db)
    x = _code(_last(app_db) + 1)
    load_master(app_db, [x])
    admin = app_db.scalar(select(auth.Account).where(auth.Account.email == "administrator0@test.local"))
    from app.services.clock import utc_now
    forged = URLSafeSerializer(settings.secret_key, salt="session-cookie").dumps({
        "rid": req.id, "aid": admin.id, "at": _epoch(utc_now()),
        "plan": plan_of(check_override(app_db, req, x))})
    r = _confirm(client, req, forged)
    assert r.status_code == 422 and "ไม่พบผลการตรวจรหัสที่ถูกต้อง" in r.text


def test_only_the_requests_code_changing_meanwhile_is_refused(client, app_db):
    # The register and the numbers to throw away stay the same; only the code on
    # the request changed (another Administrator overrode it to an older code).
    req = _approved(app_db)
    last = _last(app_db)
    x, older = _code(last + 1), _code(last - 40)
    load_master(app_db, [x, older])
    token = _token(_check(client, req, x).text)
    _confirm(client, req, _token(_check(client, req, older).text))  # register unchanged
    assert _last(app_db) == last
    r = _confirm(client, req, token)
    assert r.status_code == 422 and "รหัสปัจจุบันของคำขอ" in r.text



def test_master_renaming_the_item_between_check_and_confirm_is_refused(client, app_db):
    from app.models import ItemSnapshot

    req = _approved(app_db)
    x = _code(_last(app_db) + 1)
    load_master(app_db, [x])
    token = _token(_check(client, req, x).text)
    row = app_db.scalar(select(ItemSnapshot).where(ItemSnapshot.item_number == x))
    row.name = "SOMETHING - Another item entirely"  # master re-uploaded meanwhile
    app_db.commit()
    before = _state(app_db, req)
    r = _confirm(client, req, token)
    assert r.status_code == 422 and "ชื่อ item ใน Master" in r.text
    assert _state(app_db, req) == before


def test_checking_the_current_code_is_refused_not_offered(client, app_db):
    req = _approved(app_db)
    load_master(app_db, [req.generated_code])
    r = _check(client, req, req.generated_code)
    assert "เป็นรหัสปัจจุบันของคำขออยู่แล้ว" in r.text and 'name="token"' not in r.text


def test_pasted_code_with_spaces_is_accepted(client, app_db):
    req = _approved(app_db)
    x = _code(_last(app_db) + 1)
    load_master(app_db, [x])
    assert 'maxlength="11"' not in client.get(f"/queue/{req.id}").text
    r = _check(client, req, f"  {x} ")
    assert 'name="token"' in r.text
