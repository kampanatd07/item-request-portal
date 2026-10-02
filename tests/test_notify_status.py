"""STORY-002 ticket 04: needs_info and rejected emails, once per status change."""

import threading
import time

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models import ItemRequest, RequestEvent
from app.services.mail import MailError
from app.services.notify import latest_status_event, notify_status
from app.services.requests import change_status, submit_request
from tests.conftest import FakeMailSender, account_for, central_ids


def _submitted(db, account=None, **kw):
    factory, system, group, sub = central_ids(db)
    return submit_request(db, account or account_for(db, "requester", plant="APM"),
                          factory_id=factory.id, code_system_id=system.id, group_id=group.id,
                          subgroup_id=sub.id, item_name="Ball Bearing", **kw)


def _notified(db, req):
    return list(db.scalars(select(RequestEvent).where(
        RequestEvent.request_id == req.id, RequestEvent.action == "notified")))


def _factory(db):
    return sessionmaker(bind=db.get_bind(), expire_on_commit=False)


def _change(db, req, status, note=None, role="procurement"):
    change_status(db, req.id, new_status=status, note=note, account=account_for(db, role))
    return latest_status_event(db, req.id)


# --- What is sent (AC6) ---------------------------------------------------------------------------

def test_needs_info_emails_the_reason_and_points_at_the_change(client, app_db, mail_outbox):
    req = _submitted(app_db)
    client.post(f"/queue/{req.id}/status", data={"new_status": "needs_info",
                                                 "note": "ขอสเปค 25 mm หรือ 30 mm"})
    [mail] = mail_outbox.sent
    assert mail.to == ["requester-apm@test.local"]
    assert f"คำขอ #{req.id} ต้องการข้อมูลเพิ่ม" in mail.subject
    assert "ขอสเปค 25 mm หรือ 30 mm" in mail.html and "ขอสเปค 25 mm หรือ 30 mm" in mail.text
    app_db.expire_all()
    assert app_db.get(ItemRequest, req.id).status == "needs_info"  # no status change
    [event] = _notified(app_db, req)
    change = latest_status_event(app_db, req.id)
    assert change.action == "needs_info" and event.ref_event_id == change.id
    assert event.actor == "administrator0@test.local"


def test_rejected_before_a_code_gives_the_reason(client, app_db, mail_outbox):
    req = _submitted(app_db)
    client.post(f"/queue/{req.id}/status", data={"new_status": "rejected", "note": "ซ้ำกับ 90001000001"})
    [mail] = mail_outbox.sent
    assert f"คำขอ #{req.id} ไม่อนุมัติ" in mail.subject
    assert "ซ้ำกับ 90001000001" in mail.text and "ยกเลิกแล้ว" not in mail.text


def test_rejected_after_approval_says_the_code_must_not_be_used(client, app_db, mail_outbox):
    req = _submitted(app_db)
    _change(app_db, req, "approved", role="administrator")
    client.post(f"/queue/{req.id}/status", data={"new_status": "rejected", "note": "ผิด Group"})
    [mail] = mail_outbox.sent
    assert req.generated_code in mail.subject and "ยกเลิกแล้ว ห้ามใช้" in mail.subject
    assert f"<s>{req.generated_code}</s> ยกเลิกแล้ว ห้ามใช้" in mail.html
    assert f"รหัส {req.generated_code} ยกเลิกแล้ว ห้ามใช้" in mail.text and "ผิด Group" in mail.text


def test_no_email_on_approved_or_in_review(client, app_db, mail_outbox):
    req = _submitted(app_db)
    client.post(f"/queue/{req.id}/status", data={"new_status": "in_review"})
    client.post(f"/queue/{req.id}/status", data={"new_status": "approved"})
    assert mail_outbox.sent == []


def test_originator_gets_it_with_the_submitter_copied(client, app_db, mail_outbox):
    req = _submitted(app_db, account_for(app_db), on_behalf_of="คำรณ",
                     originator_email="kamron@carabao.co.th")
    client.post(f"/queue/{req.id}/status", data={"new_status": "needs_info", "note": "?"})
    [mail] = mail_outbox.sent
    assert mail.to == ["kamron@carabao.co.th"] and mail.cc == ["procurement-any@test.local"]
    assert "เรียน คำรณ" in mail.text


# --- Once per change (AC8) -------------------------------------------------------------------------

def test_the_same_change_is_announced_once(app_db):
    req = _submitted(app_db)
    change = _change(app_db, req, "needs_info", "?")
    outbox = FakeMailSender()
    assert notify_status(_factory(app_db), req.id, change.id, outbox, "a@test.local") == "sent"
    assert notify_status(_factory(app_db), req.id, change.id, outbox, "a@test.local") == "skipped"
    assert len(outbox.sent) == 1


def test_a_stale_change_is_skipped_quietly(app_db):
    req = _submitted(app_db)
    change = _change(app_db, req, "needs_info", "?")
    _change(app_db, req, "submitted")  # requester answered before the email went out
    outbox = FakeMailSender()
    assert notify_status(_factory(app_db), req.id, change.id, outbox, "a@test.local") == "skipped"
    assert outbox.sent == []
    assert list(app_db.scalars(select(RequestEvent).where(
        RequestEvent.request_id == req.id, RequestEvent.action == "notify_failed"))) == []


def test_a_superseded_change_is_not_announced_but_the_new_one_is(app_db):
    req = _submitted(app_db)
    first = _change(app_db, req, "needs_info", "รอบแรก")
    _change(app_db, req, "submitted")
    second = _change(app_db, req, "needs_info", "รอบสอง")
    outbox = FakeMailSender()
    # status is needs_info again, but `first` is no longer the latest change
    assert notify_status(_factory(app_db), req.id, first.id, outbox, "a@test.local") == "skipped"
    assert notify_status(_factory(app_db), req.id, second.id, outbox, "a@test.local") == "sent"
    assert len(outbox.sent) == 1 and "รอบสอง" in outbox.sent[0].text


