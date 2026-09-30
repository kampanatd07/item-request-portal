"""STORY-001 ticket 06: per-email lockout after 10 consecutive failed logins (AC9)."""

import logging
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models import Account
from app.services import auth
from app.services.auth import LOCKOUT, LOGIN_FAILED, AuthError
from tests.conftest import TEST_PASSWORD, account_for, login

EMAIL = "victim@test.local"
WRONG = "wrong-password-000"


@pytest.fixture()
def victim(clock, app_db) -> Account:
    return auth.create_account(app_db, EMAIL, "Victim", "procurement", TEST_PASSWORD,
                               must_change_password=False)


def _fail(anon_client, times: int, email: str = EMAIL) -> None:
    for _ in range(times):
        r = login(anon_client, email, WRONG)
        assert r.status_code == 401 and LOGIN_FAILED in r.text


def _error_box(html: str) -> str:
    return html.split('role="alert">', 1)[1].split("<", 1)[0]


# --- The lock (AC9) ---------------------------------------------------------------------------

def test_tenth_consecutive_failure_locks_for_15_minutes(victim, clock, anon_client, app_db):
    _fail(anon_client, 9)
    app_db.refresh(victim)
    assert victim.failed_login_count == 9 and victim.locked_until is None  # stored in the DB
    _fail(anon_client, 1)
    app_db.refresh(victim)
    assert victim.locked_until == clock.now + LOCKOUT


def test_correct_password_during_lock_looks_exactly_like_a_wrong_one(victim, anon_client):
    wrong = login(anon_client, EMAIL, WRONG)
    _fail(anon_client, 9)
    locked = login(anon_client, EMAIL, TEST_PASSWORD)
    assert locked.status_code == wrong.status_code == 401
    assert _error_box(locked.text) == _error_box(wrong.text) == LOGIN_FAILED
    assert "session" not in locked.cookies


def test_lock_lifts_after_15_minutes(victim, clock, anon_client):
    _fail(anon_client, 10)
    clock.advance(minutes=14, seconds=59)
    assert login(anon_client, EMAIL).status_code == 401
    clock.advance(seconds=1)
    assert login(anon_client, EMAIL).status_code == 303


def test_failures_during_the_lock_do_not_extend_it(victim, clock, anon_client):
    _fail(anon_client, 10)
    clock.advance(minutes=10)
    _fail(anon_client, 20)
    clock.advance(minutes=5)
    assert login(anon_client, EMAIL).status_code == 303


def test_count_starts_again_after_a_lock_runs_out(victim, clock, anon_client, app_db):
    _fail(anon_client, 10)
    clock.advance(minutes=15)
    _fail(anon_client, 1)  # one typo right after the lock must not re-lock
    app_db.refresh(victim)
    assert victim.locked_until is None and victim.failed_login_count == 1
    assert login(anon_client, EMAIL).status_code == 303


def test_successful_login_before_the_tenth_resets_the_count(victim, anon_client, app_db):
    _fail(anon_client, 9)
    assert login(anon_client, EMAIL).status_code == 303
    app_db.refresh(victim)
    assert victim.failed_login_count == 0
    anon_client.post("/logout")
    _fail(anon_client, 9)
    assert login(anon_client, EMAIL).status_code == 303  # still not locked


def test_unknown_email_failures_do_not_error_and_look_identical(victim, anon_client):
    known = login(anon_client, EMAIL, WRONG)
    for _ in range(12):
        unknown = login(anon_client, "nobody@test.local", WRONG)
        assert unknown.status_code == known.status_code
        assert _error_box(unknown.text) == _error_box(known.text)


def test_deactivated_account_still_counts_and_looks_identical(victim, anon_client, app_db):
    victim.active = False
    app_db.commit()
    _fail(anon_client, 10)
    app_db.refresh(victim)
    assert victim.locked_until is not None


def test_lockout_is_logged_with_target_and_no_password(victim, anon_client, caplog):
    caplog.set_level(logging.INFO, logger="app.accounts")
    _fail(anon_client, 10)
    lines = [r.getMessage() for r in caplog.records if r.name == "app.accounts"]
    locked = [m for m in lines if "action=locked" in m]
    assert len(locked) == 1
    assert "by=system" in locked[0] and f"target={EMAIL}" in locked[0]
    assert WRONG not in caplog.text and TEST_PASSWORD not in caplog.text


def test_login_locks_the_account_row(victim, app_db):
    # SQLite drops FOR UPDATE; the parallel-guess race runs on Postgres (STORY-006).
    from sqlalchemy import event
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.orm import Session

    seen: list[str] = []

    def _capture(state):
        if state.is_select:
            sql = str(state.statement.compile(dialect=postgresql.dialect()))
            if "FROM accounts" in sql and "FOR UPDATE" in sql:
                seen.append(sql)

    event.listen(Session, "do_orm_execute", _capture)
    try:
        with pytest.raises(AuthError):
            auth.authenticate(app_db, EMAIL, WRONG)
    finally:
        event.remove(Session, "do_orm_execute", _capture)
    assert seen


