"""STORY-002 ticket 01: the "created in AX" email, end to end."""

import logging
import threading
import time

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.models import Account, ItemRequest, RequestEvent
from app.services.exporter import export_pending
from app.services.mail import LogMailSender, MailMessage, get_mail_sender
from app.services.notify import notify_created
from app.services.requests import change_status, submit_request
from tests.conftest import FakeMailSender, account_for, central_ids


def _exported(db, requester=None):
    """An approved and exported request; returns (request, batch id)."""
    factory, system, group, sub = central_ids(db)
    requester = requester or account_for(db, "requester", plant="APM")
    req = submit_request(db, requester, factory_id=factory.id, code_system_id=system.id,
                         group_id=group.id, subgroup_id=sub.id, item_name="Ball Bearing SKF 6205",
                         uom="EA")
    change_status(db, req.id, new_status="approved", account=account_for(db, "administrator"))
    batch = export_pending(db, req.factory_id, account=account_for(db))
    return req, batch.id


def _events(db, req, action):
    return list(db.scalars(select(RequestEvent).where(
        RequestEvent.request_id == req.id, RequestEvent.action == action)))


# --- Happy path ---------------------------------------------------------------------------------

def test_mark_created_emails_the_requester_and_moves_to_notified(client, app_db, mail_outbox):
    req, batch_id = _exported(app_db)
    r = client.post(f"/exports/{batch_id}/mark-created")
    assert r.status_code == 200

    assert len(mail_outbox.sent) == 1
    mail = mail_outbox.sent[0]
    assert mail.to == ["requester-apm@test.local"]
    assert req.generated_code in mail.subject and "สร้างใน AX แล้ว" in mail.subject
    for body in (mail.html, mail.text):
        assert req.generated_code in body and "APM" in body and "EA" in body
        assert "ใช้รหัสนี้เปิด PR/PO ได้" in body
    app_db.expire_all()
    assert app_db.get(ItemRequest, req.id).status == "notified"
    [event] = _events(app_db, req, "notified")
    assert event.actor == "administrator0@test.local"  # who marked it created


def test_code_is_prominent_in_the_html(client, app_db, mail_outbox):
    req, batch_id = _exported(app_db)
    client.post(f"/exports/{batch_id}/mark-created")
    assert f"font-size:26px" in mail_outbox.sent[0].html
    assert f">{req.generated_code}</p>" in mail_outbox.sent[0].html


def test_no_link_without_public_base_url_and_no_reply_to_by_default(client, app_db, mail_outbox,
                                                                    monkeypatch):
    monkeypatch.setattr(settings, "public_base_url", "")
    monkeypatch.setattr(settings, "mail_reply_to", "")
    _req, batch_id = _exported(app_db)
    client.post(f"/exports/{batch_id}/mark-created")
    mail = mail_outbox.sent[0]
    assert "my-requests" not in mail.html and "my-requests" not in mail.text
    assert mail.reply_to is None


def test_link_and_reply_to_when_configured(client, app_db, mail_outbox, monkeypatch):
    monkeypatch.setattr(settings, "public_base_url", "https://portal.example.com/")
    monkeypatch.setattr(settings, "mail_reply_to", "procurement@carabao.co.th")
    req, batch_id = _exported(app_db)
    client.post(f"/exports/{batch_id}/mark-created")
    mail = mail_outbox.sent[0]
    link = f"https://portal.example.com/my-requests#request-{req.id}"
    assert link in mail.html and link in mail.text and "สำหรับผู้มีบัญชีในระบบ" in mail.html
    assert mail.reply_to == "procurement@carabao.co.th"


def test_my_requests_rows_are_link_targets(client_as, app_db):
    c = client_as("requester", plant="APM")
    me = app_db.scalar(select(Account).where(Account.email == "requester0@test.local"))
    req, _ = _exported(app_db, requester=me)
    html = c.get("/my-requests").text
    assert f'id="request-{req.id}"' in html
    assert ".request-row:target" in html


# --- Failure never blocks (AC1) -------------------------------------------------------------------

