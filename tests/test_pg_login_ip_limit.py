"""PostgreSQL: parallel failed logins from one IP count exactly as sequential
ones (STORY-006 ticket 07, AC 5). Each attempt is counted under the IP row
lock before it is hashed (ticket 08: count first, refund later), so the 51st
is refused without being checked, even when all arrive at once and the row
does not exist yet; and nothing is held while hashing."""

from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import Engine, select

from app.models import LoginIpFailure
from app.services import auth
from app.services.auth import LOGIN_FAILED, MAX_FAILED_LOGINS_PER_IP, AuthError, IpBlocked
from tests.conftest import TEST_PASSWORD
from tests.pg_race import WAIT_SECONDS, session_on

pytestmark = pytest.mark.postgres

IP = "198.51.100.7"


def _attempt(engine: Engine, email: str, ip: str = IP) -> str:
    """One failed login in its own session; returns how it was refused."""
    with session_on(engine) as db:
        try:
            auth.authenticate(db, email, "wrong-password-000", client_ip=ip)
        except IpBlocked:
            return "blocked"
        except AuthError as e:
            assert str(e) == LOGIN_FAILED
            return "failed"
    return "logged in"


def _run_all(engine: Engine, jobs: list[tuple[str, str]], workers: int = 16) -> Counter:
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_attempt, engine, email, ip) for email, ip in jobs]
        return Counter(f.result(timeout=WAIT_SECONDS * 2) for f in futures)


def test_parallel_failures_from_a_new_ip_count_exactly_like_sequential_ones(
        pg_engine: Engine) -> None:
    n = MAX_FAILED_LOGINS_PER_IP + 30
    outcomes = _run_all(pg_engine, [(f"spray{i}@test.local", IP) for i in range(n)])

    assert outcomes == {"failed": MAX_FAILED_LOGINS_PER_IP, "blocked": 30}
    with session_on(pg_engine) as db:
        row = db.get(LoginIpFailure, IP)
        assert row.failed_count == MAX_FAILED_LOGINS_PER_IP
        assert row.blocked_until is not None


def test_parallel_failures_across_emails_and_ips_never_deadlock(pg_engine: Engine) -> None:
    emails = [f"user{i}@test.local" for i in range(4)]
    with session_on(pg_engine) as db:
        for email in emails:
            auth.create_account(db, email, "User", "procurement", TEST_PASSWORD,
                                must_change_password=False)
    ips = ["198.51.100.1", "198.51.100.2", "198.51.100.3"]
    # Every email from every IP, interleaved: IP row then Account row, always
    # in that order, so no two logins wait on each other in a cycle.
    jobs = [(email, ip) for _ in range(3) for email in emails for ip in ips]

    outcomes = _run_all(pg_engine, jobs)  # a deadlock would raise or time out

    assert outcomes == {"failed": len(jobs)}
    with session_on(pg_engine) as db:
        assert {ip: db.get(LoginIpFailure, ip).failed_count for ip in ips} == {
            ip: len(emails) * 3 for ip in ips}


# --- ticket 08: count first, refund later --------------------------------------------------

@pytest.mark.parametrize("known", [True, False])
def test_no_connection_or_transaction_is_held_while_hashing(pg_engine: Engine, monkeypatch,
                                                            known: bool) -> None:
    if known:
        with session_on(pg_engine) as db:
            auth.create_account(db, "someone@test.local", "Someone", "procurement",
                                TEST_PASSWORD, must_change_password=False)
    real = auth.verify_password
    seen: list[tuple[int, bool]] = []
    with session_on(pg_engine) as db:
        def probe(stored: str, password: str) -> bool:
            seen.append((pg_engine.pool.checkedout(), db.in_transaction()))
            return real(stored, password)

        monkeypatch.setattr(auth, "verify_password", probe)
        with pytest.raises(AuthError):
            auth.authenticate(db, "someone@test.local", "wrong-password-000", client_ip=IP)
    assert seen == [(0, False)]  # nothing checked out of the pool, no open transaction