# --- Change-password page counts toward the same lock -------------------------------------

def _change(c, current: str):
    return c.post("/account/password", data={
        "current_password": current, "new_password": "a-new-password-99",
        "confirm_password": "a-new-password-99"})


def test_wrong_current_password_counts_toward_the_same_lock(clock, client_as, app_db):
    c = client_as("procurement")
    email = "procurement0@test.local"
    for _ in range(5):
        assert "รหัสผ่านปัจจุบันไม่ถูกต้อง" in _change(c, WRONG).text
    _fail(c, 5, email)  # the login page adds to the same counter
    account = app_db.scalar(select(Account).where(Account.email == email))
    app_db.refresh(account)
    assert account.locked_until is not None


def test_lock_triggered_on_change_page_ends_that_session(clock, client_as, app_db):
    c = client_as("procurement")
    for _ in range(9):
        _change(c, WRONG)
    r = _change(c, WRONG)
    assert r.status_code == 422 and "ล็อก" in r.text
    assert c.get("/queue", follow_redirects=False).headers["location"].startswith("/login")


def test_locked_account_cannot_change_password_even_with_right_current(clock, app_db):
    account = account_for(app_db, "procurement")
    account.locked_until = clock.now + timedelta(minutes=5)
    app_db.commit()
    with pytest.raises(AuthError, match="ล็อก"):
        auth.change_own_password(app_db, account, current=TEST_PASSWORD,
                                 new="a-new-password-99", confirm="a-new-password-99",
                                 now=clock.now)
    assert auth.verify_password(account.password_hash, TEST_PASSWORD)


# --- Administrator -----------------------------------------------------------------------------

def test_reset_password_clears_the_lock(victim, clock, anon_client, app_db):
    _fail(anon_client, 10)
    admin = account_for(app_db, "administrator")
    temporary = auth.reset_password(app_db, admin, victim.id)
    assert victim.locked_until is None and victim.failed_login_count == 0
    assert login(anon_client, EMAIL, temporary).status_code == 303


def test_account_table_shows_a_running_lock(clock, client, victim, anon_client):
    _fail(anon_client, 10)
    assert "ล็อกถึง" in client.get("/admin/accounts").text
    clock.advance(minutes=15)
    assert "ล็อกถึง" not in client.get("/admin/accounts").text


def test_right_current_password_resets_count_even_if_new_one_is_refused(clock, client_as, app_db):
    c = client_as("procurement")
    email = "procurement0@test.local"
    _fail(c, 9, email)
    r = c.post("/account/password", data={
        "current_password": TEST_PASSWORD, "new_password": "a-new-password-99",
        "confirm_password": "typo-in-confirmation"})
    assert r.status_code == 422 and "ไม่ตรงกัน" in r.text
    account = app_db.scalar(select(Account).where(Account.email == email))
    app_db.refresh(account)
    assert account.failed_login_count == 0
    assert "ไม่ถูกต้อง" in _change(c, WRONG).text  # one typo later: not locked
    assert c.get("/queue", follow_redirects=False).status_code == 200


def test_count_reset_survives_the_rollback_of_a_refused_change(clock, app_db):
    # In production get_db closes the session after the error, which rolls back
    # anything uncommitted; the HTTP tests share one session and cannot see that.
    account = account_for(app_db, "procurement")
    account.failed_login_count = 9
    app_db.commit()
    with pytest.raises(AuthError, match="ไม่ตรงกัน"):
        auth.change_own_password(app_db, account, current=TEST_PASSWORD,
                                 new="a-new-password-99", confirm="typo", now=clock.now)
    app_db.rollback()
    app_db.refresh(account)
    assert account.failed_login_count == 0



def test_lock_time_is_shown_in_thai_time(clock, client, victim, anon_client, app_db):
    # The DB keeps UTC; the table shows UTC+7.
    clock.advance(minutes=50)  # 08:50 UTC, still inside the admin's 8-hour session
    _fail(anon_client, 10)
    app_db.refresh(victim)
    assert victim.locked_until.strftime("%H:%M") == "09:05"  # stored as UTC
    page = client.get("/admin/accounts").text
    assert "ล็อกถึง 16:05 น." in page  # 09:05 UTC = 16:05 in Thailand
    assert "UTC" not in page


def test_thai_time_rolls_over_midnight():
    from datetime import datetime

    from app.templating import thai_time

    assert thai_time(datetime(2026, 9, 29, 21, 5)) == "04:05"
    assert thai_time(datetime(2026, 9, 29, 21, 5), "%d/%m %H:%M") == "30/09 04:05"
