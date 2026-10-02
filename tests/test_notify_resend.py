"""STORY-002 ticket 06: resend what was not sent, from the Export page and the queue."""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import sessionmaker

from app.models import ItemRequest, RequestEvent
from app.services.clock import utc_now
from app.services.exporter import export_pending
from app.services.notify import (
    LOST_AFTER,
    NOT_SENT_YET,
    latest_status_event,
    notify_status,
    pending_notifications,
)
from app.services.requests import change_status, submit_request
from tests.conftest import FakeMailSender, account_for, central_ids


def _submitted(db, account=None):
    factory, system, group, sub = central_ids(db)
    return submit_request(db, account or account_for(db, "requester", plant="APM"),
                          factory_id=factory.id, code_system_id=system.id, group_id=group.id,
                          subgroup_id=sub.id, item_name="Ball Bearing", uom="EA")


def _exported(db, accounts):
    """One request per account, approved and in one export batch; returns (reqs, batch id)."""
    admin = account_for(db, "administrator")
    reqs = [change_status(db, _submitted(db, a).id, new_status="approved", account=admin)
            for a in accounts]
    batch = export_pending(db, central_ids(db)[0].id, account=account_for(db))
    return reqs, batch.id


def _status(db, req) -> str:
    db.expire_all()
    return db.get(ItemRequest, req.id).status


def _change(db, req, status, note=None):
    change_status(db, req.id, new_status=status, note=note,
                  account=account_for(db, "administrator"))
    return latest_status_event(db, req.id)


def _factory(db):
    return sessionmaker(bind=db.get_bind(), expire_on_commit=False)


def _failed_change(db, req, status, reason="Graph: 503"):
    """A needs_info/rejected change whose email failed."""
    change = _change(db, req, status, "?")
    outbox = FakeMailSender()
    outbox.fail_with = reason
    assert notify_status(_factory(db), req.id, change.id, outbox, "a@test.local") == "failed"
    return change


def _age(db, event, by=LOST_AFTER + timedelta(minutes=1)):
    db.execute(update(RequestEvent).where(RequestEvent.id == event.id)
               .values(at=utc_now() - by))
    db.commit()


# --- 'created' left over (AC1) -------------------------------------------------------------------

def test_a_failed_created_email_is_listed_then_resent_from_the_queue(client, app_db, mail_outbox):
    [req], batch = _exported(app_db, [account_for(app_db, "requester", plant="APM")])
    mail_outbox.fail_with = "Graph: 503"
    client.post(f"/exports/{batch}/mark-created")
    assert mail_outbox.sent == [] and _status(app_db, req) == "created"

    page = client.get("/exports").text
    assert "อีเมลที่ยังไม่ได้ส่ง (1)" in page and f'href="/queue/{req.id}"' in page
    assert "created: Graph: 503" in page and "requester-apm@test.local" in page
    detail = client.get(f"/queue/{req.id}").text
    assert "ส่งอีเมลอีกครั้ง" in detail and "created: Graph: 503" in detail

    mail_outbox.fail_with = None
    r = client.post(f"/queue/{req.id}/notification/resend")
    assert "ส่งอีเมลแล้ว" in r.text and "ส่งอีเมลอีกครั้ง" not in r.text
    assert len(mail_outbox.sent) == 1 and req.generated_code in mail_outbox.sent[0].subject
    assert _status(app_db, req) == "notified"
    assert "อีเมลที่ยังไม่ได้ส่ง" not in client.get("/exports").text


def test_the_list_holds_exactly_the_requests_still_created(client, app_db, mail_outbox):
    a = account_for(app_db, "requester", plant="APM")
    (stuck, done), batch = _exported(app_db, [a, account_for(app_db)])
    client.post(f"/exports/{batch}/mark-created")
    app_db.execute(update(ItemRequest).where(ItemRequest.id == stuck.id).values(status="created"))
    app_db.commit()  # as if the server restarted before stuck's email went out
    other = _submitted(app_db)  # still submitted: owes nothing
    pending = pending_notifications(app_db, utc_now())
    assert [(p.req.id, p.kind, p.reason) for p in pending] == [(stuck.id, "created", NOT_SENT_YET)]
    page = client.get("/exports").text
    assert f'href="/queue/{stuck.id}"' in page and f'href="/queue/{done.id}"' not in page
    assert f'href="/queue/{other.id}"' not in page and NOT_SENT_YET in page


