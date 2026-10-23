"""PostgreSQL: the notifier and the rejection race (STORY-006 ticket 05, AC 4).

The notifier claims a request row (`UPDATE … SET status = status WHERE id
AND status`), sends while it holds the row, then commits. So two resends at
once send one email; a notifier that cannot get the row within its
`lock_timeout` gives up and leaves the email owed; and a rejection racing an
export of the same row ends consistent: in the file means exported, rejected
means not in the file.
"""

import io
import time
from collections.abc import Callable

import pytest
from openpyxl import load_workbook
from sqlalchemy import Engine, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.models import ItemRequest, RequestEvent, RetiredCode
from app.services import notify
from app.services.clock import utc_now
from app.services.exporter import build_workbook_bytes, export_pending
from app.services.notify import (
    LOST_AFTER,
    latest_status_event,
    notify_created,
    notify_status,
    pending_notifications,
)
from app.services.requests import RequestError, change_status, submit_request
from tests.conftest import FakeMailSender, account_for, central_ids
from tests.pg_race import WAIT_SECONDS, Race, session_on

pytestmark = pytest.mark.postgres

ACTOR = "procurement@test.local"


def _submitted(db: Session) -> int:
    factory, system, group, sub = central_ids(db)
    return submit_request(db, account_for(db, "requester", plant="APM"),
                          factory_id=factory.id, code_system_id=system.id, group_id=group.id,
                          subgroup_id=sub.id, item_name="Ball Bearing SKF 6205", uom="EA").id


def _approved(db: Session) -> int:
    request_id = _submitted(db)
    change_status(db, request_id, new_status="approved", account=account_for(db, "administrator"))
    return request_id


def _created(engine: Engine) -> int:
    """A request exported and marked created in AX: its email is owed."""
    with session_on(engine) as db:
        account_for(db, "administrator")
        account_for(db, "procurement")
        request_id = _approved(db)
        export_pending(db, central_ids(db)[0].id, account=account_for(db))
        change_status(db, request_id, new_status="created", account=account_for(db))
    return request_id


def _announced(engine: Engine, status: str) -> tuple[int, int]:
    """A request moved to needs_info or rejected (after approval); (id, change id)."""
    with session_on(engine) as db:
        admin = account_for(db, "administrator")
        request_id = _approved(db) if status == "rejected" else _submitted(db)
        change_status(db, request_id, new_status=status, note="ขอรายละเอียดเพิ่ม",
                      account=admin)
        return request_id, latest_status_event(db, request_id).id


def _status(engine: Engine, request_id: int) -> str:
    with session_on(engine) as db:
        return db.get(ItemRequest, request_id).status


def _events(engine: Engine, request_id: int, action: str) -> list[RequestEvent]:
    with session_on(engine) as db:
        return list(db.scalars(select(RequestEvent).where(
            RequestEvent.request_id == request_id, RequestEvent.action == action)))


# --- two resends at once send one email ----------------------------------------------------

def test_two_resends_of_a_created_email_at_once_send_one(pg_engine: Engine) -> None:
    request_id = _created(pg_engine)
    outbox = FakeMailSender()

    def resend(db: Session) -> dict[str, int]:
        return notify_created(lambda: db, [request_id], outbox, ACTOR)

    with Race(pg_engine) as race:  # A sent and holds its claim; B waits on the row
        first, second = race.run(resend, resend)

    assert first == {"sent": 1, "failed": 0, "skipped": 0}
    assert second == {"sent": 0, "failed": 0, "skipped": 1}, second
    assert len(outbox.sent) == 1
    assert _status(pg_engine, request_id) == "notified"
    assert len(_events(pg_engine, request_id, "notified")) == 1


@pytest.mark.parametrize("status", ["needs_info", "rejected"])
def test_two_resends_of_a_status_email_at_once_send_one(pg_engine: Engine, status: str) -> None:
    request_id, change_id = _announced(pg_engine, status)
    outbox = FakeMailSender()

    def resend(db: Session) -> str:
        return notify_status(lambda: db, request_id, change_id, outbox, ACTOR)

    with Race(pg_engine) as race:
        first, second = race.run(resend, resend)

    # B gets the row (the status did not change) but finds the change announced.
    assert (first, second) == ("sent", "skipped"), second
    assert len(outbox.sent) == 1
    notified = _events(pg_engine, request_id, "notified")
    assert [e.ref_event_id for e in notified] == [change_id]


# --- a notifier that cannot get the row gives up -------------------------------------------