def test_two_needs_info_rounds_give_two_emails(client, app_db, mail_outbox):
    req = _submitted(app_db)
    client.post(f"/queue/{req.id}/status", data={"new_status": "needs_info", "note": "รอบแรก"})
    client.post(f"/queue/{req.id}/status", data={"new_status": "submitted"})
    client.post(f"/queue/{req.id}/status", data={"new_status": "needs_info", "note": "รอบสอง"})
    assert [("รอบแรก" in m.text, "รอบสอง" in m.text) for m in mail_outbox.sent] == [
        (True, False), (False, True)]
    refs = {e.ref_event_id for e in _notified(app_db, req)}
    assert len(refs) == 2


def test_an_event_of_another_request_is_refused(app_db):
    a, b = _submitted(app_db), _submitted(app_db)
    change = _change(app_db, a, "needs_info", "?")
    outbox = FakeMailSender()
    assert notify_status(_factory(app_db), b.id, change.id, outbox, "a@test.local") == "skipped"
    assert outbox.sent == []


def test_failure_records_notify_failed_pointing_at_the_change(app_db):
    req = _submitted(app_db)
    change = _change(app_db, req, "rejected", "ไม่ผ่าน")
    outbox = FakeMailSender()
    outbox.fail_with = "Graph: 503"
    assert notify_status(_factory(app_db), req.id, change.id, outbox, "a@test.local") == "failed"
    failed = app_db.scalar(select(RequestEvent).where(
        RequestEvent.request_id == req.id, RequestEvent.action == "notify_failed"))
    assert failed.ref_event_id == change.id and failed.detail == "rejected: Graph: 503"
    # a failure is not "already announced": a resend can still send it
    outbox.fail_with = None
    assert notify_status(_factory(app_db), req.id, change.id, outbox, "a@test.local") == "sent"


def test_two_concurrent_sends_of_one_change_deliver_one_email(tmp_path, seeded_template):
    url = f"sqlite:///{(tmp_path / 'race4.db').as_posix()}"
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
                          item_name="X", status="needs_info", review_note="?")
        db.add(req)
        db.flush()
        change = RequestEvent(request_id=req.id, actor="p@test.local", action="needs_info")
        db.add(change)
        db.commit()
        request_id, change_id = req.id, change.id

    class Slow(FakeMailSender):
        def send(self, message):
            time.sleep(0.4)
            super().send(message)

    sender, gate, results = Slow(), threading.Barrier(2), []

    def worker():
        gate.wait()
        results.append(notify_status(factory, request_id, change_id, sender, "a@test.local"))

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    try:
        assert len(sender.sent) == 1 and sorted(results) == ["sent", "skipped"]
    finally:
        engine.dispose()



# --- Code review fixes ----------------------------------------------------------------------------

def test_a_change_without_a_note_does_not_repeat_an_older_reason(app_db):
    req = _submitted(app_db)
    _change(app_db, req, "needs_info", "ขอสเปค 25 mm")
    _change(app_db, req, "submitted")
    second = _change(app_db, req, "needs_info")  # no note this time
    outbox = FakeMailSender()
    notify_status(_factory(app_db), req.id, second.id, outbox, "a@test.local")
    [mail] = outbox.sent
    assert "ขอสเปค 25 mm" not in mail.text and "สิ่งที่ต้องการ: -" in mail.text


def test_rejection_without_a_note_does_not_show_the_review_note(app_db):
    req = _submitted(app_db)
    _change(app_db, req, "in_review", "ราคาเช็คแล้ว")
    rejected = _change(app_db, req, "rejected")
    outbox = FakeMailSender()
    notify_status(_factory(app_db), req.id, rejected.id, outbox, "a@test.local")
    assert "ราคาเช็คแล้ว" not in outbox.sent[0].text and "เหตุผล: -" in outbox.sent[0].text


def test_busy_twice_is_recorded_so_it_can_be_resent(app_db, monkeypatch):
    import app.services.notify as notify
    from sqlalchemy.exc import OperationalError

    req = _submitted(app_db)
    change = _change(app_db, req, "needs_info", "?")

    def busy(db, request_id, status):
        raise OperationalError("UPDATE", {}, Exception("lock timeout"))

    monkeypatch.setattr(notify, "_claim", busy)
    assert notify_status(_factory(app_db), req.id, change.id, FakeMailSender(), "a@test.local") == "failed"
    failed = app_db.scalar(select(RequestEvent).where(
        RequestEvent.request_id == req.id, RequestEvent.action == "notify_failed"))
    assert failed.ref_event_id == change.id and "ระบบไม่ว่าง" in failed.detail


def test_an_error_in_the_post_claim_checks_is_recorded(app_db, monkeypatch):
    import app.services.notify as notify

    req = _submitted(app_db)
    change = _change(app_db, req, "rejected", "ไม่ผ่าน")

    def broken(db, request_id):
        raise RuntimeError("connection dropped")

    monkeypatch.setattr(notify, "latest_status_event", broken)
    assert notify_status(_factory(app_db), req.id, change.id, FakeMailSender(), "a@test.local") == "failed"
    failed = app_db.scalar(select(RequestEvent).where(
        RequestEvent.request_id == req.id, RequestEvent.action == "notify_failed"))
    assert failed.ref_event_id == change.id and "connection dropped" in failed.detail
