"""STORY-006 ticket 08, review fix: "being checked" slots on the Account and
the IP. Confirmed failures + slots in use may not pass the limits; slots
expire 1 minute after the count went 0 -> 1 and are then written back as
empty; freeing never goes below 0; back at 0 the time is cleared. Also:
slots are freed after an error, a hash that changes while being checked is
checked again, and the hash upgrade never overwrites a changed password."""

from datetime import timedelta

import pytest
from sqlalchemy import update

from app.models import Account, LoginIpFailure
from app.services import auth
from app.services.auth import (
    LOGIN_FAILED,
    MAX_FAILED_LOGINS,
    MAX_FAILED_LOGINS_PER_IP,
    PENDING_EXPIRY,
    AuthError,
    IpBlocked,
)
from tests.conftest import TEST_PASSWORD

EMAIL = "someone@test.local"
WRONG = "wrong-password-000"
IP = "198.51.100.7"


@pytest.fixture()
def account(clock, app_db) -> Account:
    return auth.create_account(app_db, EMAIL, "Someone", "procurement", TEST_PASSWORD,
                               must_change_password=False)


def _login(db, clock, password: str = WRONG) -> Account:
    return auth.authenticate(db, EMAIL, password, now=clock(), client_ip=IP)


def _rows(db) -> tuple[Account, LoginIpFailure]:
    db.expire_all()
    return (db.query(Account).filter_by(email=EMAIL).one(), db.get(LoginIpFailure, IP))


def _set_slots(db, clock, *, account: tuple[int, timedelta] | None = None,
               ip: tuple[int, timedelta] | None = None) -> None:
    """Put `n` slots taken `ago` on the Account and/or the IP."""
    now = clock()
    if account:
        db.execute(update(Account).where(Account.email == EMAIL).values(
            pending_checks=account[0], pending_since=now - account[1]))
    if ip:
        if db.get(LoginIpFailure, IP) is None:
            db.add(LoginIpFailure(ip=IP, failed_count=0, window_started_at=now))
            db.flush()
        db.execute(update(LoginIpFailure).where(LoginIpFailure.ip == IP).values(
            pending_checks=ip[0], pending_since=now - ip[1]))
    db.commit()


def _probe(monkeypatch, on_check):
    """Replace the hash check: on_check(stored_hash, password) runs first."""
    real = auth.verify_password

    def probe(stored: str, password: str) -> bool:
        on_check(stored, password)
        return real(stored, password)

    monkeypatch.setattr(auth, "verify_password", probe)


# --- the limits count slots in use ------------------------------------------------------

def test_slots_in_use_fill_the_account_limit_and_its_real_hash_is_not_checked(
        account, app_db, clock, monkeypatch):
    _set_slots(app_db, clock, account=(MAX_FAILED_LOGINS, timedelta(seconds=30)))
    checked: list[str] = []
    _probe(monkeypatch, lambda stored, pw: checked.append(stored))
    with pytest.raises(AuthError, match=LOGIN_FAILED):
        _login(app_db, clock, TEST_PASSWORD)  # even the right password
    assert account.password_hash not in checked and len(checked) == 1  # dummy, same work
    acc, _ = _rows(app_db)
    assert acc.pending_checks == MAX_FAILED_LOGINS  # no slot taken, none freed


def test_slots_in_use_fill_the_ip_limit(account, app_db, clock):
    _set_slots(app_db, clock, ip=(MAX_FAILED_LOGINS_PER_IP, timedelta(seconds=30)))
    with pytest.raises(IpBlocked):
        _login(app_db, clock, TEST_PASSWORD)


# --- expiry: written back as empty, then this login takes a fresh slot ------------------

