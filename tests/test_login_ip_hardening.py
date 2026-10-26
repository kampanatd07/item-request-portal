"""STORY-006 ticket 08: count first, refund later (nothing held while the
password is hashed); a right password on an Account locked meanwhile looks
exactly like a wrong one; IPv6 counted per /64; the unblock CLI."""

import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update

from app.main import app
from app.models import Account, LoginIpFailure
from app.services import auth
from app.services.auth import IP_BLOCKED, LOCKOUT, LOGIN_FAILED, MAX_FAILED_LOGINS_PER_IP
from app.unblock_ip import run as unblock
from tests.conftest import TEST_IP, TEST_PASSWORD

EMAIL = "someone@test.local"
WRONG = "wrong-password-000"
IP = "198.51.100.7"


@pytest.fixture()
def account(clock, app_db) -> Account:
    return auth.create_account(app_db, EMAIL, "Someone", "procurement", TEST_PASSWORD,
                               must_change_password=False)


@pytest.fixture()
def client_from(app_db):
    clients: list[TestClient] = []

    def _make(ip: str) -> TestClient:
        c = TestClient(app, client=(ip, 50000))
        c.__enter__()
        clients.append(c)
        return c

    yield _make
    for c in clients:
        c.__exit__(None, None, None)


def _post(c: TestClient, email: str = EMAIL, password: str = WRONG):
    return c.post("/login", data={"email": email, "password": password},
                  follow_redirects=False)


def _count(db, ip: str = IP) -> int:
    db.expire_all()
    row = db.get(LoginIpFailure, ip)
    return row.failed_count if row else 0


def _block(c: TestClient) -> None:
    for i in range(MAX_FAILED_LOGINS_PER_IP):
        assert _post(c, email=f"spray{i}@test.local").status_code == 401


# --- count first, refund later -----------------------------------------------------------

@pytest.mark.parametrize("email", [EMAIL, "nobody@test.local"])
def test_nothing_is_held_while_the_password_is_hashed(account, app_db, monkeypatch, email):
    real = auth.verify_password
    seen: list[bool] = []

    def probe(stored: str, password: str) -> bool:
        seen.append(app_db.in_transaction())
        return real(stored, password)

    monkeypatch.setattr(auth, "verify_password", probe)
    with pytest.raises(auth.AuthError):
        auth.authenticate(app_db, email, WRONG, client_ip=TEST_IP)
    assert seen == [False]  # the attempt was counted and committed before the hash


def test_a_success_gives_its_slot_back_and_failures_stay(account, client_from, app_db):
    c = client_from(IP)
    for _ in range(3):
        _post(c)
    assert _count(app_db) == 3
    assert _post(c, password=TEST_PASSWORD).status_code == 303
    assert _count(app_db) == 3


def test_the_count_never_goes_below_zero(account, client_from, app_db):
    assert _post(client_from(IP), password=TEST_PASSWORD).status_code == 303
    assert _count(app_db) == 0


def test_one_at_a_time_the_fiftieth_still_starts_the_block(account, client_from, app_db):
    c = client_from(IP)
    _block(c)
    assert _count(app_db) == MAX_FAILED_LOGINS_PER_IP
    r = _post(c, password=TEST_PASSWORD)
    assert r.status_code == 429 and IP_BLOCKED in r.text


def _comparable(r) -> tuple:
    headers = {k: v for k, v in r.headers.items() if k.lower() != "date"}
    return r.status_code, r.text, headers, dict(r.cookies)


def test_a_right_password_on_an_account_locked_during_the_hash_looks_like_a_wrong_one(
        account, client_from, app_db, clock, monkeypatch):
    real = auth.verify_password

    def lock_while_hashing(stored: str, password: str) -> bool:
        if password == TEST_PASSWORD:
            # Another request's 10th wrong guess lands while this one hashes.
            app_db.execute(update(Account).where(Account.email == EMAIL)
                           .values(locked_until=clock() + LOCKOUT, failed_login_count=10))
            app_db.commit()
        return real(stored, password)

    monkeypatch.setattr(auth, "verify_password", lock_while_hashing)
    c = client_from(IP)
    right = _post(c, password=TEST_PASSWORD)
    wrong = _post(c, password=WRONG)  # the Account is locked now

    assert right.status_code == 401 and LOGIN_FAILED in right.text
    assert "location" not in right.headers and not right.cookies
    assert _comparable(right) == _comparable(wrong)


def test_a_password_changed_during_the_hash_is_refused(account, client_from, app_db,
                                                       monkeypatch):
    real = auth.verify_password

    def change_while_hashing(stored: str, password: str) -> bool:
        app_db.execute(update(Account).where(Account.email == EMAIL)
                       .values(password_hash=auth.hash_password("a-new-password-123")))
        app_db.commit()
        return real(stored, password)

    monkeypatch.setattr(auth, "verify_password", change_while_hashing)
    assert _post(client_from(IP), password=TEST_PASSWORD).status_code == 401


# --- IPv6 per /64 -----------------------------------------------------------------------