def test_a_failure_before_the_created_change_is_not_its_reason(client, app_db, mail_outbox):
    a = account_for(app_db, "requester", plant="APM")
    req = _submitted(app_db, a)
    _failed_change(app_db, req, "needs_info", "Graph: 503")  # an older round's failure
    admin = account_for(app_db, "administrator")
    change_status(app_db, req.id, new_status="submitted", account=admin)
    change_status(app_db, req.id, new_status="approved", account=admin)
    batch = export_pending(app_db, central_ids(app_db)[0].id, account=account_for(app_db))
    client.post(f"/exports/{batch.id}/mark-created")
    app_db.execute(update(ItemRequest).where(ItemRequest.id == req.id).values(status="created"))
    app_db.commit()  # lost before its email went out
    [p] = pending_notifications(app_db, utc_now())
    assert p.kind == "created" and p.reason == NOT_SENT_YET


def test_send_all_groups_created_emails_per_recipient(client, app_db, mail_outbox):
    a = account_for(app_db, "requester", plant="APM")
    b = account_for(app_db)
    reqs, batch = _exported(app_db, [a, a, b])
    mail_outbox.fail_with = "Graph: 503"
    client.post(f"/exports/{batch}/mark-created")
    mail_outbox.fail_with = None

    r = client.post("/exports/notifications/resend")
    assert "กำลังส่ง 3 รายการ" in r.text
    assert sorted(m.to[0] for m in mail_outbox.sent) == sorted([a.email, b.email])
    assert "2 รายการ" in next(m for m in mail_outbox.sent if m.to == [a.email]).subject
    assert all(_status(app_db, x) == "notified" for x in reqs)


# --- needs_info / rejected changes ---------------------------------------------------------------

def test_a_failed_change_is_listed_with_its_reason_and_resent(client, app_db, mail_outbox):
    req = _submitted(app_db)
    change = _failed_change(app_db, req, "rejected", "Graph: 429")
    [p] = pending_notifications(app_db, utc_now())
    assert (p.req.id, p.kind, p.event_id, p.reason) == (req.id, "rejected", change.id,
                                                        "rejected: Graph: 429")
    assert "rejected: Graph: 429" in client.get("/exports").text

    r = client.post("/exports/notifications/resend")
    assert "กำลังส่ง 1 รายการ" in r.text
    [mail] = mail_outbox.sent
    assert f"คำขอ #{req.id} ไม่อนุมัติ" in mail.subject
    notified = app_db.scalar(select(RequestEvent).where(
        RequestEvent.request_id == req.id, RequestEvent.action == "notified"))
    assert notified.ref_event_id == change.id
    assert pending_notifications(app_db, utc_now()) == []


def test_a_lost_change_is_listed_only_after_the_grace_time(app_db):
    req = _submitted(app_db)
    change = _change(app_db, req, "needs_info", "?")  # no notified, no notify_failed
    assert pending_notifications(app_db, utc_now()) == []  # probably still sending
    _age(app_db, change)
    [p] = pending_notifications(app_db, utc_now())
    assert p.event_id == change.id and p.reason == NOT_SENT_YET


def test_a_stale_change_is_neither_listed_nor_resent(client, app_db, mail_outbox):
    answered = _submitted(app_db)
    _failed_change(app_db, answered, "needs_info")
    _change(app_db, answered, "submitted")  # the requester answered: E is no longer current
    superseded = _submitted(app_db)
    _failed_change(app_db, superseded, "needs_info")
    _change(app_db, superseded, "submitted")
    _change(app_db, superseded, "needs_info", "รอบสอง")  # same status again, newer change
    notify_status(_factory(app_db), superseded.id,
                  latest_status_event(app_db, superseded.id).id, FakeMailSender(), "a@test.local")

    moved = _submitted(app_db)
    _failed_change(app_db, moved, "rejected")
    app_db.execute(update(ItemRequest).where(ItemRequest.id == moved.id)
                   .values(status="submitted"))  # left E's status without a status event
    app_db.commit()

    assert pending_notifications(app_db, utc_now()) == []
    page = client.get("/exports").text
    assert "อีเมลที่ยังไม่ได้ส่ง" not in page
    assert "ไม่มีอีเมลค้าง" in client.post("/exports/notifications/resend").text
    r = client.post(f"/queue/{answered.id}/notification/resend")
    assert "ไม่มีอีเมลค้างสำหรับคำขอนี้" in r.text
    assert mail_outbox.sent == []