@pytest.mark.parametrize("side", ["account", "ip"])
def test_expired_slots_are_written_back_empty_and_this_login_takes_slot_one(
        account, app_db, clock, monkeypatch, side):
    limit = MAX_FAILED_LOGINS if side == "account" else MAX_FAILED_LOGINS_PER_IP
    _set_slots(app_db, clock, **{side: (limit, PENDING_EXPIRY)})  # exactly 1 minute old
    during: list[tuple[int, object]] = []

    def look(stored: str, pw: str) -> None:
        acc, ip = _rows(app_db)
        row = acc if side == "account" else ip
        during.append((row.pending_checks, row.pending_since))

    _probe(monkeypatch, look)
    assert _login(app_db, clock, TEST_PASSWORD).email == EMAIL  # not locked, not blocked
    assert during == [(1, clock())]  # reset to 0, then this login's own slot: (1, now)
    acc, ip = _rows(app_db)
    row = acc if side == "account" else ip
    assert (row.pending_checks, row.pending_since) == (0, None)


@pytest.mark.parametrize("side", ["account", "ip"])
def test_after_expiry_the_limit_holds_again(account, app_db, clock, side):
    limit = MAX_FAILED_LOGINS if side == "account" else MAX_FAILED_LOGINS_PER_IP
    _set_slots(app_db, clock, **{side: (limit, PENDING_EXPIRY)})
    _login(app_db, clock, TEST_PASSWORD)  # writes the expired slots back as empty
    # Fresh slots now fill it again: the write-back did not turn the limit off.
    _set_slots(app_db, clock, **{side: (limit, timedelta(seconds=30))})
    with pytest.raises(IpBlocked if side == "ip" else AuthError):
        _login(app_db, clock, TEST_PASSWORD)


@pytest.mark.parametrize("side", ["account", "ip"])
def test_slots_younger_than_a_minute_still_count(account, app_db, clock, side):
    limit = MAX_FAILED_LOGINS if side == "account" else MAX_FAILED_LOGINS_PER_IP
    _set_slots(app_db, clock, **{side: (limit, PENDING_EXPIRY - timedelta(seconds=1))})
    with pytest.raises(IpBlocked if side == "ip" else AuthError):
        _login(app_db, clock, TEST_PASSWORD)


# --- freeing never goes below 0; back at 0 the time is cleared ---------------------------

def test_freeing_after_the_slots_were_reset_never_goes_below_zero(
        account, app_db, clock, monkeypatch):
    def reset_both(stored: str, pw: str) -> None:
        # Meanwhile another login found them expired and wrote them back empty.
        app_db.execute(update(Account).values(pending_checks=0, pending_since=None))
        app_db.execute(update(LoginIpFailure).values(pending_checks=0, pending_since=None))
        app_db.commit()

    _probe(monkeypatch, reset_both)
    with pytest.raises(AuthError):
        _login(app_db, clock)
    acc, ip = _rows(app_db)
    assert (acc.pending_checks, acc.pending_since) == (0, None)
    assert (ip.pending_checks, ip.pending_since) == (0, None)


def test_back_at_zero_the_time_is_cleared_on_both_rows(account, app_db, clock):
    with pytest.raises(AuthError):
        _login(app_db, clock)
    _login(app_db, clock, TEST_PASSWORD)
    acc, ip = _rows(app_db)
    assert (acc.pending_checks, acc.pending_since) == (0, None)
    assert (ip.pending_checks, ip.pending_since) == (0, None)
    assert acc.failed_login_count == 0 and ip.failed_count == 1


def test_one_slot_stays_while_another_is_freed(account, app_db, clock):
    _set_slots(app_db, clock, account=(1, timedelta(seconds=5)), ip=(1, timedelta(seconds=5)))
    _login(app_db, clock, TEST_PASSWORD)
    acc, ip = _rows(app_db)
    since = clock() - timedelta(seconds=5)
    assert (acc.pending_checks, acc.pending_since) == (1, since)  # the other login's
    assert (ip.pending_checks, ip.pending_since) == (1, since)


# --- an error frees the slots -------------------------------------------------------------