def test_ipv6_addresses_in_one_slash_64_are_counted_together(account, client_from):
    for i in range(MAX_FAILED_LOGINS_PER_IP):
        # A sprayer rotating inside its own /64.
        _post(client_from(f"2001:db8:1:2::{i + 1:x}"), email=f"spray{i}@test.local")
    assert _post(client_from("2001:db8:1:2:abcd::1"), password=TEST_PASSWORD).status_code == 429
    assert _post(client_from("2001:db8:1:3::1"), password=TEST_PASSWORD).status_code == 303


def test_an_ipv4_mapped_address_counts_as_its_ipv4(account, client_from):
    _block(client_from(f"::ffff:{IP}"))
    assert _post(client_from(IP), password=TEST_PASSWORD).status_code == 429


# --- the unblock CLI --------------------------------------------------------------------

def _cli(app_db, *argv: str) -> tuple[int, str]:
    """python -m app.unblock_ip with `argv`, on the test's clock when it has one
    (the `clock` fixture), so blocks are judged at the same time as the logins."""
    from app.services.clock import get_clock

    test_clock = app.dependency_overrides.get(get_clock)
    lines: list[str] = []
    code = unblock(app_db, list(argv), out=lines.append,
                   now=test_clock()() if test_clock else None)
    return code, "\n".join(lines)


def test_unblock_lifts_the_block_logs_who_and_login_works_again(
        account, client_from, app_db, caplog):
    c = client_from(IP)
    _block(c)
    with caplog.at_level(logging.INFO, logger="app.accounts"):
        code, out = _cli(app_db, IP, "--by", "Peter (Procurement)")
    assert code == 0 and f"Unblocked {IP}" in out
    assert f"login_ip_unblocked ip={IP} by=Peter (Procurement)" in caplog.text
    assert _count(app_db) == 0
    assert _post(c, password=TEST_PASSWORD).status_code == 303


def test_the_real_command_writes_who_unblocked_to_its_log(tmp_path):
    # caplog captures the line even when nobody set up logging, so run the
    # command as a person would: its own process, its own database file.
    import os
    import subprocess
    import sys

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.database import Base
    from app.services.clock import utc_now

    url = f"sqlite:///{(tmp_path / 'cli.db').as_posix()}"
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        now = utc_now()
        db.add(LoginIpFailure(ip=IP, failed_count=MAX_FAILED_LOGINS_PER_IP,
                              window_started_at=now, blocked_until=now + auth.IP_BLOCK))
        db.commit()
    engine.dispose()

    env = {**os.environ, "APP_ENV": "dev", "DATABASE_URL": url}
    done = subprocess.run([sys.executable, "-m", "app.unblock_ip", IP, "--by", "Peter"],
                          capture_output=True, text=True, env=env)
    assert done.returncode == 0, done.stdout + done.stderr
    assert f"INFO app.accounts login_ip_unblocked ip={IP} by=Peter" in done.stderr


def test_unblock_without_by_is_an_error_and_changes_nothing(account, client_from, app_db):
    _block(client_from(IP))
    for argv in ([IP], [IP, "--by", "   "]):
        code, out = _cli(app_db, *argv)
        assert code == 1 and "--by" in out
    assert _count(app_db) == MAX_FAILED_LOGINS_PER_IP


def test_unblock_with_an_equals_sign_in_by_is_an_error_and_changes_nothing(
        account: Account, client_from, app_db) -> None:
    # The audit line is key=value; a name must not add a fake field to it.
    _block(client_from(IP))
    code, out = _cli(app_db, IP, "--by", "x ip=10.9.9.9")
    assert code == 1 and "=" in out
    assert _count(app_db) == MAX_FAILED_LOGINS_PER_IP


def test_unblock_of_something_that_is_not_an_ip_is_an_error(app_db):
    code, out = _cli(app_db, "proxy.example.com", "--by", "Peter")
    assert code == 1 and "not an IP" in out


def test_unblock_of_an_ip_that_is_not_blocked_changes_nothing(account, client_from, app_db,
                                                              clock):
    c = client_from(IP)
    for _ in range(5):
        _post(c)
    assert _cli(app_db, IP, "--by", "Peter")[0] == 2
    assert _count(app_db) == 5                    # counted failures untouched
    assert _cli(app_db, "198.51.100.99", "--by", "Peter")[0] == 2  # never seen
    _block(client_from("198.51.100.9"))
    clock.advance(minutes=15)                     # block ran out by itself
    assert _cli(app_db, "198.51.100.9", "--by", "Peter")[0] == 2


def test_unblock_with_any_address_of_the_slash_64(account, client_from, app_db):
    for i in range(MAX_FAILED_LOGINS_PER_IP):
        _post(client_from(f"2001:db8:1:2::{i + 1:x}"), email=f"spray{i}@test.local")
    assert _cli(app_db, "2001:db8:1:2:ffff::9", "--by", "Peter")[0] == 0
    assert _post(client_from("2001:db8:1:2::1"), password=TEST_PASSWORD).status_code == 303


def test_unblock_the_shared_unknown_bucket(account, client_from, app_db):
    _block(client_from("testclient"))  # not an IP: the shared bucket
    assert _cli(app_db, "unknown", "--by", "Peter")[0] == 0
    assert _post(client_from("testclient"), password=TEST_PASSWORD).status_code == 303
