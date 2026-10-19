"""STORY-009 ticket 06: Procurement hears about resubmits; Needs Info links to the form."""

import logging

import pytest
from sqlalchemy import select

from app.config import settings
from app.models import Account, ItemRequest, RequestEvent
from app.services.auth import deactivate_account
from app.services.notify import pending_notifications
from app.services.requests import change_status, submit_request
from tests.conftest import account_for, central_ids

REPLY = "เพิ่มขนาด 20 L แล้วครับ"
BASE = "https://portal.example.com"


@pytest.fixture(autouse=True)
def _base_url(monkeypatch):
    monkeypatch.setattr(settings, "public_base_url", BASE + "/")
    monkeypatch.setattr(settings, "mail_reply_to", "procurement@carabao.co.th")


def _me(db, email: str) -> Account:
    return db.scalar(select(Account).where(Account.email == email))


def _needs_info_request(db, account: Account) -> ItemRequest:
    factory, system, group, sub = central_ids(db)
    req = submit_request(db, account, factory_id=factory.id, code_system_id=system.id,
                         group_id=group.id, subgroup_id=sub.id, item_name="Ball Bearing",
                         brand="SKF")
    change_status(db, req.id, new_status="needs_info", note="ขอขนาด",
                  account=account_for(db, "procurement"))
    return req


def _form(req: ItemRequest, **over) -> dict:
    data = {"code_system_id": req.code_system_id, "group_id": req.group_id,
            "subgroup_id": req.subgroup_id, "item_name": req.base_name,
            "brand": req.brand or "", "search_name": req.search_name or "", "reply": REPLY}
    data.update(over)
    return data


def _requester_resubmits(client_as, app_db, **over):
    c = client_as("requester", plant="APM")
    me = _me(app_db, "requester0@test.local")
    req = _needs_info_request(app_db, me)
    r = c.post(f"/my-requests/{req.id}/resubmit", data=_form(req, **over))
    assert r.status_code == 200, r.text
    return me, req


def _staff(db) -> list[str]:
    return sorted(db.scalars(select(Account.email).where(
        Account.active, Account.role.in_(("procurement", "administrator")))))


# --- A Requester resubmits: one email to all of Procurement ----------------------------------------------

def test_a_requester_resubmit_emails_procurement_once(client_as, app_db, mail_outbox):
    account_for(app_db, "administrator")
    me, req = _requester_resubmits(client_as, app_db, size="20 L")
    assert len(mail_outbox.sent) == 1
    mail = mail_outbox.sent[0]
    assert mail.to == _staff(app_db)
    assert "administrator-any@test.local" in mail.to and "procurement-any@test.local" in mail.to
    assert mail.reply_to == me.email  # Procurement's reply reaches the Requester
    assert mail.subject == (f"[Item Portal] คำขอ #{req.id} ส่งกลับแล้ว — "
                            "BEARING - Ball Bearing SKF - 20 L")
    for body in (mail.text, mail.html):
        assert "BEARING - Ball Bearing SKF - 20 L" in body
        assert "APM" in body
        assert me.display_name in body and me.email in body
        assert REPLY in body
        assert "ขนาด: - → 20 L" in body
        assert f"{BASE}/queue/{req.id}" in body
        assert "duplicate" not in body.lower()


def test_a_resubmit_without_edits_says_so(client_as, app_db, mail_outbox):
    _requester_resubmits(client_as, app_db)
    mail = mail_outbox.sent[0]
    assert "ไม่ได้แก้ข้อมูล" in mail.text and "ไม่ได้แก้ข้อมูล" in mail.html


def test_no_queue_link_without_a_public_base_url(client_as, app_db, mail_outbox, monkeypatch):
    monkeypatch.setattr(settings, "public_base_url", "")
    _, req = _requester_resubmits(client_as, app_db)
    mail = mail_outbox.sent[0]
    assert f"/queue/{req.id}" not in mail.text and f"/queue/{req.id}" not in mail.html


def test_inactive_procurement_gets_nothing(client_as, app_db, mail_outbox):
    from app.services.auth import create_account
    from tests.conftest import TEST_PASSWORD

    gone = create_account(app_db, "gone@test.local", "Gone", "procurement", TEST_PASSWORD,
                          must_change_password=False)
    deactivate_account(app_db, account_for(app_db, "administrator"), gone.id)
    _requester_resubmits(client_as, app_db)
    assert gone.email not in mail_outbox.sent[0].to
    assert "procurement-any@test.local" in mail_outbox.sent[0].to


# --- No email for Procurement's own actions ---------------------------------------------------------------

@pytest.mark.parametrize("role", ["procurement", "administrator"])
def test_no_email_when_procurement_or_an_administrator_resubmits(client_as, app_db,
                                                                 mail_outbox, role):
    c = client_as(role)
    me = _me(app_db, f"{role}0@test.local")
    req = _needs_info_request(app_db, me)
    sent_before = len(mail_outbox.sent)
    r = c.post(f"/my-requests/{req.id}/resubmit", data=_form(req, size="20 L"))
    assert r.status_code == 200, r.text
    assert len(mail_outbox.sent) == sent_before