def test_an_error_during_the_check_frees_both_slots(account, app_db, clock, monkeypatch):
    def broken(stored: str, pw: str) -> bool:
        raise RuntimeError("hashing broke")

    monkeypatch.setattr(auth, "verify_password", broken)
    with pytest.raises(RuntimeError, match="hashing broke"):
        _login(app_db, clock, TEST_PASSWORD)
    acc, ip = _rows(app_db)
    assert (acc.pending_checks, acc.pending_since) == (0, None)
    assert (ip.pending_checks, ip.pending_since) == (0, None)
    assert acc.failed_login_count == 0 and ip.failed_count == 0  # not a wrong password


# --- a hash that changes while it is checked ---------------------------------------------

def test_a_hash_upgraded_during_the_check_is_checked_again_and_lets_the_right_password_in(
        account, app_db, clock, monkeypatch):
    calls: list[str] = []

    def upgrade_once(stored: str, pw: str) -> None:
        calls.append(stored)
        if len(calls) == 1:
            # Another login of the same person re-hashed it (new salt, same password).
            app_db.execute(update(Account).where(Account.email == EMAIL)
                           .values(password_hash=auth.hash_password(TEST_PASSWORD)))
            app_db.commit()

    _probe(monkeypatch, upgrade_once)
    assert _login(app_db, clock, TEST_PASSWORD).email == EMAIL
    assert len(calls) == 2 and calls[0] != calls[1]
    acc, _ = _rows(app_db)
    assert acc.failed_login_count == 0 and acc.pending_checks == 0


# --- the hash upgrade never overwrites a changed password ---------------------------------

class _AlwaysRehash:
    """The real hasher, but every hash counts as needing an upgrade (as after
    the Argon2 cost is raised)."""

    def __init__(self, real) -> None:
        self._real = real

    def __getattr__(self, name: str):
        return getattr(self._real, name)

    def check_needs_rehash(self, _hash: str) -> bool:
        return True


@pytest.fixture()
def always_rehash(monkeypatch):
    real = auth._current_hasher()
    monkeypatch.setattr(auth, "_current_hasher", lambda: _AlwaysRehash(real))


def test_the_hash_upgrade_rewrites_the_hash_it_checked(account, app_db, always_rehash):
    old = account.password_hash
    auth._upgrade_hash(app_db, account, old, TEST_PASSWORD)
    acc, _ = _rows(app_db)
    assert acc.password_hash != old and auth.verify_password(acc.password_hash, TEST_PASSWORD)


def test_the_hash_upgrade_never_overwrites_a_password_changed_meanwhile(
        account, app_db, always_rehash):
    old = account.password_hash
    changed = auth.hash_password("a-brand-new-password")
    app_db.execute(update(Account).where(Account.id == account.id)
                   .values(password_hash=changed))
    app_db.commit()
    auth._upgrade_hash(app_db, account, old, TEST_PASSWORD)  # checked the old one
    acc, _ = _rows(app_db)
    assert acc.password_hash == changed


# --- second review (A): a failed hash upgrade -------------------------------------------

def test_a_failed_hash_upgrade_still_logs_in_and_frees_no_other_logins_slot(
        account, app_db, clock, monkeypatch, always_rehash, caplog):
    import logging

    from fastapi.testclient import TestClient

    from app.main import app

    since = clock() - timedelta(seconds=5)
    _set_slots(app_db, clock, account=(1, timedelta(seconds=5)), ip=(1, timedelta(seconds=5)))

    def db_error(*a, **kw):
        raise RuntimeError("database went away")  # the upgrade's UPDATE fails

    monkeypatch.setattr(auth, "update", db_error)
    with caplog.at_level(logging.WARNING, logger="app.auth"), \
            TestClient(app, client=(IP, 50000)) as c:
        r = c.post("/login", data={"email": EMAIL, "password": TEST_PASSWORD},
                   follow_redirects=False)
    assert r.status_code == 303
    assert "login_hash_upgrade_failed" in caplog.text
    acc, ip = _rows(app_db)
    assert (acc.pending_checks, acc.pending_since) == (1, since)  # the other login's slot
    assert (ip.pending_checks, ip.pending_since) == (1, since)


