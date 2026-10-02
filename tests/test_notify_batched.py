"""STORY-002 ticket 03: one "created" email per (To, CC) per click."""

import threading
import time

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models import ItemRequest, RequestEvent
from app.services.exporter import export_pending
from app.services.mail import MailMessage
from app.services.notify import build_created_group_email, notify_created
from app.services.requests import change_status, submit_request
from tests.conftest import FakeMailSender, account_for, central_ids


def _approved(db, account, **kw):
    factory, system, group, sub = central_ids(db)
    req = submit_request(db, account, factory_id=factory.id, code_system_id=system.id,
                         group_id=group.id, subgroup_id=sub.id, item_name="Ball Bearing",
                         uom="EA", **kw)
    return change_status(db, req.id, new_status="approved",
                         account=account_for(db, "administrator"))


def _batch(db) -> int:
    return export_pending(db, central_ids(db)[0].id, account=account_for(db)).id


def _codes(mail: MailMessage, reqs) -> set[str]:
    return {r.generated_code for r in reqs if r.generated_code in mail.html}


def _status(db, req) -> str:
    db.expire_all()
    return db.get(ItemRequest, req.id).status


def test_five_requests_two_requesters_give_two_emails(client, app_db, mail_outbox):
    a = account_for(app_db, "requester", plant="APM")
    b = account_for(app_db, "procurement")
    mine = [_approved(app_db, a) for _ in range(3)]
    theirs = [_approved(app_db, b) for _ in range(2)]
    client.post(f"/exports/{_batch(app_db)}/mark-created")

    assert len(mail_outbox.sent) == 2
    by_to = {m.to[0]: m for m in mail_outbox.sent}
    assert _codes(by_to[a.email], mine + theirs) == {r.generated_code for r in mine}
    assert _codes(by_to[b.email], mine + theirs) == {r.generated_code for r in theirs}
    assert "3 รายการ" in by_to[a.email].subject and "2 รายการ" in by_to[b.email].subject
    assert all(_status(app_db, r) == "notified" for r in mine + theirs)
    detail = app_db.scalar(select(RequestEvent.detail).where(
        RequestEvent.request_id == mine[0].id, RequestEvent.action == "notified"))
    assert "ฉบับรวม 3 รายการ" in detail


def test_own_requests_and_ones_submitted_for_me_are_separate_emails(client, app_db, mail_outbox):
    # The same person asked twice herself (no CC) and once through Procurement
    # (CC Procurement): two emails, Procurement is copied only on its own item.
    from app.services.auth import create_account

    plant = central_ids(app_db, "APM")[0].id
    me = create_account(app_db, "somying@carabao.co.th", "สมหญิง", "requester", "a-long-password-1",
                        factory_id=plant, must_change_password=False)
    procurement = account_for(app_db, "procurement")
    own = [_approved(app_db, me), _approved(app_db, me)]
    for_me = _approved(app_db, procurement, on_behalf_of="สมหญิง",
                       originator_email="somying@carabao.co.th")
    client.post(f"/exports/{_batch(app_db)}/mark-created")

    assert len(mail_outbox.sent) == 2
    by_cc = {tuple(m.cc): m for m in mail_outbox.sent}
    assert set(by_cc) == {(), (procurement.email,)}
    assert by_cc[()].to == [me.email] and by_cc[(procurement.email,)].to == [me.email]
    assert _codes(by_cc[()], own + [for_me]) == {r.generated_code for r in own}
    assert _codes(by_cc[(procurement.email,)], own + [for_me]) == {for_me.generated_code}


def test_one_failing_group_leaves_only_its_requests_created(client, app_db, mail_outbox):
    a = account_for(app_db, "requester", plant="APM")
    b = account_for(app_db, "procurement")
    ok = _approved(app_db, a)
    bad = [_approved(app_db, b), _approved(app_db, b)]

    class FailFor(FakeMailSender):
        def send(self, message):
            if message.to == [b.email]:
                from app.services.mail import MailError
                raise MailError("Graph: 503")
            super().send(message)

    sender = FailFor()
    factory = sessionmaker(bind=app_db.get_bind(), expire_on_commit=False)
    _batch(app_db)
    for r in [ok] + bad:
        change_status(app_db, r.id, new_status="created", account=account_for(app_db))
    counts = notify_created(factory, [ok.id] + [r.id for r in bad], sender, "a@test.local")
    assert counts == {"sent": 1, "failed": 2, "skipped": 0}
    assert _status(app_db, ok) == "notified"
    assert [_status(app_db, r) for r in bad] == ["created", "created"]
    for r in bad:
        assert app_db.scalar(select(RequestEvent.detail).where(
            RequestEvent.request_id == r.id, RequestEvent.action == "notify_failed")) == \
            "created: Graph: 503"