def test_the_latest_failure_reason_is_shown(client, app_db):
    req = _submitted(app_db)
    change = _failed_change(app_db, req, "needs_info", "Graph: 503")
    outbox = FakeMailSender()
    outbox.fail_with = "Graph: 429"
    notify_status(_factory(app_db), req.id, change.id, outbox, "a@test.local")
    [p] = pending_notifications(app_db, utc_now())
    assert p.reason == "needs_info: Graph: 429"
    detail = client.get(f"/queue/{req.id}").text
    assert "needs_info: Graph: 429" in detail and "Graph: 503</p>" not in detail


def test_a_failed_resend_says_why_and_stays_listed(client, app_db, mail_outbox):
    req = _submitted(app_db)
    _failed_change(app_db, req, "needs_info")
    mail_outbox.fail_with = "Graph: 401 token"
    r = client.post(f"/queue/{req.id}/notification/resend")
    assert "ส่งไม่สำเร็จ: needs_info: Graph: 401 token" in r.text and "ส่งอีเมลอีกครั้ง" in r.text
    assert len(pending_notifications(app_db, utc_now())) == 1


# --- Once (AC8) and who may press (AC11) ---------------------------------------------------------

def test_pressing_resend_twice_sends_one_email(client, app_db, mail_outbox):
    req = _submitted(app_db)
    _failed_change(app_db, req, "needs_info")
    client.post(f"/queue/{req.id}/notification/resend")
    second = client.post(f"/queue/{req.id}/notification/resend")
    assert "ไม่มีอีเมลค้าง" in second.text
    client.post("/exports/notifications/resend")
    assert len(mail_outbox.sent) == 1


def test_requesters_get_403_on_both_buttons(client_as, app_db, mail_outbox):
    req = _submitted(app_db)
    _failed_change(app_db, req, "rejected")
    requester = client_as("requester", plant="APM")
    assert requester.post(f"/queue/{req.id}/notification/resend").status_code == 403
    assert requester.post("/exports/notifications/resend").status_code == 403
    assert mail_outbox.sent == []


# --- Menu counter --------------------------------------------------------------------------------

def test_the_menu_shows_the_count_to_procurement_only(client_as, app_db):
    procurement = client_as("procurement")
    requester = client_as("requester", plant="APM")
    assert ">Export</a>" in procurement.get("/queue").text  # nothing owed: no counter
    for _ in range(2):
        _failed_change(app_db, _submitted(app_db), "rejected")
    assert "Export (อีเมลค้าง 2)</a>" in procurement.get("/queue").text
    page = requester.get("/my-requests").text
    assert "อีเมลค้าง" not in page and "/exports" not in page


# --- End to end over HTTP on a file database ------------------------------------------------------

