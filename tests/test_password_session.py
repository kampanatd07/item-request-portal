"""STORY-001 ticket 05: forced/self password change and 8-hour session expiry."""

import logging
import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.models import Account
from app.services import auth
from tests.conftest import TEST_PASSWORD, login

NEW_PASSWORD = "brand-new-password-42"
EIGHT_HOURS = 8 * 3600


def _max_age(response) -> int:
    return int(re.search(r"Max-Age=(\d+)", response.headers["set-cookie"]).group(1))


def _change(c: TestClient, current: str = TEST_PASSWORD, new: str = NEW_PASSWORD,
            confirm: str | None = None):
    return c.post("/account/password", data={
        "current_password": current, "new_password": new,
        "confirm_password": new if confirm is None else confirm,
    }, follow_redirects=False)


@pytest.fixture()
def fresh(app_db, anon_client):
    """An Account with a temporary password (must change), logged in via the real form."""
    account = auth.create_account(app_db, "fresh@test.local", "Fresh", "procurement",
                                  TEST_PASSWORD)  # must_change_password defaults to True
    r = login(anon_client, account.email)
    return account, anon_client, r


# --- Forced change (AC11) --------------------------------------------------------------

def test_first_login_of_must_change_account_lands_on_change_password(fresh):
    _account, _c, r = fresh
    assert r.status_code == 303 and r.headers["location"] == "/account/password"


