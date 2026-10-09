"""STORY-002 pre-merge: what happened before email existed is not owed an email.

Migration e52ce808c5d5 records an honest `notify_not_applicable` event (never a
fake `notified`) for every request still `created` and every current
needs_info/rejected change; the resend list treats it as settled.
"""

from pathlib import Path

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.models import ItemRequest, RequestEvent
from app.services.clock import utc_now
from app.services.exporter import export_pending
from app.services.notify import (
    LOST_AFTER,
    NOT_APPLICABLE,
    latest_status_event,
    notify_status,
    pending_notifications,
)
from app.services.requests import change_status, submit_request
from tests.conftest import FakeMailSender, account_for, central_ids

DETAIL = "เกิดก่อนมีระบบแจ้งเตือนทางอีเมล"


def _later():
    return utc_now() + 2 * LOST_AFTER


# --- The migration ------------------------------------------------------------------------------

# status, then the status events in order (none for a request older than the event log)
HISTORIES = {
    "created": ("created", ["submitted", "approved", "exported", "created"]),
    "created_before_events": ("created", []),
    "needs_info": ("needs_info", ["submitted", "needs_info"]),
    "rejected_after_approval": ("rejected", ["submitted", "approved", "rejected"]),
    "needs_info_superseded": ("in_review", ["submitted", "needs_info", "in_review"]),
    "notified": ("notified", ["submitted", "approved", "exported", "created"]),
    "submitted": ("submitted", ["submitted"]),
}


def _closing_events(engine) -> dict[int, list[tuple]]:
    with engine.connect() as c:
        rows = c.execute(text(
            "SELECT request_id, actor, detail, ref_event_id FROM request_events "
            "WHERE action = :a ORDER BY id"), {"a": NOT_APPLICABLE}).all()
    got: dict[int, list[tuple]] = {}
    for request_id, *rest in rows:
        got.setdefault(request_id, []).append(tuple(rest))
    return got


def test_migration_closes_only_what_could_be_listed(tmp_path, monkeypatch):
    from alembic import command
    from alembic.config import Config

    url = f"sqlite:///{(tmp_path / 'closing.db').as_posix()}"
    monkeypatch.setattr(settings, "database_url", url)
    cfg = Config(str(Path(__file__).resolve().parent.parent / "alembic.ini"))
    command.upgrade(cfg, "16ec6f1afac9")  # before email existed
    engine = create_engine(url)
    ids: dict[str, int] = {}
    last_event: dict[str, int] = {}
    try:
        with engine.begin() as c:
            for key, (status, actions) in HISTORIES.items():
                c.execute(text(
                    "INSERT INTO item_requests (requester_name, requester_email, factory_id, "
                    "code_system_id, group_id, item_name, status) "
                    "VALUES ('P', 'p@test.local', 1, 1, 1, 'x', :s)"), {"s": status})
                ids[key] = c.execute(text("SELECT max(id) FROM item_requests")).scalar()
                for action in actions:
                    c.execute(text(
                        "INSERT INTO request_events (request_id, actor, action, at) "
                        "VALUES (:r, 'p@test.local', :a, '2026-09-30 10:00:00')"),
                        {"r": ids[key], "a": action})
                    last_event[key] = c.execute(text("SELECT max(id) FROM request_events")).scalar()

        command.upgrade(cfg, "head")
        got = _closing_events(engine)
        with engine.connect() as c:
            statuses = dict(c.execute(text("SELECT id, status FROM item_requests")).all())
        with Session(engine) as db:
            pending = pending_notifications(db, _later())

        # Round trip: downgrade removes them, upgrade adds them once again.
        command.downgrade(cfg, "16ec6f1afac9")
        with engine.connect() as c:
            assert c.execute(text("SELECT count(*) FROM request_events WHERE action = :a"),
                             {"a": NOT_APPLICABLE}).scalar() == 0
        command.upgrade(cfg, "head")
        again = _closing_events(engine)
    finally:
        engine.dispose()

    assert got == {
        ids["created"]: [("system", DETAIL, last_event["created"])],
        ids["created_before_events"]: [("system", DETAIL, None)],  # no 'created' event to point at
        ids["needs_info"]: [("system", DETAIL, last_event["needs_info"])],
        ids["rejected_after_approval"]: [("system", DETAIL, last_event["rejected_after_approval"])],
    }
    assert again == got
    # Statuses are the truth and stay as they were: never a fake 'notified'.
    assert statuses == {ids[k]: status for k, (status, _) in HISTORIES.items()}
    assert pending == []