def test_originator_group_is_to_the_originator_cc_the_submitters(client, app_db, mail_outbox):
    p1 = account_for(app_db, "procurement")
    p2 = account_for(app_db, "administrator")
    r1 = _approved(app_db, p1, on_behalf_of="คำรณ", originator_email="kamron@carabao.co.th")
    r2 = _approved(app_db, p1, on_behalf_of="คำรณ", originator_email="kamron@carabao.co.th")
    r3 = _approved(app_db, p2, on_behalf_of="คำรณ", originator_email="kamron@carabao.co.th")
    client.post(f"/exports/{_batch(app_db)}/mark-created")
    by_cc = {tuple(m.cc): m for m in mail_outbox.sent}
    # (To, CC) grouping: each submitter is copied only on what they submitted
    assert set(by_cc) == {(p1.email,), (p2.email,)}
    assert _codes(by_cc[(p1.email,)], [r1, r2, r3]) == {r1.generated_code, r2.generated_code}
    assert _codes(by_cc[(p2.email,)], [r1, r2, r3]) == {r3.generated_code}
    assert all(m.to == ["kamron@carabao.co.th"] for m in mail_outbox.sent)


def test_rerunning_the_click_sends_nothing_more(client, app_db, mail_outbox):
    a = account_for(app_db, "requester", plant="APM")
    reqs = [_approved(app_db, a) for _ in range(2)]
    batch_id = _batch(app_db)
    client.post(f"/exports/{batch_id}/mark-created")
    factory = sessionmaker(bind=app_db.get_bind(), expire_on_commit=False)
    assert notify_created(factory, [r.id for r in reqs], mail_outbox, "a@test.local") == {
        "sent": 0, "failed": 0, "skipped": 2}
    assert len(mail_outbox.sent) == 1


def test_subject_lists_three_codes_then_an_ellipsis(app_db):
    a = account_for(app_db, "requester", plant="APM")
    reqs = [_approved(app_db, a) for _ in range(5)]
    subject = build_created_group_email(reqs).subject
    assert "5 รายการ" in subject
    assert ", ".join(r.generated_code for r in reqs[:3]) + ", …" in subject
    assert reqs[3].generated_code not in subject
    assert build_created_group_email(reqs[:3]).subject.endswith(
        ", ".join(r.generated_code for r in reqs[:3]) + ")")


def test_greeting_names_the_person_or_says_requester_when_names_differ(app_db):
    p = account_for(app_db, "procurement")
    same = [_approved(app_db, p, on_behalf_of="คำรณ ใจดี", originator_email="k@carabao.co.th")
            for _ in range(2)]
    assert "เรียน คำรณ ใจดี" in build_created_group_email(same).text
    other = _approved(app_db, p, on_behalf_of="คำรณ", originator_email="k@carabao.co.th")
    assert "เรียน ผู้ขอ" in build_created_group_email(same + [other]).text


def test_overlapping_concurrent_clicks_send_each_code_once(tmp_path, seeded_template):
    # Two threads, two connections, one file DB; their request sets overlap.
    url = f"sqlite:///{(tmp_path / 'race3.db').as_posix()}"
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
        ids = []
        for n in range(4):
            r = ItemRequest(requester_name="R", requester_email="r@test.local", factory_id=f.id,
                            code_system_id=system.id, group_id=group.id, subgroup_id=sub.id,
                            item_name=f"X{n}", status="created", generated_code=f"9000100{900 + n:04d}")
            db.add(r)
            db.flush()
            ids.append(r.id)
        db.commit()

    class Slow(FakeMailSender):
        def send(self, message):
            time.sleep(0.3)
            super().send(message)

    sender, gate = Slow(), threading.Barrier(2)

    def click(subset):
        gate.wait()
        notify_created(factory, subset, sender, "a@test.local")

    threads = [threading.Thread(target=click, args=(ids[:3],)),
               threading.Thread(target=click, args=(ids[1:],))]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    try:
        codes = [f"9000100{900 + n:04d}" for n in range(4)]
        sent_codes = [c for m in sender.sent for c in codes if c in m.html]
        assert sorted(sent_codes) == sorted(codes)  # every code exactly once
        with factory() as db:
            assert {db.get(ItemRequest, i).status for i in ids} == {"notified"}
    finally:
        engine.dispose()



# --- Code review fixes ----------------------------------------------------------------------------

def test_a_request_whose_recipients_break_does_not_stop_the_click(app_db, monkeypatch):
    import app.services.notify as notify

    a = account_for(app_db, "requester", plant="APM")
    good = _approved(app_db, a)
    bad = _approved(app_db, account_for(app_db, "procurement"))
    _batch(app_db)
    for r in (good, bad):
        change_status(app_db, r.id, new_status="created", account=account_for(app_db))
    real = notify.group_key

    def broken(req):
        if req.id == bad.id:
            raise IndexError("malformed originator email")
        return real(req)

    monkeypatch.setattr(notify, "group_key", broken)
    outbox = FakeMailSender()
    factory = sessionmaker(bind=app_db.get_bind(), expire_on_commit=False)
    counts = notify_created(factory, [good.id, bad.id], outbox, "a@test.local")
    assert counts == {"sent": 1, "failed": 1, "skipped": 0}
    assert _status(app_db, good) == "notified" and _status(app_db, bad) == "created"
    detail = app_db.scalar(select(RequestEvent.detail).where(
        RequestEvent.request_id == bad.id, RequestEvent.action == "notify_failed"))
    assert "หาผู้รับไม่ได้" in detail and "malformed originator email" in detail