def test_a_right_password_on_an_account_locked_during_the_hash_is_refused(
        pg_engine: Engine, monkeypatch) -> None:
    from datetime import timedelta

    from sqlalchemy import update

    from app.models import Account
    from app.services.clock import utc_now

    with session_on(pg_engine) as db:
        auth.create_account(db, "someone@test.local", "Someone", "procurement",
                            TEST_PASSWORD, must_change_password=False)
    real = auth.verify_password

    def lock_while_hashing(stored: str, password: str) -> bool:
        # Another login's 10th wrong guess commits while this one hashes.
        with session_on(pg_engine) as other:
            other.execute(update(Account).where(Account.email == "someone@test.local")
                          .values(locked_until=utc_now() + timedelta(minutes=15),
                                  failed_login_count=10))
            other.commit()
        return real(stored, password)

    monkeypatch.setattr(auth, "verify_password", lock_while_hashing)
    with session_on(pg_engine) as db, pytest.raises(AuthError, match=LOGIN_FAILED):
        auth.authenticate(db, "someone@test.local", TEST_PASSWORD, client_ip=IP)
    with session_on(pg_engine) as db:
        account = db.scalar(select(Account).where(Account.email == "someone@test.local"))
        assert account.locked_until is not None and account.failed_login_count == 10


# --- ticket 08 review fix: slots on the Account -------------------------------------------

def test_two_hundred_parallel_guesses_at_one_email_check_its_real_hash_at_most_ten_times(
        pg_engine: Engine, monkeypatch) -> None:
    import threading
    import time

    from app.models import Account
    from app.services.auth import MAX_FAILED_LOGINS

    email = "victim@test.local"
    with session_on(pg_engine) as db:
        real_hash = auth.create_account(db, email, "Victim", "procurement", TEST_PASSWORD,
                                        must_change_password=False).password_hash
    real = auth.verify_password
    gate = threading.Event()
    real_checks: list[str] = []

    def probe(stored: str, password: str) -> bool:
        if stored == real_hash:
            real_checks.append(password)
            gate.wait(WAIT_SECONDS)  # keep the first slots in flight (holding nothing)
        return real(stored, password)

    monkeypatch.setattr(auth, "verify_password", probe)
    ips = [f"198.51.100.{i}" for i in range(1, 6)]  # 40 attempts each: under 50 per IP

    def attempt(password: str, ip: str) -> str:
        with session_on(pg_engine) as db:
            try:
                auth.authenticate(db, email, password, client_ip=ip)
            except IpBlocked:
                return "blocked"
            except AuthError:
                return "failed"
        return "logged in"

    with ThreadPoolExecutor(max_workers=24) as pool:
        first = [pool.submit(attempt, "wrong-password-000", ips[i % 5])
                 for i in range(MAX_FAILED_LOGINS)]
        deadline = time.monotonic() + WAIT_SECONDS
        while len(real_checks) < MAX_FAILED_LOGINS and time.monotonic() < deadline:
            time.sleep(0.01)
        assert len(real_checks) == MAX_FAILED_LOGINS  # all 10 slots in flight
        # 190 more, the right password among them, while the 10 are checked.
        rest = [pool.submit(attempt, TEST_PASSWORD if i % 10 == 0 else "wrong-password-000",
                            ips[i % 5]) for i in range(190)]
        rest_outcomes = Counter(f.result(timeout=WAIT_SECONDS * 2) for f in rest)
        gate.set()
        first_outcomes = Counter(f.result(timeout=WAIT_SECONDS) for f in first)

    assert rest_outcomes == {"failed": 190}  # the right password did not get in
    assert first_outcomes == {"failed": MAX_FAILED_LOGINS}
    assert len(real_checks) == MAX_FAILED_LOGINS  # the real hash: checked 10 times, no more
    with session_on(pg_engine) as db:
        acc = db.scalar(select(Account).where(Account.email == email))
        assert acc.locked_until is not None and acc.failed_login_count == MAX_FAILED_LOGINS
        assert (acc.pending_checks, acc.pending_since) == (0, None)