def test_failed_send_keeps_created_and_records_notify_failed(client, app_db, mail_outbox):
    mail_outbox.fail_with = "Graph: 503 service unavailable"
    req, batch_id = _exported(app_db)
    r = client.post(f"/exports/{batch_id}/mark-created")
    assert r.status_code == 200  # marking created still succeeds
    app_db.expire_all()
    assert app_db.get(ItemRequest, req.id).status == "created"
    [event] = _events(app_db, req, "notify_failed")
    assert "503 service unavailable" in event.detail
    assert _events(app_db, req, "notified") == []


# --- Dedupe (AC8) -------------------------------------------------------------------------------

def test_second_notification_finds_nothing_to_do(app_db, mail_outbox):
    req, _ = _exported(app_db)
    change_status(app_db, req.id, new_status="created", account=account_for(app_db))
    factory = sessionmaker(bind=app_db.get_bind(), expire_on_commit=False)
    first = notify_created(factory, [req.id], mail_outbox, "a@test.local")
    second = notify_created(factory, [req.id], mail_outbox, "a@test.local")
    assert first == {"sent": 1, "failed": 0, "skipped": 0}
    assert second == {"sent": 0, "failed": 0, "skipped": 1}
    assert len(mail_outbox.sent) == 1


def test_only_created_requests_are_emailed(app_db, mail_outbox):
    req, _ = _exported(app_db)  # still 'exported'
    factory = sessionmaker(bind=app_db.get_bind(), expire_on_commit=False)
    assert notify_created(factory, [req.id], mail_outbox, "a@test.local")["skipped"] == 1
    assert mail_outbox.sent == []


def test_two_concurrent_sends_deliver_one_email(tmp_path, seeded_template):
    # A real race: two threads, two connections, one file database. The claim
    # (an UPDATE that only matches a still-'created' row) takes SQLite's write
    # lock and holds it through the send, so the second thread waits and then
    # finds the request already notified.
    url = f"sqlite:///{(tmp_path / 'race.db').as_posix()}"
    engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30})
    src, dst = seeded_template.raw_connection(), engine.raw_connection()
    try:
        src.driver_connection.backup(dst.driver_connection)
    finally:
        src.close()
        dst.close()
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        f, system, group, sub = central_ids(db)
        req = ItemRequest(requester_name="R", requester_email="r@test.local", factory_id=f.id,
                          code_system_id=system.id, group_id=group.id, subgroup_id=sub.id,
                          item_name="X", status="created", generated_code="90001000999")
        db.add(req)
        db.commit()
        request_id = req.id

    class SlowSender(FakeMailSender):
        def send(self, message: MailMessage) -> None:
            time.sleep(0.4)  # widen the window in which both threads are inside
            super().send(message)

    sender, results = SlowSender(), []
    start = threading.Barrier(2)

    def worker():
        start.wait()
        results.append(notify_created(factory, [request_id], sender, "a@test.local"))

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    try:
        assert len(sender.sent) == 1
        assert sorted(r["sent"] for r in results) == [0, 1]
        with factory() as db:
            assert db.get(ItemRequest, request_id).status == "notified"
            assert len(list(db.scalars(select(RequestEvent).where(
                RequestEvent.action == "notified")))) == 1
    finally:
        engine.dispose()


# --- Dev mode (AC2) -----------------------------------------------------------------------------

def test_without_mail_settings_the_log_sender_is_used():
    assert isinstance(get_mail_sender(), LogMailSender)


def test_log_sender_logs_recipients_and_subject_but_not_the_body(caplog):
    caplog.set_level(logging.INFO, logger="app.mail")
    LogMailSender().send(MailMessage(to=["a@carabao.co.th"], cc=["b@carabao.co.th"],
                                     subject="[Item Portal] รหัส 90001000001",
                                     html="<p>SECRET-BODY</p>", text="SECRET-BODY"))
    assert "a@carabao.co.th" in caplog.text and "b@carabao.co.th" in caplog.text
    assert "90001000001" in caplog.text and "SECRET-BODY" not in caplog.text



