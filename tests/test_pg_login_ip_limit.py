"""PostgreSQL: parallel failed logins from one IP count exactly as sequential
ones (STORY-006 ticket 07, AC 5). The IP row is locked through the hashing,
so the 51st attempt is refused without being checked, even when all arrive
at once and the row does not exist yet."""

from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import Engine

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
