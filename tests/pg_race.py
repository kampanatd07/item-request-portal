"""Helpers for PostgreSQL race tests (STORY-006): two sessions, real row locks.

Pattern: session A runs a real service call and is held just before its
commit, so it keeps every lock it took. Session B then runs in another
thread; the test waits until PostgreSQL itself reports B waiting on a lock
(pg_stat_activity), then lets A commit and checks what B did. Proof that B
was blocked by a lock, not merely slow.
"""

import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

from sqlalchemy import Engine, event, text
from sqlalchemy.orm import Session, sessionmaker

# Every wait is bounded well under pytest's 60 s timeout: a missing lock fails
# the test with a message instead of hanging it.
WAIT_SECONDS = 15


def session_on(engine: Engine) -> Session:
    return sessionmaker(bind=engine, expire_on_commit=False)()


def backend_pid(session: Session) -> int:
    """The PostgreSQL process serving this session's connection. The session
    keeps that connection until it commits or rolls back."""
    return session.execute(text("SELECT pg_backend_pid()")).scalar_one()


class HeldCommit:
    """Holds `session`'s next commit until release(): its locks stay taken.

    Pending changes are flushed first, so what A did is written (uncommitted)
    and its row locks are all in place while it waits.
    """

    def __init__(self, session: Session) -> None:
        self.reached = threading.Event()
        self._release = threading.Event()
        event.listen(session, "before_commit", self._hold, once=True)

    def _hold(self, session: Session) -> None:
        session.flush()
        self.reached.set()
        if not self._release.wait(WAIT_SECONDS):
            raise AssertionError("HeldCommit was never released")

    def wait_reached(self) -> None:
        if not self.reached.wait(WAIT_SECONDS):
            raise AssertionError("session A never reached its commit")

    def release(self) -> None:
        self._release.set()


def wait_until_lock_wait(engine: Engine, pid: int, gave_up: Callable[[], bool]) -> None:
    """Poll pg_stat_activity until backend `pid` waits on a lock; bounded.
    Fails at once if `gave_up()` turns true (B finished without waiting)."""
    deadline = time.monotonic() + WAIT_SECONDS
    with engine.connect() as c:
        while time.monotonic() < deadline:
            if gave_up():
                raise AssertionError(f"backend {pid} finished without waiting on a lock")
            state = c.execute(
                text("SELECT wait_event_type FROM pg_stat_activity WHERE pid = :pid"),
                {"pid": pid},
            ).scalar_one_or_none()
            c.commit()  # a fresh snapshot of pg_stat_activity on the next poll
            if state == "Lock":
                return
            time.sleep(0.02)
    raise AssertionError(f"backend {pid} never waited on a lock")


class Race:
    """Runs A (held before commit) and B (blocked on A's lock) in threads."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self._pool = ThreadPoolExecutor(max_workers=2)

    def __enter__(self) -> "Race":
        return self

    def __exit__(self, *exc: object) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)

    def run(self, a: Callable[[Session], Any], b: Callable[[Session], Any]) -> tuple[Any, Any]:
        """A takes its locks and holds; B starts and must wait on a lock; then
        A commits and B finishes. Returns (A's result, B's result); an
        exception from B is returned, not raised, so a test can check it."""
        session_a, session_b = session_on(self.engine), session_on(self.engine)
        try:
            held = HeldCommit(session_a)
            future_a = self._pool.submit(a, session_a)
            held.wait_reached()
            pid_b = backend_pid(session_b)
            future_b = self._pool.submit(b, session_b)
            try:
                wait_until_lock_wait(self.engine, pid_b, future_b.done)
            finally:
                held.release()
            result_a = future_a.result(WAIT_SECONDS)
            return result_a, _outcome(future_b)
        finally:
            session_a.close()
            session_b.close()


def _outcome(future: Future) -> Any:
    try:
        return future.result(WAIT_SECONDS)
    except Exception as e:  # noqa: BLE001 — the test decides what B's error means
        return e