# --- Code review fixes ----------------------------------------------------------------------------

def _created(db, n=1):
    reqs = []
    for _ in range(n):
        req, _ = _exported(db)
        change_status(db, req.id, new_status="created", account=account_for(db))
        reqs.append(req)
    return reqs


def test_one_requests_unexpected_error_does_not_stop_the_others(app_db, monkeypatch):
    import app.services.notify as notify

    first, second, third = _created(app_db, 3)
    real = notify.build_created_email

    def flaky(req):
        if req.id == second.id:
            raise RuntimeError("template broke")
        return real(req)

    monkeypatch.setattr(notify, "build_created_email", flaky)
    outbox = FakeMailSender()
    factory = sessionmaker(bind=app_db.get_bind(), expire_on_commit=False)
    counts = notify_created(factory, [first.id, second.id, third.id], outbox, "a@test.local")
    assert counts == {"sent": 2, "failed": 1, "skipped": 0}
    app_db.expire_all()
    assert [app_db.get(ItemRequest, r.id).status for r in (first, second, third)] == [
        "notified", "created", "notified"]
    [failed] = _events(app_db, second, "notify_failed")
    assert "template broke" in failed.detail


def test_sent_but_not_recorded_is_named_as_a_possible_duplicate(app_db):
    [req] = _created(app_db)
    outbox = FakeMailSender()
    inner = sessionmaker(bind=app_db.get_bind(), expire_on_commit=False)
    commits = {"n": 0}

    def factory():
        s = inner()
        real_commit = s.commit

        def commit():
            commits["n"] += 1
            if commits["n"] == 1:  # the commit right after a successful send
                raise RuntimeError("db went away")
            real_commit()

        s.commit = commit
        return s

    counts = notify_created(factory, [req.id], outbox, "a@test.local")
    assert counts["failed"] == 1 and len(outbox.sent) == 1
    [failed] = _events(app_db, req, "notify_failed")
    assert "ส่งอีเมลแล้วแต่บันทึกผลไม่สำเร็จ" in failed.detail and "ได้ซ้ำ" in failed.detail


def test_mark_created_emails_the_ones_it_moved_even_if_a_later_one_fails(client, app_db,
                                                                       mail_outbox, monkeypatch):
    import app.routes.exports as exports
    from app.services.requests import RequestError

    first, batch_id = _exported(app_db)
    second, _ = _exported(app_db)
    second.export_batch_id = batch_id
    app_db.commit()
    real = exports.change_status

    def fail_on_second(db, request_id, **kw):
        if request_id == second.id:
            raise RequestError("ชนกับการกดพร้อมกัน")
        return real(db, request_id, **kw)

    monkeypatch.setattr(exports, "change_status", fail_on_second)
    r = client.post(f"/exports/{batch_id}/mark-created")
    assert r.status_code == 422
    assert [m.to for m in mail_outbox.sent] == [["requester-apm@test.local"]]
    app_db.expire_all()
    assert app_db.get(ItemRequest, first.id).status == "notified"


def test_plain_text_is_not_html_escaped(app_db):
    from app.services.notify import build_created_email

    [req] = _created(app_db)
    req.item_name = 'ORING & SEAL "NBR" <70>'
    mail = build_created_email(req)
    assert 'ORING & SEAL "NBR" <70>' in mail.text
    assert "&amp;" in mail.html  # the HTML part stays escaped


def test_busy_lock_is_skipped_not_crashed(app_db, monkeypatch):
    import app.services.notify as notify
    from sqlalchemy.exc import OperationalError

    [req] = _created(app_db)

    def busy(db, request_id, status):
        raise OperationalError("UPDATE", {}, Exception("database is locked"))

    monkeypatch.setattr(notify, "_claim", busy)
    factory = sessionmaker(bind=app_db.get_bind(), expire_on_commit=False)
    assert notify_created(factory, [req.id], FakeMailSender(), "a@test.local") == {
        "sent": 0, "failed": 0, "skipped": 1}
    app_db.expire_all()
    assert app_db.get(ItemRequest, req.id).status == "created"
