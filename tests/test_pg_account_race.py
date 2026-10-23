"""PostgreSQL: Account races (STORY-006 ticket 04, AC 4 and AC 5).

(a) Administrators deactivating or demoting each other at the same moment:
the rows of all active Administrators are locked in id order, and an actor
who lost the role meanwhile is refused (PERMISSION_CHANGED), so exactly the
expected one remains. (b) Parallel wrong passwords for one email reach its
real hash exactly 10 times and lock it once ("being checked" slots, ticket
08); every attempt gets the same answer. Each test proves the calls really
overlapped: run one after another, it fails.
"""

import logging
import threading
from collections.abc import Callable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import wait as wait_futures
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.main import app
from app.models import Account
from app.services import auth
from app.services.auth import LOGIN_FAILED, MAX_FAILED_LOGINS, PERMISSION_CHANGED, AuthError
from tests.conftest import TEST_PASSWORD
from tests.pg_race import (
    WAIT_SECONDS,
    HeldCommit,
    Race,
    backend_pid,
    session_on,
    wait_until_lock_wait,
)

pytestmark = pytest.mark.postgres

Action = Callable[[Session], str]


def _admins(engine: Engine, n: int) -> list[int]:
    with session_on(engine) as db:
        return [auth.create_account(db, f"admin{i}@test.local", f"Admin {i}", "administrator",
                                    TEST_PASSWORD, must_change_password=False).id
                for i in range(1, n + 1)]


def _deactivate(acting_id: int, target_id: int) -> Action:
    def run(db: Session) -> str:
        auth.deactivate_account(db, db.get(Account, acting_id), target_id)
        return "deactivated"
    return run


def _demote(acting_id: int, target_id: int) -> Action:
    def run(db: Session) -> str:
        auth.change_access(db, db.get(Account, acting_id), target_id,
                           role="procurement", factory_id=None)
        return "demoted"
    return run


LABEL = {_deactivate: "deactivated", _demote: "demoted"}


def _active_admins(engine: Engine) -> list[int]:
    with session_on(engine) as db:
        return list(db.scalars(select(Account.id).where(
            Account.role == "administrator", Account.active).order_by(Account.id)))


def _outcome(future: Future) -> str:
    """'deactivated' / 'demoted', or 'refused: <message>' for an AuthError."""
    try:
        return future.result(0)
    except AuthError as e:
        return f"refused: {e}"


def _all_done(pool: ThreadPoolExecutor, futures: list[Future], seconds: float) -> None:
    """Wait for all, within one overall bound; never wait on a hung thread."""
    _, not_done = wait_futures(futures, timeout=seconds)
    pool.shutdown(wait=False, cancel_futures=True)
    assert not not_done, f"{len(not_done)} call(s) still running after {seconds} s"


# --- (a) two Administrators ---------------------------------------------------------------

@pytest.mark.parametrize("first, second", [
    (_deactivate, _deactivate), (_demote, _demote), (_deactivate, _demote), (_demote, _deactivate),
])
def test_two_administrators_acting_on_each_other_leave_the_first(
        pg_engine: Engine, first: Callable[[int, int], Action],
        second: Callable[[int, int], Action]) -> None:
    a1, a2 = _admins(pg_engine, 2)

    with Race(pg_engine) as race:  # B waits on A's Administrator row locks
        done, refused = race.run(first(a1, a2), second(a2, a1))

    assert done == LABEL[first]
    # a2 lost the role while waiting: refused for that, not as "the last one".
    assert isinstance(refused, AuthError) and str(refused) == PERMISSION_CHANGED, refused
    assert _active_admins(pg_engine) == [a1]