@pytest.fixture()
def short_lock_timeout(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """lock_timeout of 1 s for the notifier, and a record of the SQLSTATE of
    each claim that failed: proof it gave up on a lock, not for another reason."""
    monkeypatch.setattr(notify, "NOTIFY_LOCK_TIMEOUT_SECONDS", 1)
    real_claim = notify._claim
    sqlstates: list[str] = []

    def claim(db: Session, request_id: int, status: str) -> ItemRequest | None:
        try:
            return real_claim(db, request_id, status)
        except OperationalError as e:
            sqlstates.append(getattr(e.orig, "sqlstate", None))
            raise

    monkeypatch.setattr(notify, "_claim", claim)
    return sqlstates


def _hold_row(engine: Engine, request_id: int) -> Session:
    """Another transaction holding the request row (e.g. a long write)."""
    holder = session_on(engine)
    holder.execute(text("SELECT id FROM item_requests WHERE id = :id FOR UPDATE"),
                   {"id": request_id})
    return holder


def _timed(call: Callable[[], object]) -> tuple[object, float]:
    started = time.monotonic()
    result = call()
    return result, time.monotonic() - started


LOCK_NOT_AVAILABLE = "55P03"  # PostgreSQL: lock_timeout reached


def test_a_created_email_whose_row_stays_locked_is_left_owed(
        pg_engine: Engine, short_lock_timeout: list[str]) -> None:
    request_id = _created(pg_engine)
    outbox = FakeMailSender()
    holder = _hold_row(pg_engine, request_id)
    try:
        result, seconds = _timed(lambda: notify_created(
            lambda: session_on(pg_engine), [request_id], outbox, ACTOR))
    finally:
        holder.rollback()
        holder.close()

    assert result == {"sent": 0, "failed": 0, "skipped": 1}
    assert short_lock_timeout == [LOCK_NOT_AVAILABLE] * 2  # both tries hit lock_timeout
    assert 1.5 <= seconds < WAIT_SECONDS, seconds  # 2 x 1 s: SET LOCAL applied
    assert outbox.sent == []
    assert _status(pg_engine, request_id) == "created"
    with session_on(pg_engine) as db:  # still owed: on the resend list
        owed = pending_notifications(db, utc_now() + LOST_AFTER + LOST_AFTER)
        assert [(p.req.id, p.kind) for p in owed] == [(request_id, "created")]


def test_a_status_email_whose_row_stays_locked_is_recorded_for_resend(
        pg_engine: Engine, short_lock_timeout: list[str]) -> None:
    request_id, change_id = _announced(pg_engine, "needs_info")
    outbox = FakeMailSender()
    holder = _hold_row(pg_engine, request_id)
    try:
        result, seconds = _timed(lambda: notify_status(
            lambda: session_on(pg_engine), request_id, change_id, outbox, ACTOR))
    finally:
        holder.rollback()
        holder.close()

    assert result == "failed"
    assert short_lock_timeout == [LOCK_NOT_AVAILABLE] * 2
    assert 1.5 <= seconds < WAIT_SECONDS, seconds
    assert outbox.sent == []
    failed = _events(pg_engine, request_id, "notify_failed")
    assert len(failed) == 1 and failed[0].ref_event_id == change_id
    assert "ระบบไม่ว่าง" in failed[0].detail


# --- a rejection racing an export of the same row -------------------------------------------

def _codes_in_file(engine: Engine, batch_id: int) -> set[str]:
    """Every cell of the batch's workbook, built as the download builds it."""
    with session_on(engine) as db:
        reqs = list(db.scalars(select(ItemRequest).where(ItemRequest.export_batch_id == batch_id)))
        data = build_workbook_bytes(db, "APM", reqs)
    wb = load_workbook(io.BytesIO(data), read_only=True)
    return {str(v) for ws in wb.worksheets for row in ws.iter_rows(values_only=True)
            for v in row if v is not None}


def _export(db: Session) -> int:
    return export_pending(db, central_ids(db)[0].id, account=account_for(db, "administrator")).id


def _reject(request_id: int) -> Callable[[Session], str]:
    def run(db: Session) -> str:
        change_status(db, request_id, new_status="rejected", note="ซ้ำกับรายการเดิม",
                      account=account_for(db, "administrator"))
        return "rejected"
    return run


def _request(engine: Engine, request_id: int) -> ItemRequest:
    with session_on(engine) as db:
        return db.get(ItemRequest, request_id)


def _retired(engine: Engine, code: str) -> dict[str, str]:
    with session_on(engine) as db:
        return {r.code: r.reason for r in db.scalars(
            select(RetiredCode).where(RetiredCode.code == code))}


def test_export_first_then_the_waiting_rejection_is_refused(pg_engine: Engine) -> None:
    with session_on(pg_engine) as db:
        account_for(db, "administrator")
        r1 = _approved(db)
    code = _request(pg_engine, r1).generated_code

    with Race(pg_engine) as race:  # the rejection waits on the row the export holds
        batch_id, outcome = race.run(_export, _reject(r1))

    assert isinstance(outcome, RequestError), outcome
    req = _request(pg_engine, r1)
    # In the file, so exported, not rejected.
    assert (req.status, req.export_batch_id, req.generated_code) == ("exported", batch_id, code)
    assert code in _codes_in_file(pg_engine, batch_id)
    assert _retired(pg_engine, code) == {}


def test_rejection_first_then_the_waiting_export_leaves_it_out(pg_engine: Engine) -> None:
    with session_on(pg_engine) as db:
        account_for(db, "administrator")
        r1, r2 = _approved(db), _approved(db)  # r2 so the export has something to take
    code1 = _request(pg_engine, r1).generated_code
    code2 = _request(pg_engine, r2).generated_code

    with Race(pg_engine) as race:  # the export waits on the row the rejection holds
        rejected, batch_id = race.run(_reject(r1), _export)

    assert rejected == "rejected"
    assert isinstance(batch_id, int), batch_id
    req1 = _request(pg_engine, r1)
    # Rejected, so not in the file.
    assert (req1.status, req1.export_batch_id) == ("rejected", None)
    in_file = _codes_in_file(pg_engine, batch_id)
    assert code1 not in in_file and code2 in in_file
    assert _retired(pg_engine, code1) == {code1: "rejected"}
    assert _request(pg_engine, r2).export_batch_id == batch_id