def test_end_to_end_resend_on_a_file_database(tmp_path, seeded_template):
    """Request sessions and background sessions on separate real connections,
    as in production: fail, list, resend twice, one email."""
    from app.database import get_db, get_session_factory
    from app.main import app
    from app.services.auth import create_account
    from app.services.mail import get_mail_sender
    from tests.conftest import TEST_PASSWORD, login

    engine = create_engine(f"sqlite:///{(tmp_path / 'resend.db').as_posix()}",
                           connect_args={"check_same_thread": False, "timeout": 30})
    src, dst = seeded_template.raw_connection(), engine.raw_connection()
    try:
        src.driver_connection.backup(dst.driver_connection)
    finally:
        src.close()
        dst.close()
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        [req], batch = _exported(db, [account_for(db, "requester", plant="APM")])
        create_account(db, "buyer@test.local", "Buyer", "procurement", TEST_PASSWORD,
                       must_change_password=False)
        request_id = req.id

    def _db():
        with factory() as session:
            yield session

    outbox = FakeMailSender()
    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_session_factory] = lambda: factory
    app.dependency_overrides[get_mail_sender] = lambda: outbox
    try:
        with TestClient(app) as c:
            assert login(c, "buyer@test.local").status_code == 303
            outbox.fail_with = "Graph: 503"
            c.post(f"/exports/{batch}/mark-created")
            page = c.get("/exports").text
            assert f'href="/queue/{request_id}"' in page and "created: Graph: 503" in page
            assert "Export (อีเมลค้าง 1)" in page

            outbox.fail_with = None
            assert "กำลังส่ง 1 รายการ" in c.post("/exports/notifications/resend").text
            assert "ไม่มีอีเมลค้าง" in c.post("/exports/notifications/resend").text
            assert len(outbox.sent) == 1
            page = c.get("/exports").text
            assert "อีเมลที่ยังไม่ได้ส่ง" not in page and "อีเมลค้าง" not in page
        with factory() as db:
            assert db.get(ItemRequest, request_id).status == "notified"
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


# --- Code review fixes ----------------------------------------------------------------------------

def test_a_busy_resend_says_try_again_not_status_changed(client, app_db, mail_outbox, monkeypatch):
    import app.services.notify as notify
    from sqlalchemy.exc import OperationalError

    [req], batch = _exported(app_db, [account_for(app_db, "requester", plant="APM")])
    mail_outbox.fail_with = "Graph: 503"
    client.post(f"/exports/{batch}/mark-created")
    mail_outbox.fail_with = None

    def busy(db, request_id, status):
        raise OperationalError("UPDATE", {}, Exception("database is locked"))

    monkeypatch.setattr(notify, "_claim", busy)
    r = client.post(f"/queue/{req.id}/notification/resend")
    assert "ระบบไม่ว่าง" in r.text and "สถานะคำขอเปลี่ยนไปแล้ว" not in r.text
    assert "ส่งอีเมลอีกครั้ง" in r.text and mail_outbox.sent == []


def _render_base(account, **state):
    from types import SimpleNamespace

    from app.templating import templates

    request = SimpleNamespace(state=SimpleNamespace(account=account, **state))
    return templates.env.get_template("base.html").render(request=request)


def test_the_template_reads_the_count_and_never_queries(app_db):
    from sqlalchemy import event

    procurement = account_for(app_db)
    _failed_change(app_db, _submitted(app_db), "rejected")  # one email is owed
    statements: list[str] = []

    def _record(conn, cursor, statement, *args):
        statements.append(statement)

    engine = app_db.get_bind()
    event.listen(engine, "before_cursor_execute", _record)
    try:
        with_count = _render_base(procurement, pending_mail_count=1)
        without = _render_base(procurement)  # e.g. 403 or login: nothing counted
    finally:
        event.remove(engine, "before_cursor_execute", _record)
    assert statements == []
    assert "Export (อีเมลค้าง 1)</a>" in with_count
    assert ">Export</a>" in without and "อีเมลค้าง" not in without


def test_fragments_and_requesters_are_not_counted(client_as, app_db, monkeypatch):
    import app.services.notify as notify

    _failed_change(app_db, _submitted(app_db), "rejected")
    procurement = client_as("procurement")
    requester = client_as("requester", plant="APM")
    real, calls = notify.pending_notifications, []

    def spy(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(notify, "pending_notifications", spy)
    requester.get("/my-requests")
    procurement.get("/my-requests", headers={"HX-Request": "true"})
    assert calls == []
    assert "Export (อีเมลค้าง 1)</a>" in procurement.get("/my-requests").text
    assert calls == [1]


def test_the_forbidden_page_shows_the_menu_without_error(client_as, app_db):
    _failed_change(app_db, _submitted(app_db), "rejected")
    r = client_as("procurement").get("/admin/snapshots")
    assert r.status_code == 403 and "Export (อีเมลค้าง 1)</a>" in r.text