def test_commit_failure_keeps_each_parts_real_reason(app_db, monkeypatch):
    import app.services.notify as notify
    from app.services.mail import MailError

    a = account_for(app_db, "requester", plant="APM")
    sent_req, failed_req = _approved(app_db, a), _approved(app_db, a)
    _batch(app_db)
    for r in (sent_req, failed_req):
        change_status(app_db, r.id, new_status="created", account=account_for(app_db))
    # Make the two requests two parts of one group (as if a domain changed under
    # the lock), so one part is sent and the other fails before the commit.
    keys = {sent_req.id: ("x@test.local", ()), failed_req.id: ("y@test.local", ())}
    monkeypatch.setattr(notify, "group_key",
                        lambda req: ("a", ()) if not hasattr(req, "_in_lock") else keys[req.id])
    real_claim = notify._claim

    def claim(db, request_id, status):
        req = real_claim(db, request_id, status)
        if req is not None:
            req._in_lock = True
        return req

    monkeypatch.setattr(notify, "_claim", claim)

    class OneFails(FakeMailSender):
        def send(self, message):
            if failed_req.generated_code in message.html:
                raise MailError("Graph: 503")
            super().send(message)

    inner = sessionmaker(bind=app_db.get_bind(), expire_on_commit=False)

    def factory():
        s = inner()
        real_commit = s.commit
        calls = {"n": 0}

        def commit():
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("db went away")
            real_commit()

        s.commit = commit
        return s

    notify_created(factory, [sent_req.id, failed_req.id], OneFails(), "a@test.local")

    def failure(req):
        return app_db.scalar(select(RequestEvent.detail).where(
            RequestEvent.request_id == req.id, RequestEvent.action == "notify_failed"))

    assert "ส่งอีเมลแล้วแต่บันทึกผลไม่สำเร็จ" in failure(sent_req)
    assert failure(failed_req) == "created: Graph: 503"


def test_a_busy_claim_is_retried_once(app_db, monkeypatch):
    import app.services.notify as notify
    from sqlalchemy.exc import OperationalError

    a = account_for(app_db, "requester", plant="APM")
    req = _approved(app_db, a)
    _batch(app_db)
    change_status(app_db, req.id, new_status="created", account=account_for(app_db))
    real_claim, calls = notify._claim, {"n": 0}

    def busy_once(db, request_id, status):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OperationalError("UPDATE", {}, Exception("database is locked"))
        return real_claim(db, request_id, status)

    monkeypatch.setattr(notify, "_claim", busy_once)
    outbox = FakeMailSender()
    factory = sessionmaker(bind=app_db.get_bind(), expire_on_commit=False)
    assert notify_created(factory, [req.id], outbox, "a@test.local")["sent"] == 1
    assert len(outbox.sent) == 1



def test_postgres_claims_set_a_lock_timeout_sqlite_does_not():
    from app.services.notify import NOTIFY_LOCK_TIMEOUT_SECONDS, _set_lock_timeout

    class FakeSession:
        def __init__(self, dialect):
            self.sql = []
            self._bind = type("B", (), {"dialect": type("D", (), {"name": dialect})()})()

        def get_bind(self):
            return self._bind

        def execute(self, statement, *a, **kw):
            self.sql.append(str(statement))

    pg, lite = FakeSession("postgresql"), FakeSession("sqlite")
    _set_lock_timeout(pg)
    _set_lock_timeout(lite)
    assert pg.sql == [f"SET LOCAL lock_timeout = '{NOTIFY_LOCK_TIMEOUT_SECONDS}s'"]
    assert lite.sql == []


def test_lock_timeout_is_set_in_the_claiming_transaction(app_db, monkeypatch):
    import app.services.notify as notify

    a = account_for(app_db, "requester", plant="APM")
    req = _approved(app_db, a)
    _batch(app_db)
    change_status(app_db, req.id, new_status="created", account=account_for(app_db))
    order = []
    monkeypatch.setattr(notify, "_set_lock_timeout", lambda db: order.append("timeout"))
    real_claim = notify._claim
    monkeypatch.setattr(notify, "_claim",
                        lambda db, rid, st: (order.append("claim"), real_claim(db, rid, st))[1])
    factory = sessionmaker(bind=app_db.get_bind(), expire_on_commit=False)
    notify_created(factory, [req.id], FakeMailSender(), "a@test.local")
    assert order == ["timeout", "claim"]
