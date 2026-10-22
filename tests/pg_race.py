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
from concurrent.futures import wait as wait_futures
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

    def wait_reached(self, future_a: Future) -> None:
        """Wait until A holds at its commit. If A ends first, A's own error is
        raised (not a timeout that hides it)."""
        deadline = time.monotonic() + WAIT_SECONDS
        while not self.reached.wait(0.02):
            if future_a.done():
                future_a.result()  # re-raises A's exception, if any
                raise AssertionError("session A finished without committing")
            if time.monotonic() > deadline:
                raise AssertionError("session A never reached its commit")

    def release(self) -> None:
        self._release.set()


def wait_until_lock_wait(engine: Engine, pid: int, future_b: Future) -> None:
    """Poll pg_stat_activity until backend `pid` waits on a lock; bounded.
    Fails at once if B finishes first, with what B returned or raised, so a
    setup error in B does not read as a missing lock."""
    deadline = time.monotonic() + WAIT_SECONDS
    with engine.connect() as c:
        while time.monotonic() < deadline:
            if future_b.done():
                raise AssertionError(f"backend {pid} finished without waiting on a lock; "
                                     f"B gave {_outcome(future_b)!r}")
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
        held = HeldCommit(session_a)
        futures: list[Future] = []
        try:
            futures.append(self._pool.submit(a, session_a))
            held.wait_reached(futures[0])
            pid_b = backend_pid(session_b)
            futures.append(self._pool.submit(b, session_b))
            wait_until_lock_wait(self.engine, pid_b, futures[1])
            held.release()
            return futures[0].result(WAIT_SECONDS), _outcome(futures[1])
        finally:
            # On every path, let A commit and both threads end before their
            # sessions are closed here: a Session must not be used from two
            # threads, and the database is dropped right after the test.
            held.release()
            wait_futures(futures, timeout=WAIT_SECONDS)
            if all(f.done() for f in futures):
                session_a.close()
                session_b.close()

    def run_without_wait(self, a: Callable[[Session], Any],
                         b: Callable[[Session], Any]) -> tuple[Any, Any]:
        """For two actions that must NOT block each other: A takes its locks and
        holds at its commit; B must finish while A still holds. Then A commits.
        Returns (A's result, B's result); B's exception is returned, not raised."""
        session_a, session_b = session_on(self.engine), session_on(self.engine)
        held = HeldCommit(session_a)
        futures: list[Future] = []
        try:
            futures.append(self._pool.submit(a, session_a))
            held.wait_reached(futures[0])
            futures.append(self._pool.submit(b, session_b))
            wait_futures([futures[1]], timeout=WAIT_SECONDS)
            if not futures[1].done():
                raise AssertionError("B did not finish while A held its locks: B was blocked")
            held.release()
            return futures[0].result(WAIT_SECONDS), _outcome(futures[1])
        finally:
            held.release()
            wait_futures(futures, timeout=WAIT_SECONDS)
            if all(f.done() for f in futures):
                session_a.close()
                session_b.close()


def _outcome(future: Future) -> Any:
    try:
        return future.result(WAIT_SECONDS)
    except Exception as e:  # noqa: BLE001 — the test decides what B's error means
        return e
