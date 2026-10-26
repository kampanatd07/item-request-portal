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

from sqlalchemy import Connection, Engine, event, text
from sqlalchemy.orm import Session, sessionmaker

# Every wait is bounded well under pytest's 60 s timeout: a missing lock fails
# the test with a message instead of hanging it.
WAIT_SECONDS = 15
# How long A may stay held at its commit; longer than WAIT_SECONDS (see HeldCommit).
HOLD_SECONDS = 2 * WAIT_SECONDS


def session_on(engine: Engine) -> Session:
    return sessionmaker(bind=engine, expire_on_commit=False)()


def pinned_session(engine: Engine) -> tuple[Session, Connection]:
    """A session that keeps one connection (one PostgreSQL backend) across its
    commits and rollbacks. A plain session hands its connection back to the
    pool at each commit/rollback, so code that rolls back mid-way (the
    notifier does) could continue on another backend than the one watched in
    pg_stat_activity. Close both when done."""
    connection = engine.connect()
    return sessionmaker(bind=connection, expire_on_commit=False)(), connection


def backend_pid(session: Session) -> int:
    """The PostgreSQL process serving this session's connection. The session
    keeps that connection until it commits or rolls back."""
    return session.execute(text("SELECT pg_backend_pid()")).scalar_one()


class HeldCommit:
    """Holds `session`'s next commit until release(): its locks stay taken.

    Pending changes are flushed first, so what A did is written (uncommitted)
    and its row locks are all in place while it waits. abort() makes the
    held commit fail instead, so A rolls back and its locks go at once.
    """

    def __init__(self, session: Session) -> None:
        self.reached = threading.Event()
        self._release = threading.Event()
        self._aborted = False
        event.listen(session, "before_commit", self._hold, once=True)

    def _hold(self, session: Session) -> None:
        session.flush()
        self.reached.set()
        # Longer than any wait on B, so a failing race is decided (and A
        # aborted) before A's own safety timeout could fire.
        if not self._release.wait(HOLD_SECONDS):
            raise AssertionError("HeldCommit was never released")
        if self._aborted:
            raise AssertionError("A aborted: the race failed (see the test's error)")

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

    def abort(self) -> None:
        self._aborted = True
        self._release.set()


def _lock_wait_state(c: Connection, pid: int) -> str | None:
    state = c.execute(
        text("SELECT wait_event_type FROM pg_stat_activity WHERE pid = :pid"),
        {"pid": pid},
    ).scalar_one_or_none()
    c.commit()  # a fresh snapshot of pg_stat_activity on the next poll
    return state


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
            if _lock_wait_state(c, pid) == "Lock":
                return
            time.sleep(0.02)
    raise AssertionError(f"backend {pid} never waited on a lock")


def wait_until_done_without_lock(engine: Engine, pid: int, future_b: Future) -> None:
    """Poll until B finishes; fail at once if PostgreSQL shows backend `pid`
    waiting on a lock (proof by pg_stat_activity, not by timing); bounded."""
    deadline = time.monotonic() + WAIT_SECONDS
    with engine.connect() as c:
        while time.monotonic() < deadline:
            if future_b.done():
                return
            if _lock_wait_state(c, pid) == "Lock":
                raise AssertionError(f"backend {pid} waited on a lock while A held: "
                                     "B was blocked by A")
            time.sleep(0.02)
    raise AssertionError(f"backend {pid} neither finished nor waited on a lock")


def _rolled_back_on_error(fn: Callable[[Session], Any], session: Session) -> Any:
    """Run fn; on any error roll back, so a failed A or B never keeps its
    locks (an error raised in before_commit leaves the transaction open)."""
    try:
        return fn(session)
    except BaseException:
        session.rollback()
        raise


class Race:
    """Runs A (held before commit) and B in threads; B must wait on A's lock
    (run) or must finish without waiting (run_without_wait)."""

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
        return self._race(a, b, wait_until_lock_wait)

    def run_without_wait(self, a: Callable[[Session], Any],
                         b: Callable[[Session], Any]) -> tuple[Any, Any]:
        """For two actions that must NOT block each other: A takes its locks and
        holds at its commit; B must finish without ever waiting on a lock.
        Then A commits. Returns (A's result, B's result); B's exception is
        returned, not raised."""
        return self._race(a, b, wait_until_done_without_lock)

    def _race(self, a: Callable[[Session], Any], b: Callable[[Session], Any],
              check_b: Callable[[Engine, int, Future], None]) -> tuple[Any, Any]:
        (session_a, conn_a), (session_b, conn_b) = (pinned_session(self.engine),
                                                    pinned_session(self.engine))
        held = HeldCommit(session_a)
        futures: list[Future] = []
        decided = False
        try:
            futures.append(self._pool.submit(_rolled_back_on_error, a, session_a))
            held.wait_reached(futures[0])
            pid_b = backend_pid(session_b)
            futures.append(self._pool.submit(_rolled_back_on_error, b, session_b))
            check_b(self.engine, pid_b, futures[1])
            decided = True
            held.release()
            return futures[0].result(WAIT_SECONDS), _outcome(futures[1])
        finally:
            # A failed race aborts A: it rolls back, its locks go, and a B
            # blocked on them can end. On every path both threads end before
            # their sessions are closed here: a Session must not be used from
            # two threads, and the database is dropped right after the test.
            if not decided:
                held.abort()
            held.release()
            wait_futures(futures, timeout=WAIT_SECONDS)
            if all(f.done() for f in futures):
                session_a.close()
                session_b.close()
                conn_a.close()
                conn_b.close()


def _outcome(future: Future) -> Any:
    try:
        return future.result(WAIT_SECONDS)
    except Exception as e:  # noqa: BLE001 — the test decides what B's error means
        return e