def test_no_email_for_the_requeue_button(client_as, app_db, mail_outbox):
    me = account_for(app_db, "requester", plant="APM")
    req = _needs_info_request(app_db, me)
    r = client_as("procurement").post(f"/queue/{req.id}/status",
                                      data={"new_status": "submitted", "note": "โทรมาแจ้งแล้ว"})
    assert r.status_code == 200, r.text
    assert mail_outbox.sent == []


# --- A failing sender: logged only ---------------------------------------------------------------------

def test_a_failing_email_never_blocks_the_resubmit(client_as, app_db, mail_outbox, caplog):
    mail_outbox.fail_with = "Graph credentials do not work"
    caplog.set_level(logging.ERROR, logger="app.notify")
    _, req = _requester_resubmits(client_as, app_db)
    app_db.expire_all()
    assert app_db.get(ItemRequest, req.id).status == "submitted"
    failures = [r for r in caplog.records if r.name == "app.notify" and r.levelno == logging.ERROR]
    assert len(failures) == 1 and failures[0].exc_info is not None  # log.exception
    assert f"request {req.id}" in failures[0].getMessage()
    actions = list(app_db.scalars(select(RequestEvent.action)
                                  .where(RequestEvent.request_id == req.id)))
    assert "notify_failed" not in actions and actions.count("notified") == 0
    from datetime import datetime

    assert [p for p in pending_notifications(app_db, datetime.utcnow())
            if p.request_id == req.id] == []


def test_an_unexpected_error_is_logged_too(client_as, app_db, mail_outbox, caplog,
                                           monkeypatch):
    def boom(message):
        raise RuntimeError("template bug")

    monkeypatch.setattr(mail_outbox, "send", boom)
    caplog.set_level(logging.ERROR, logger="app.notify")
    _, req = _requester_resubmits(client_as, app_db)
    app_db.expire_all()
    assert app_db.get(ItemRequest, req.id).status == "submitted"
    assert any(r.exc_info and r.exc_info[0] is RuntimeError for r in caplog.records)


# --- The Needs Info email links to the resubmit page ---------------------------------------------------

def test_the_needs_info_email_links_to_the_resubmit_page(client_as, app_db, mail_outbox):
    me = account_for(app_db, "requester", plant="APM")
    factory, system, group, sub = central_ids(app_db)
    req = submit_request(app_db, me, factory_id=factory.id, code_system_id=system.id,
                         group_id=group.id, subgroup_id=sub.id, item_name="Ball Bearing")
    r = client_as("procurement").post(f"/queue/{req.id}/status",
                                      data={"new_status": "needs_info", "note": "ขอขนาด"})
    assert r.status_code == 200, r.text
    mail = mail_outbox.sent[-1]
    link = f"{BASE}/my-requests/{req.id}/resubmit"
    for body in (mail.text, mail.html):
        assert link in body
        assert "แก้ไขและส่งกลับในระบบ" in body and "(สำหรับผู้มีบัญชี)" in body
        assert "กรุณาตอบกลับอีเมลนี้" in body
        assert "my-requests#request" not in body


# --- An Originator from another Plant follows the link: 403 says to reply by email ----------------------

def test_an_originator_in_another_plant_is_told_to_reply_by_email(app_db, client_as):
    from fastapi.testclient import TestClient

    from app.main import app
    from app.models import Factory
    from app.services.auth import create_account
    from tests.conftest import TEST_PASSWORD, login

    acm = app_db.scalar(select(Factory.id).where(Factory.code == "ACM"))
    create_account(app_db, "somchai@apm.co.th", "สมชาย", "requester", TEST_PASSWORD,
                   factory_id=acm, must_change_password=False)
    proc = account_for(app_db, "procurement")
    factory, system, group, sub = central_ids(app_db)
    req = submit_request(app_db, proc, factory_id=factory.id, code_system_id=system.id,
                         group_id=group.id, subgroup_id=sub.id, item_name="Ball Bearing",
                         on_behalf_of="สมชาย", originator_email="somchai@apm.co.th")
    change_status(app_db, req.id, new_status="needs_info", note="ขอขนาด", account=proc)
    with TestClient(app) as c:
        assert login(c, "somchai@apm.co.th").status_code == 303
        r = c.get(f"/my-requests/{req.id}/resubmit")
    assert r.status_code == 403
    assert "ตอบกลับทางอีเมลที่ได้รับแทนได้" in r.text


def test_a_stranger_gets_the_plain_403(client_as, app_db):
    me = account_for(app_db, "requester", plant="APM")
    req = _needs_info_request(app_db, me)
    r = client_as("requester", plant="APM").get(f"/my-requests/{req.id}/resubmit")
    assert r.status_code == 403
    assert "ตอบกลับทางอีเมลที่ได้รับแทนได้" not in r.text