# --- second review (B): one re-check, written on rows locked afresh ---------------------

def test_a_changed_hash_is_checked_once_more_and_others_writes_meanwhile_are_kept(
        account, app_db, clock, monkeypatch):
    calls: list[str] = []

    def meanwhile(stored: str, pw: str) -> None:
        calls.append(stored)
        if len(calls) == 1:
            # During the first check: another login of the same person
            # re-hashes the password; another login fails from this IP; a
            # third takes a slot on the Account.
            app_db.execute(update(Account).where(Account.email == EMAIL).values(
                password_hash=auth.hash_password(TEST_PASSWORD),
                pending_checks=Account.pending_checks + 1))
            app_db.execute(update(LoginIpFailure).values(failed_count=7))
        else:
            # During the re-check: one more failure from this IP.
            app_db.execute(update(LoginIpFailure).values(failed_count=8))
        app_db.commit()

    _probe(monkeypatch, meanwhile)
    assert _login(app_db, clock, TEST_PASSWORD).email == EMAIL
    assert len(calls) == 2 and calls[0] != calls[1]  # checked again, once
    acc, ip = _rows(app_db)
    assert ip.failed_count == 8  # not overwritten from a row read before the re-check
    assert ip.pending_checks == 0
    assert acc.pending_checks == 1  # the other login's slot; this one's freed
    assert acc.failed_login_count == 0


def test_a_locked_account_is_refused_before_any_re_check(account, app_db, clock, monkeypatch):
    calls: list[str] = []

    def lock_and_change(stored: str, pw: str) -> None:
        calls.append(stored)
        app_db.execute(update(Account).where(Account.email == EMAIL).values(
            password_hash=auth.hash_password(TEST_PASSWORD),
            locked_until=clock() + timedelta(minutes=15), failed_login_count=10))
        app_db.commit()

    _probe(monkeypatch, lock_and_change)
    with pytest.raises(AuthError, match=LOGIN_FAILED):
        _login(app_db, clock, TEST_PASSWORD)
    assert len(calls) == 1  # one hash, like a wrong password on a locked Account


def test_a_hash_that_changes_again_during_the_re_check_is_refused(
        account, app_db, clock, monkeypatch):
    calls: list[str] = []

    def change_every_time(stored: str, pw: str) -> None:
        calls.append(stored)
        app_db.execute(update(Account).where(Account.email == EMAIL)
                       .values(password_hash=auth.hash_password(TEST_PASSWORD)))
        app_db.commit()

    _probe(monkeypatch, change_every_time)
    with pytest.raises(AuthError, match=LOGIN_FAILED):
        _login(app_db, clock, TEST_PASSWORD)
    assert len(calls) == 2  # never a third round
    acc, ip = _rows(app_db)
    assert acc.pending_checks == 0 and ip.pending_checks == 0


# --- (ข) 4: the prune never deletes a row whose logins are being checked ------------------

@pytest.mark.parametrize("slot_age, kept", [(timedelta(seconds=10), True),
                                            (PENDING_EXPIRY + timedelta(seconds=1), False)])
def test_the_prune_keeps_an_idle_ip_row_while_its_slots_are_live(
        account, app_db, clock, slot_age, kept):
    other = "192.0.2.50"
    app_db.add(LoginIpFailure(ip=other, failed_count=0,
                              window_started_at=clock() - timedelta(days=2),
                              pending_checks=3, pending_since=clock() - slot_age))
    app_db.commit()
    with pytest.raises(AuthError):
        _login(app_db, clock)  # a failure runs the prune
    app_db.expire_all()
    assert (app_db.get(LoginIpFailure, other) is not None) is kept
