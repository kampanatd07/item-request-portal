"""STORY-006 ticket 05: when the notifier cannot record a failed email, a lock
timeout (another transaction holds the request row) is an expected warning;
anything else is logged as an error with its traceback."""

import logging

import pytest
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.services import notify


class _LockTimeout(Exception):
    """What psycopg raises when lock_timeout runs out (SQLSTATE 55P03)."""

    sqlstate = notify.LOCK_NOT_AVAILABLE


def _record_with_failing_commit(db: Session, monkeypatch: pytest.MonkeyPatch,
                                error: Exception) -> None:
    def failing_commit() -> None:
        raise error

    monkeypatch.setattr(db, "commit", failing_commit)
    notify._record_failure(db, 1, "procurement@test.local", "needs_info: Graph: 503")


def _records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if "could not record notify_failed" in r.getMessage()]


def test_a_lock_timeout_while_recording_is_a_warning(
        db_session: Session, monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="app.notify"):
        _record_with_failing_commit(db_session, monkeypatch,
                                    OperationalError("INSERT", {}, _LockTimeout()))
    (record,) = _records(caplog)
    assert record.levelno == logging.WARNING and record.exc_info is not None


@pytest.mark.parametrize("error", [
    RuntimeError("disk full"),
    OperationalError("INSERT", {}, Exception("server closed the connection")),
])
def test_any_other_failure_while_recording_is_an_error(
        db_session: Session, monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture, error: Exception) -> None:
    with caplog.at_level(logging.INFO, logger="app.notify"):
        _record_with_failing_commit(db_session, monkeypatch, error)  # never raises
    (record,) = _records(caplog)
    assert record.levelno == logging.ERROR and record.exc_info is not None