@pytest.mark.parametrize("path", ["/", "/queue", "/exports", "/fragments/systems?factory_id=1"])
def test_other_pages_redirect_to_change_password_until_done(fresh, path):
    _account, c, _r = fresh
    r = c.get(path, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/account/password"


def test_htmx_request_is_sent_to_change_password(fresh):
    _account, c, _r = fresh
    r = c.get("/fragments/systems?factory_id=1", headers={"HX-Request": "true"},
              follow_redirects=False)
    assert r.headers["HX-Redirect"] == "/account/password"


def test_forced_page_hides_navigation_but_allows_logout(fresh):
    _account, c, _r = fresh
    page = c.get("/account/password").text
    assert "รหัสชั่วคราว" in page
    assert 'href="/queue"' not in page and 'href="/"' not in page
    assert 'action="/logout"' in page
    assert c.post("/logout", follow_redirects=False).headers["location"] == "/login"


def test_after_forced_change_every_page_opens(fresh, app_db):
    account, c, _r = fresh
    r = _change(c)
    assert r.status_code == 303 and r.headers["location"] == "/account/password?done=1"
    assert "เปลี่ยนรหัสผ่านเรียบร้อย" in c.get(r.headers["location"]).text
    app_db.refresh(account)
    assert not account.must_change_password
    assert c.get("/queue", follow_redirects=False).status_code == 200


# --- Password rules ----------------------------------------------------------------------

def test_password_shorter_than_12_is_refused(fresh, app_db):
    account, c, _r = fresh
    r = _change(c, new="short-pw-1")
    assert r.status_code == 422 and "12" in r.text
    app_db.refresh(account)
    assert account.must_change_password


def test_wrong_current_password_is_refused(fresh, app_db):
    account, c, _r = fresh
    r = _change(c, current="not-the-password")
    assert r.status_code == 422 and "รหัสผ่านปัจจุบันไม่ถูกต้อง" in r.text
    app_db.refresh(account)
    assert auth.verify_password(account.password_hash, TEST_PASSWORD)


def test_mismatched_confirmation_is_refused(fresh):
    _account, c, _r = fresh
    r = _change(c, confirm=NEW_PASSWORD + "x")
    assert r.status_code == 422 and "ไม่ตรงกัน" in r.text


def test_new_password_must_differ_from_current(fresh):
    _account, c, _r = fresh
    r = _change(c, new=TEST_PASSWORD)
    assert r.status_code == 422 and "ไม่ซ้ำ" in r.text


def test_any_account_can_change_its_own_password(client_as, app_db):
    c = client_as("requester", plant="APM")
    assert c.get("/account/password").status_code == 200
    assert _change(c).status_code == 303
    account = app_db.scalar(select(Account).where(Account.email == "requester0@test.local"))
    assert auth.authenticate(app_db, account.email, NEW_PASSWORD).id == account.id


# --- Sessions after a change (AC10, password part) ------------------------------------------

def test_password_change_ends_other_sessions_but_not_this_one(client_as, app_db):
    this = client_as("procurement")
    email = "procurement0@test.local"
    other = TestClient(app)
    with other:
        assert login(other, email).status_code == 303
        assert other.get("/queue", follow_redirects=False).status_code == 200

        assert _change(this).status_code == 303
        assert other.get("/queue", follow_redirects=False).status_code == 303
        assert this.get("/queue", follow_redirects=False).status_code == 200


# --- Expiry (AC10, expiry part) ------------------------------------------------------------

def test_session_just_under_8_hours_works_and_8_hours_is_rejected(clock, client):
    clock.advance(hours=7, minutes=59, seconds=59)
    assert client.get("/", follow_redirects=False).status_code == 200
    clock.advance(seconds=1)
    r = client.get("/queue", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/login?relogin=1&next=/queue"


def test_login_cookie_lives_8_hours(clock, anon_client, app_db):
    auth.create_account(app_db, "a@test.local", "A", "procurement", TEST_PASSWORD,
                        must_change_password=False)
    assert _max_age(login(anon_client, "a@test.local")) == EIGHT_HOURS


def test_password_change_keeps_original_expiry(clock, client_as):
    c = client_as("procurement")
    clock.advance(hours=3)
    r = _change(c)
    # Re-issued cookie lives only for what is left of the original 8 hours.
    assert _max_age(r) == EIGHT_HOURS - 3 * 3600
    clock.advance(hours=4, minutes=59)
    assert c.get("/queue", follow_redirects=False).status_code == 200
    clock.advance(minutes=1)
    assert c.get("/queue", follow_redirects=False).status_code == 303


# --- Log --------------------------------------------------------------------------------------

def test_password_change_is_logged_without_the_password(fresh, caplog):
    caplog.set_level(logging.INFO, logger="app.accounts")
    _account, c, _r = fresh
    _change(c)
    lines = [r.getMessage() for r in caplog.records if r.name == "app.accounts"]
    assert any("action=change_password" in m and "target=fresh@test.local" in m for m in lines)
    assert NEW_PASSWORD not in caplog.text and TEST_PASSWORD not in caplog.text



# --- Login page notices (review fix: the browser drops an expired cookie itself) ------------

def test_login_page_always_states_the_8_hour_limit(anon_client):
    assert "ระบบจะออกจากระบบอัตโนมัติหลังเข้าใช้งาน 8 ชั่วโมง" in anon_client.get("/login").text


def test_never_logged_in_visitor_is_not_asked_to_log_in_again(anon_client):
    r = anon_client.get("/queue", follow_redirects=False)
    assert "relogin" not in r.headers["location"]
    assert "กรุณาเข้าสู่ระบบใหม่" not in anon_client.get(r.headers["location"]).text


@pytest.mark.parametrize("how", ["version", "deactivated", "tampered"])
def test_dead_cookie_asks_to_log_in_again_once(client, app_db, how):
    from app.services.sessions import COOKIE_NAME

    account = app_db.scalar(select(Account).where(Account.email == "administrator0@test.local"))
    if how == "version":
        account.session_version += 1
    elif how == "deactivated":
        account.active = False
    else:
        for cookie in client.cookies.jar:  # edit in place: same domain as issued
            if cookie.name == COOKIE_NAME:
                cookie.value = cookie.value[:-3] + "abc"
    app_db.commit()

    r = client.get("/queue", follow_redirects=False)
    assert r.headers["location"] == "/login?relogin=1&next=/queue"
    assert "กรุณาเข้าสู่ระบบใหม่" in client.get(r.headers["location"]).text
    # The dead cookie was dropped, so the notice does not repeat.
    assert "relogin" not in client.get("/queue", follow_redirects=False).headers["location"]


def test_refreshing_after_a_change_shows_success_not_an_error(client_as):
    c = client_as("procurement")
    r = _change(c)
    # A refresh re-requests the GET the browser was redirected to.
    for _ in range(2):
        page = c.get(r.headers["location"])
        assert page.status_code == 200
        assert "เปลี่ยนรหัสผ่านเรียบร้อย" in page.text
        assert "ไม่ถูกต้อง" not in page.text
