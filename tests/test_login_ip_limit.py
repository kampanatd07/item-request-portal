"""STORY-006 ticket 07: login refuses a client IP after 50 failed logins in
15 minutes (AC 5), against password spraying across many emails."""

import logging
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.main import app
from app.models import Account, LoginIpFailure
from app.services import auth
from app.services.auth import (
    IP_BLOCKED,
    LOGIN_FAILED,
    MAX_FAILED_LOGINS_PER_IP,
    MAX_FAILED_LOGINS,
)
from app.services.sessions import COOKIE_NAME
from tests.conftest import TEST_PASSWORD

EMAIL = "someone@test.local"
WRONG = "wrong-password-000"
IP = "198.51.100.7"
OTHER_IP = "198.51.100.8"


@pytest.fixture()
def account(clock, app_db) -> Account:
    return auth.create_account(app_db, EMAIL, "Someone", "procurement", TEST_PASSWORD,
                               must_change_password=False)


@pytest.fixture()
def client_from(app_db):
    """client_from(ip, asgi=app) -> a TestClient whose requests come from `ip`."""
    clients: list[TestClient] = []

    def _make(ip: str, asgi=app) -> TestClient:
        c = TestClient(asgi, client=(ip, 50000))
        c.__enter__()
        clients.append(c)
        return c

    yield _make
    for c in clients:
        c.__exit__(None, None, None)


def _post(c: TestClient, email: str = EMAIL, password: str = WRONG, **headers: str):
    return c.post("/login", data={"email": email, "password": password},
                  headers=headers, follow_redirects=False)


def _fail(c: TestClient, times: int, **kw: str) -> None:
    # Spread over many emails, as a sprayer would: the per-email lock (10)
    # must not be what stops these.
    for i in range(times):
        r = _post(c, email=f"spray{i}@test.local", **kw)
        assert r.status_code == 401 and LOGIN_FAILED in r.text, (i, r.status_code)


def _row(db, ip: str = IP) -> LoginIpFailure | None:
    db.expire_all()
    return db.get(LoginIpFailure, ip)


# --- the limit ------------------------------------------------------------------------

def test_fiftieth_failure_blocks_and_the_next_attempt_gets_429_in_thai(
        account, client_from, app_db):
    c = client_from(IP)
    _fail(c, MAX_FAILED_LOGINS_PER_IP - 1)
    assert _row(app_db).blocked_until is None
    _fail(c, 1)  # the 50th still gets the normal answer, and starts the block
    assert _row(app_db).blocked_until is not None

    r = _post(c, password=TEST_PASSWORD)  # even the right password
    assert r.status_code == 429
    assert IP_BLOCKED in r.text and LOGIN_FAILED not in r.text
    assert COOKIE_NAME not in r.cookies


def test_a_blocked_ip_is_refused_without_hashing_and_without_counting(
        account, client_from, app_db, monkeypatch):
    c = client_from(IP)
    _fail(c, MAX_FAILED_LOGINS_PER_IP)
    calls: list[str] = []
    monkeypatch.setattr(auth, "verify_password", lambda *a: calls.append("hash") or False)
    assert _post(c).status_code == 429
    assert calls == []
    assert _row(app_db).failed_count == MAX_FAILED_LOGINS_PER_IP


def test_another_ip_is_not_affected(account, client_from):
    _fail(client_from(IP), MAX_FAILED_LOGINS_PER_IP)
    assert _post(client_from(OTHER_IP), password=TEST_PASSWORD).status_code == 303


def test_the_block_lifts_after_15_minutes(account, client_from, clock):
    c = client_from(IP)
    _fail(c, MAX_FAILED_LOGINS_PER_IP)
    clock.advance(minutes=14, seconds=59)
    assert _post(c, password=TEST_PASSWORD).status_code == 429
    clock.advance(seconds=1)
    assert _post(c, password=TEST_PASSWORD).status_code == 303


def test_a_window_older_than_15_minutes_starts_again(account, client_from, clock, app_db):
    c = client_from(IP)
    _fail(c, MAX_FAILED_LOGINS_PER_IP - 1)
    clock.advance(minutes=15)
    _fail(c, MAX_FAILED_LOGINS_PER_IP - 1)
    row = _row(app_db)
    assert row.blocked_until is None and row.failed_count == MAX_FAILED_LOGINS_PER_IP - 1


def test_a_success_in_between_does_not_reset_the_count(account, client_from):
    c = client_from(IP)
    _fail(c, 25)
    assert _post(c, password=TEST_PASSWORD).status_code == 303
    _fail(c, MAX_FAILED_LOGINS_PER_IP - 25)
    assert _post(c, password=TEST_PASSWORD).status_code == 429


def test_every_kind_of_failure_counts(account, client_from, app_db):
    c = client_from(IP)
    assert _post(c, email="nobody@test.local").status_code == 401           # unknown email
    assert _post(c).status_code == 401                                      # wrong password
    for _ in range(MAX_FAILED_LOGINS - 1):                                  # lock the Account
        _post(c)
    assert _post(c, password=TEST_PASSWORD).status_code == 401              # locked Account
    other = auth.create_account(app_db, "gone@test.local", "Gone", "procurement",
                                TEST_PASSWORD, must_change_password=False)
    other.active = False
    app_db.commit()
    assert _post(c, email="gone@test.local", password=TEST_PASSWORD).status_code == 401
    assert _row(app_db).failed_count == 1 + MAX_FAILED_LOGINS + 1 + 1


def test_the_per_email_lockout_still_applies(account, client_from, app_db):
    c = client_from(IP)
    for _ in range(MAX_FAILED_LOGINS):
        _post(c)
    app_db.expire_all()
    assert app_db.scalar(select(Account.locked_until).where(Account.email == EMAIL))


