"""PostgreSQL: Account races (STORY-006 ticket 04, AC 4 and AC 5).

(a) Administrators deactivating or demoting each other at the same moment
always leave at least one active Administrator (all active Administrator
rows locked in id order, STORY-001 ticket 04). (b) Parallel wrong passwords
for one email, raced freely, reach its real hash at most 10 times and lock
it exactly once ("being checked" slots, ticket 08); every attempt gets the
same answer.
"""

import logging
import threading
from collections import Counter
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.main import app
from app.models import Account
from app.services import auth
from app.services.auth import LOGIN_FAILED, MAX_FAILED_LOGINS, AuthError
from tests.conftest import TEST_PASSWORD
from tests.pg_race import WAIT_SECONDS, Race, session_on

pytestmark = pytest.mark.postgres

LAST_ADMIN = "ผู้ดูแลระบบคนสุดท้ายที่ใช้งานอยู่"


def _admins(engine: Engine, n: int) -> list[int]:
    with session_on(engine) as db:
        return [auth.create_account(db, f"admin{i}@test.local", f"Admin {i}", "administrator",
                                    TEST_PASSWORD, must_change_password=False).id
                for i in range(1, n + 1)]


def _deactivate(acting_id: int, target_id: int) -> Callable[[Session], str]:
    def run(db: Session) -> str:
        auth.deactivate_account(db, db.get(Account, acting_id), target_id)
        return "deactivated"
    return run


def _demote(acting_id: int, target_id: int) -> Callable[[Session], str]:
    def run(db: Session) -> str:
        auth.change_access(db, db.get(Account, acting_id), target_id,
                           role="procurement", factory_id=None)
        return "demoted"
    return run


def _active_admins(engine: Engine) -> list[int]:
    with session_on(engine) as db:
        return list(db.scalars(select(Account.id).where(
            Account.role == "administrator", Account.active).order_by(Account.id)))


# --- (a) two Administrators ---------------------------------------------------------------

@pytest.mark.parametrize("first, second", [
    (_deactivate, _deactivate), (_demote, _demote), (_deactivate, _demote), (_demote, _deactivate),
])
def test_two_administrators_acting_on_each_other_leave_one(pg_engine: Engine, first, second
                                                           ) -> None:
    a1, a2 = _admins(pg_engine, 2)

    with Race(pg_engine) as race:  # B must wait on A's Administrator row locks
        done, refused = race.run(first(a1, a2), second(a2, a1))

    assert done in ("deactivated", "demoted")
    assert isinstance(refused, AuthError) and LAST_ADMIN in str(refused), refused
    assert _active_admins(pg_engine) == [a1]


def test_three_administrators_in_a_cycle_leave_at_least_one(pg_engine: Engine) -> None:
    a1, a2, a3 = _admins(pg_engine, 3)
    start = threading.Barrier(3)

    def attempt(acting: int, target: int) -> str:
        with session_on(pg_engine) as db:
            start.wait(WAIT_SECONDS)
            try:
                return _deactivate(acting, target)(db)
            except AuthError as e:
                return "refused" if LAST_ADMIN in str(e) else f"error: {e}"

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(attempt, x, y) for x, y in ((a1, a2), (a2, a3), (a3, a1))]
        outcomes = [f.result(timeout=WAIT_SECONDS * 2) for f in futures]  # no deadlock

    assert set(outcomes) <= {"deactivated", "refused"}, outcomes
    assert "deactivated" in outcomes
    assert len(_active_admins(pg_engine)) >= 1


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
def test_thirty_parallel_wrong_passwords_at_one_email(pg_engine: Engine, http_on_pg,
                                                       monkeypatch, caplog,
                                                       round_no: int) -> None:
    with session_on(pg_engine) as db:
        real_hash = auth.create_account(db, EMAIL, "Victim", "procurement", TEST_PASSWORD,
                                        must_change_password=False).password_hash
    real = auth.verify_password
    real_checks: list[int] = []

    def count(stored: str, password: str) -> bool:
        if stored == real_hash:
            real_checks.append(1)
        return real(stored, password)

    monkeypatch.setattr(auth, "verify_password", count)

    def attempt(i: int) -> tuple[int, str]:
        # One IP each: 30 IPs, so no IP limit is near.
        with TestClient(app, client=(f"198.51.100.{i + 1}", 50000)) as c:
            r = c.post("/login", data={"email": EMAIL, "password": "wrong-password-000"},
                       follow_redirects=False)
            return r.status_code, r.text

    with caplog.at_level(logging.INFO, logger="app.accounts"), \
            ThreadPoolExecutor(max_workers=30) as pool:
        answers = [f.result(timeout=WAIT_SECONDS * 2)
                   for f in [pool.submit(attempt, i) for i in range(30)]]

    # Same answer for all 30, whether checked against the real hash or refused
    # because the Account was full or already locked.
    assert len(set(answers)) == 1, Counter(status for status, _ in answers)
    status, text = answers[0]
    assert status == 401 and LOGIN_FAILED in text
    assert len(real_checks) <= MAX_FAILED_LOGINS, len(real_checks)
    locked_lines = [r for r in caplog.records
                    if "action=locked" in r.getMessage() and EMAIL in r.getMessage()]
    assert len(locked_lines) == 1
    with session_on(pg_engine) as db:
        account = db.scalar(select(Account).where(Account.email == EMAIL))
        assert account.failed_login_count == MAX_FAILED_LOGINS
        assert account.locked_until is not None
        assert (account.pending_checks, account.pending_since) == (0, None)