# --- The resend list ----------------------------------------------------------------------------

def _submitted(db):
    factory, system, group, sub = central_ids(db)
    return submit_request(db, account_for(db, "requester", plant="APM"), factory_id=factory.id,
                          code_system_id=system.id, group_id=group.id, subgroup_id=sub.id,
                          item_name="Ball Bearing", uom="EA")


def _change(db, req, status, note=None):
    change_status(db, req.id, new_status=status, note=note,
                  account=account_for(db, "administrator"))
    return latest_status_event(db, req.id)


def _close(db, req, ref):
    """What the migration writes."""
    db.add(RequestEvent(request_id=req.id, actor="system", action=NOT_APPLICABLE,
                        detail=DETAIL, ref_event_id=ref.id if ref is not None else None))
    db.commit()


def _created(db):
    req = _submitted(db)
    _change(db, req, "approved")
    export_pending(db, req.factory_id, account=account_for(db))
    return req, _change(db, req, "created")


def _listed(db) -> set[tuple[int, str]]:
    return {(p.req.id, p.kind) for p in pending_notifications(db, _later())}


def test_closed_requests_and_changes_are_not_listed(db_session):
    created, created_event = _created(db_session)
    created_old, _ = _created(db_session)
    needs_info = _submitted(db_session)
    needs_info_change = _change(db_session, needs_info, "needs_info", "ขอสเปค")
    rejected = _submitted(db_session)
    rejected_change = _change(db_session, rejected, "rejected", "ซ้ำ")
    assert _listed(db_session) == {(created.id, "created"), (created_old.id, "created"),
                                   (needs_info.id, "needs_info"), (rejected.id, "rejected")}

    _close(db_session, created, created_event)
    _close(db_session, created_old, None)  # a request older than the event log
    _close(db_session, needs_info, needs_info_change)
    _close(db_session, rejected, rejected_change)

    assert _listed(db_session) == set()


def test_a_new_change_after_the_closed_one_is_owed_an_email(db_session):
    req = _submitted(db_session)
    _close(db_session, req, _change(db_session, req, "needs_info", "ขอสเปค"))
    _change(db_session, req, "submitted")  # the requester answered (closed change superseded)
    _change(db_session, req, "needs_info", "ขอรูปด้วย")
    assert _listed(db_session) == {(req.id, "needs_info")}


def test_a_closed_change_is_never_sent(db_session):
    req = _submitted(db_session)
    change = _change(db_session, req, "rejected", "ซ้ำ")
    _close(db_session, req, change)
    outbox = FakeMailSender()
    factory = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)

    assert notify_status(factory, req.id, change.id, outbox, "a@test.local") == "skipped"
    assert outbox.sent == []
    db_session.expire_all()
    assert db_session.get(ItemRequest, req.id).status == "rejected"
    assert not db_session.scalars(select(RequestEvent).where(
        RequestEvent.request_id == req.id,
        RequestEvent.action.in_(("notified", "notify_failed")))).all()


def test_the_history_shows_it_in_thai(client, app_db):
    req, created_event = _created(app_db)
    _close(app_db, req, created_event)
    page = client.get(f"/queue/{req.id}").text
    assert "ไม่ต้องแจ้งทางอีเมล" in page and DETAIL in page