def test_the_login_form_is_a_plain_post_so_the_429_page_shows_as_is(anon_client):
    # If this fails, the form moved to HTMX: add 429 to htmx:beforeSwap
    # (base.html) in the same change, or the Thai message never shows.
    html = anon_client.get("/login").text
    form = html.split("<form", 1)[1].split("</form>", 1)[0]
    assert "hx-" not in form and "hx-boost" not in html


def test_the_block_is_logged_once_with_the_ip_and_never_a_password(
        account, client_from, caplog):
    c = client_from(IP)
    with caplog.at_level(logging.INFO, logger="app.accounts"):
        _fail(c, MAX_FAILED_LOGINS_PER_IP)
        _post(c)
    blocked = [r.getMessage() for r in caplog.records if "login_ip_blocked" in r.getMessage()]
    assert len(blocked) == 1 and f"ip={IP}" in blocked[0]
    assert WRONG not in caplog.text and TEST_PASSWORD not in caplog.text


@pytest.mark.parametrize("raw, key", [
    ("198.51.100.7", "198.51.100.7"), (" 198.51.100.7 ", "198.51.100.7"),
    ("2001:DB8::0001", "2001:db8::1"), ("testclient", "unknown"), (None, "unknown"),
    ("1.2.3.4, 5.6.7.8", "unknown"),
])
def test_the_stored_ip_is_normalised_and_odd_values_share_one_bucket(raw, key):
    assert auth._ip_key(raw) == key


@pytest.mark.parametrize("raw", ["testclient", None, "1.2.3.4, 5.6.7.8", "x\ny"])
def test_every_unknown_client_ip_is_a_warning_without_the_password(account, client_from,
                                                                   raw, caplog):
    with caplog.at_level(logging.WARNING, logger="app.auth"):
        assert auth._ip_key(raw) == "unknown"
        r = _post(client_from("testclient"))  # through the login, too
    assert r.status_code == 401
    warnings = [rec for rec in caplog.records
                if rec.levelno == logging.WARNING and "login_client_ip_unknown" in rec.getMessage()]
    assert len(warnings) == 2  # one per lookup: the call above and the login
    assert all("\n" not in rec.getMessage() for rec in warnings)  # no forged log lines
    assert WRONG not in caplog.text


def test_a_real_ip_logs_no_warning(account, client_from, caplog):
    with caplog.at_level(logging.WARNING, logger="app.auth"):
        _post(client_from(IP))
    assert "login_client_ip_unknown" not in caplog.text


# --- through the real proxy layer (ticket 06 review, note 7) ---------------------------

def test_behind_a_trusted_proxy_each_client_is_counted_on_its_own_and_cannot_forge(
        account, client_from):
    # Configured as app/main.py does for FORWARDED_ALLOW_IPS=10.0.0.5.
    proxy = client_from("10.0.0.5", ProxyHeadersMiddleware(app, trusted_hosts=["10.0.0.5"]))
    _fail(proxy, MAX_FAILED_LOGINS_PER_IP, **{"X-Forwarded-For": IP})
    assert _post(proxy, **{"X-Forwarded-For": IP}).status_code == 429
    # A forged entry in front does not move the count off the real client.
    assert _post(proxy, **{"X-Forwarded-For": f"1.2.3.4, {IP}"}).status_code == 429
    # Another client behind the same proxy is someone else.
    assert _post(proxy, password=TEST_PASSWORD,
                 **{"X-Forwarded-For": OTHER_IP}).status_code == 303
    # Straight from the blocked IP, a header naming someone else is ignored.
    direct = client_from(IP, ProxyHeadersMiddleware(app, trusted_hosts=["10.0.0.5"]))
    assert _post(direct, **{"X-Forwarded-For": OTHER_IP}).status_code == 429


# --- tidying old rows -------------------------------------------------------------------

def _put_row(db, ip: str, window_started_at: datetime, blocked_until: datetime | None = None):
    db.add(LoginIpFailure(ip=ip, failed_count=3, window_started_at=window_started_at,
                          blocked_until=blocked_until))
    db.commit()


def test_rows_idle_over_a_day_are_removed_and_rows_in_use_are_kept(
        account, client_from, clock, app_db):
    now = clock()
    _put_row(app_db, "192.0.2.1", now - timedelta(days=2))                 # idle: removed
    _put_row(app_db, "192.0.2.2", now - timedelta(hours=1))                # recent: kept
    _put_row(app_db, "192.0.2.3", now - timedelta(days=2),
             blocked_until=now - timedelta(days=1, minutes=1))             # idle: removed
    _put_row(app_db, "192.0.2.4", now - timedelta(days=2),
             blocked_until=now - timedelta(hours=2))                       # block recent: kept
    _fail(client_from(IP), 1)
    app_db.expire_all()
    left = set(app_db.scalars(select(LoginIpFailure.ip)))
    assert left == {"192.0.2.2", "192.0.2.4", IP}


def test_a_failed_tidy_never_fails_the_login(account, client_from, clock, app_db,
                                             monkeypatch, caplog):
    _put_row(app_db, "192.0.2.1", clock() - timedelta(days=2))

    def broken(*a, **kw):
        raise RuntimeError("tidy broke")

    monkeypatch.setattr(auth, "delete", broken)
    with caplog.at_level(logging.WARNING, logger="app.auth"):
        r = _post(client_from(IP))
    assert r.status_code == 401 and LOGIN_FAILED in r.text
    assert _row(app_db).failed_count == 1  # the failure itself was still counted
    assert "login_ip_prune_failed" in caplog.text