# --- Review 2026-10-19: the email is tied to the event the resubmit wrote ---------------------------------

def _overtaken_by(monkeypatch, meanwhile):
    """Run `meanwhile(db, request_id)` right after the resubmit commits, before
    the route goes on: the gap where a later lookup of "the latest submitted
    event" would see someone else's change."""
    from app.routes import requests as routes

    real = routes.resubmit_request

    def then_overtaken(db, request_id, *args, **kwargs):
        result = real(db, request_id, *args, **kwargs)
        meanwhile(db, request_id)
        return result

    monkeypatch.setattr(routes, "resubmit_request", then_overtaken)


def test_a_status_change_before_the_email_still_sends_it(client_as, app_db, mail_outbox,
                                                         monkeypatch):
    def in_review(db, request_id):
        change_status(db, request_id, new_status="in_review",
                      account=account_for(db, "procurement"))

    _overtaken_by(monkeypatch, in_review)
    _, req = _requester_resubmits(client_as, app_db, size="20 L")
    app_db.expire_all()
    assert app_db.get(ItemRequest, req.id).status == "in_review"
    assert len(mail_outbox.sent) == 1 and REPLY in mail_outbox.sent[0].text


def test_a_second_round_before_the_email_does_not_change_it(client_as, app_db, mail_outbox,
                                                            monkeypatch):
    from app.services.requests import resubmit_request

    def second_round(db, request_id):
        change_status(db, request_id, new_status="needs_info", note="ขอรุ่นด้วย",
                      account=account_for(db, "procurement"))
        req = db.get(ItemRequest, request_id)
        resubmit_request(db, request_id, _me(db, "requester0@test.local"),
                         **_form(req, reply="REPLY-ROUND-2", model="6205"))

    _overtaken_by(monkeypatch, second_round)
    _requester_resubmits(client_as, app_db, size="20 L")
    # One email, about the first resubmit: the second went through the
    # service only, so it scheduled nothing.
    assert len(mail_outbox.sent) == 1
    mail = mail_outbox.sent[0]
    assert REPLY in mail.text and "ขนาด: - → 20 L" in mail.text
    assert "REPLY-ROUND-2" not in mail.text and "6205" not in mail.text.split("ที่แก้:")[1]


def test_the_service_names_the_event_only_when_procurement_must_hear(app_db):
    from app.services.requests import resubmit_request

    for role, plant in (("requester", "APM"), ("procurement", None)):
        me = account_for(app_db, role, plant=plant)
        req = _needs_info_request(app_db, me)
        result = resubmit_request(app_db, req.id, me, **_form(req))
        submitted = app_db.scalar(select(RequestEvent).where(
            RequestEvent.request_id == req.id, RequestEvent.action == "submitted")
            .order_by(RequestEvent.id.desc()).limit(1))
        expected = submitted.id if role == "requester" else None
        assert result.req.id == req.id and result.notify_event_id == expected


# --- Review 2026-10-19: an old Needs Info link still leads to the request ---------------------------------

def test_an_old_needs_info_link_points_to_my_requests(client_as, app_db):
    c = client_as("requester", plant="APM")
    me = _me(app_db, "requester0@test.local")
    req = _needs_info_request(app_db, me)
    assert c.post(f"/my-requests/{req.id}/resubmit", data=_form(req)).status_code == 200
    r = c.get(f"/my-requests/{req.id}/resubmit")
    assert r.status_code == 409
    assert f'href="/my-requests#request-{req.id}"' in r.text and "ดูคำขอนี้ในคำขอของฉัน" in r.text


def test_an_inactive_originator_is_not_told_about_plants(app_db):
    from app.models import Factory
    from app.services.auth import create_account
    from app.services.requests import RequestForbidden, resubmittable
    from tests.conftest import TEST_PASSWORD

    apm = app_db.scalar(select(Factory.id).where(Factory.code == "APM"))
    originator = create_account(app_db, "somchai@apm.co.th", "สมชาย", "requester",
                                TEST_PASSWORD, factory_id=apm, must_change_password=False)
    originator.active = False
    app_db.commit()
    proc = account_for(app_db, "procurement")
    factory, system, group, sub = central_ids(app_db)
    req = submit_request(app_db, proc, factory_id=factory.id, code_system_id=system.id,
                         group_id=group.id, subgroup_id=sub.id, item_name="Ball Bearing",
                         on_behalf_of="สมชาย", originator_email="somchai@apm.co.th")
    change_status(app_db, req.id, new_status="needs_info", note="ขอขนาด", account=proc)
    with pytest.raises(RequestForbidden) as refused:
        resubmittable(app_db, req.id, originator)
    assert "คนละโรงงาน" not in str(refused.value)