def test_three_administrators_in_a_cycle_two_succeed_and_one_is_refused(
        pg_engine: Engine) -> None:
    a1, a2, a3 = _admins(pg_engine, 3)
    session_a, session_b, session_c = (session_on(pg_engine) for _ in range(3))
    held = HeldCommit(session_a)
    pool = ThreadPoolExecutor(max_workers=3)
    decided = False
    try:
        # a1 -> a2 takes the locks and holds; a2 -> a3 and a3 -> a1 must both
        # be waiting on them at the same moment (proof of overlap).
        future_a = pool.submit(_deactivate(a1, a2), session_a)
        held.wait_reached(future_a)
        pid_b, pid_c = backend_pid(session_b), backend_pid(session_c)
        future_b = pool.submit(_deactivate(a2, a3), session_b)
        future_c = pool.submit(_deactivate(a3, a1), session_c)
        wait_until_lock_wait(pg_engine, pid_b, future_b)
        wait_until_lock_wait(pg_engine, pid_c, future_c)
        decided = True
        held.release()
        _all_done(pool, [future_a, future_b, future_c], WAIT_SECONDS)
    finally:
        if not decided:
            held.abort()
        pool.shutdown(wait=False, cancel_futures=True)
        for s in (session_a, session_b, session_c):
            s.rollback()
            s.close()

    # In either order of b and c: a2 is no longer an Administrator when its
    # call runs, and a3 -> a1 leaves a3.
    assert [_outcome(f) for f in (future_a, future_b, future_c)] == [
        "deactivated", f"refused: {PERMISSION_CHANGED}", "deactivated"]
    assert _active_admins(pg_engine) == [a3]


# --- (b) parallel wrong passwords for one email, raced freely ----------------------------

EMAIL = "victim@test.local"


@pytest.fixture()
def http_on_pg(pg_engine: Engine) -> Iterator[None]:
    """The app's requests use this test's PostgreSQL database, one session each."""
    def _db() -> Iterator[Session]:
        with session_on(pg_engine) as db:
            yield db

    app.dependency_overrides[get_db] = _db
    yield
    app.dependency_overrides.pop(get_db, None)


@pytest.mark.parametrize("round_no", [1, 2, 3])  # each free race orders itself differently
def test_thirty_parallel_wrong_passwords_at_one_email(
        pg_engine: Engine, http_on_pg: None, monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture, round_no: int) -> None:
    with session_on(pg_engine) as db:
        real_hash = auth.create_account(db, EMAIL, "Victim", "procurement", TEST_PASSWORD,
                                        must_change_password=False).password_hash
    real = auth.verify_password
    guard = threading.Lock()
    seen = {"real_checks": 0, "max_slots": 0}
    two_checking = threading.Event()
    in_check = [0]

    def count(stored: str, password: str) -> bool:
        if stored != real_hash:
            return real(stored, password)
        with guard:
            seen["real_checks"] += 1
            in_check[0] += 1
            if in_check[0] >= 2:
                two_checking.set()
        with session_on(pg_engine) as db:  # slots in use, as stored right now
            slots = db.scalar(select(Account.pending_checks).where(Account.email == EMAIL))
        with guard:
            seen["max_slots"] = max(seen["max_slots"], slots)
        # Give a parallel login the moment to be in its check too. One after
        # another, each check waits this once and slots never pass 1: fails.
        two_checking.wait(2)
        try:
            return real(stored, password)
        finally:
            with guard:
                in_check[0] -= 1

    monkeypatch.setattr(auth, "verify_password", count)

    def attempt(i: int) -> tuple[int, str]:
        # One IP each: 30 IPs, so no IP limit is near.
        with TestClient(app, client=(f"198.51.100.{i + 1}", 50000)) as c:
            r = c.post("/login", data={"email": EMAIL, "password": "wrong-password-000"},
                       follow_redirects=False)
            return r.status_code, r.text

    pool = ThreadPoolExecutor(max_workers=30)
    with caplog.at_level(logging.INFO, logger="app.accounts"):
        futures = [pool.submit(attempt, i) for i in range(30)]
        _all_done(pool, futures, WAIT_SECONDS * 2)
    answers: list[Any] = [f.result(0) for f in futures]

    # Same answer for all 30, whether checked against the real hash or refused
    # because the Account was full or already locked.
    variants = {(status, text) for status, text in answers}
    assert len(variants) == 1, [(status, text[:400]) for status, text in variants]
    status, text = answers[0]
    assert status == 401 and LOGIN_FAILED in text
    assert seen["max_slots"] > 1, "the logins never overlapped"
    assert seen["real_checks"] == MAX_FAILED_LOGINS, seen
    locked_lines = [r for r in caplog.records
                    if "action=locked" in r.getMessage() and EMAIL in r.getMessage()]
    assert len(locked_lines) == 1
    with session_on(pg_engine) as db:
        account = db.scalar(select(Account).where(Account.email == EMAIL))
        assert account.failed_login_count == MAX_FAILED_LOGINS
        assert account.locked_until is not None
        assert (account.pending_checks, account.pending_since) == (0, None)
