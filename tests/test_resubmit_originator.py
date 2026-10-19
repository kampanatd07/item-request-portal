"""STORY-009 ticket 04: the Originator sees and resubmits requests made for them."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.main import app
from app.models import Account, Factory, ItemRequest, RequestEvent
from app.services import requests as svc
from app.services.auth import create_account
from app.services.requests import change_status, resubmit_request, submit_request
from tests.conftest import TEST_PASSWORD, account_for, central_ids, login
from tests.test_requeue import _all_text, _file_db, _one_winner, _race

REPLY = "ขนาด 20 L ครับ"
ORIGINATOR = "somchai@apm.co.th"


def _account(db: Session, email: str, role: str = "requester",
             plant: str | None = "APM") -> Account:
    factory_id = db.scalar(select(Factory.id).where(Factory.code == plant)) if plant else None
    return create_account(db, email, "สมชาย ใจดี", role, TEST_PASSWORD,
                          factory_id=factory_id, must_change_password=False)


@pytest.fixture()
def client_for():
    """client_for(email) -> a TestClient logged in as that existing Account."""
    clients: list[TestClient] = []

    def _make(email: str) -> TestClient:
        c = TestClient(app)
        c.__enter__()
        clients.append(c)
        assert login(c, email).status_code == 303
        return c

    yield _make
    for c in clients:
        c.__exit__(None, None, None)


def _on_behalf(db: Session, status: str = "needs_info", plant: str = "APM",
               base: str = "Ball Bearing", email: str = ORIGINATOR) -> ItemRequest:
    """A request Procurement submitted for `email`, moved to `status`."""
    proc = account_for(db, "procurement")
    factory, system, group, sub = central_ids(db, plant)
    req = submit_request(db, proc, factory_id=factory.id, code_system_id=system.id,
                         group_id=group.id, subgroup_id=sub.id, item_name=base, brand="SKF",
                         on_behalf_of="สมชาย ใจดี", originator_email=email)
    if status != "submitted":
        change_status(db, req.id, new_status=status, account=proc, note="ขอขนาด")
    return req


def _form(req: ItemRequest, **over) -> dict:
    data = {
        "code_system_id": req.code_system_id, "group_id": req.group_id,
        "subgroup_id": req.subgroup_id or "", "item_name": req.base_name or "",
        "brand": req.brand or "", "model": req.model or "", "size": req.size or "",
        "variant": req.variant or "", "spec_note": req.spec_note or "", "uom": req.uom or "",
        "search_name": req.search_name or "", "purchase_price": req.purchase_price or "",
        "procurement_category": req.procurement_category or "",
        "on_behalf_of": req.originator_name or "", "originator_email": req.originator_email or "",
        "reply": REPLY,
    }
    data.update(over)
    return data


def _url(req: ItemRequest) -> str:
    return f"/my-requests/{req.id}/resubmit"


def _fresh(db: Session, req: ItemRequest) -> ItemRequest:
    db.expire_all()
    return db.get(ItemRequest, req.id)


def _events(db: Session, req: ItemRequest) -> list[RequestEvent]:
    db.expire_all()
    return list(db.scalars(select(RequestEvent).where(RequestEvent.request_id == req.id)
                           .order_by(RequestEvent.id)))


# --- My requests -------------------------------------------------------------------------------------

def test_my_requests_lists_requests_made_for_me_in_every_status(app_db, client_for):
    _account(app_db, ORIGINATOR)
    waiting = _on_behalf(app_db)
    queued = _on_behalf(app_db, status="submitted", base="Seal Ring")
    page = client_for(ORIGINATOR).get("/my-requests").text
    assert f'id="request-{waiting.id}"' in page and f'id="request-{queued.id}"' in page
    assert page.count("ขอแทนโดย Test procurement") == 2
    assert f'href="{_url(waiting)}"' in page
    assert f'href="{_url(queued)}"' not in page


def test_the_requester_sees_no_on_behalf_label(app_db, client_as):
    c = client_as("procurement")
    me = app_db.scalar(select(Account).where(Account.email == "procurement0@test.local"))
    factory, system, group, sub = central_ids(app_db)
    req = submit_request(app_db, me, factory_id=factory.id, code_system_id=system.id,
                         group_id=group.id, subgroup_id=sub.id, item_name="Ball Bearing",
                         on_behalf_of="สมชาย ใจดี", originator_email=ORIGINATOR)
    page = c.get("/my-requests").text
    assert f'id="request-{req.id}"' in page and "ขอแทนโดย" not in page


# --- The Originator resubmits ------------------------------------------------------------------------

def test_the_originator_resubmits_and_is_the_actor(app_db, client_for):
    _account(app_db, ORIGINATOR)
    req = _on_behalf(app_db)
    before = len(_events(app_db, req))
    r = client_for(ORIGINATOR).post(_url(req), data=_form(req, size="20 L"))
    assert r.status_code == 200, r.text
    req = _fresh(app_db, req)
    assert req.status == "submitted" and req.size == "20 L"
    new = _events(app_db, req)[before:]
    assert [e.action for e in new] == ["request_edited", "submitted"]
    assert {e.actor for e in new} == {ORIGINATOR}


def test_the_originator_sees_the_requester_and_cannot_edit_the_originator(app_db, client_for):
    _account(app_db, ORIGINATOR)
    req = _on_behalf(app_db)
    page = client_for(ORIGINATOR).get(_url(req)).text
    assert "Test procurement" in page and req.requester_email in page
    assert 'name="on_behalf_of"' not in page and 'name="originator_email"' not in page
    assert "สมชาย ใจดี" in page  # shown, read-only


def test_originator_fields_posted_by_the_originator_are_ignored(app_db, client_for):
    _account(app_db, ORIGINATOR)
    req = _on_behalf(app_db)
    before = len(_events(app_db, req))
    r = client_for(ORIGINATOR).post(_url(req), data=_form(
        req, on_behalf_of="คนอื่น", originator_email="other@apm.co.th"))
    assert r.status_code == 200, r.text
    req = _fresh(app_db, req)
    assert (req.originator_name, req.originator_email) == ("สมชาย ใจดี", ORIGINATOR)
    assert [e.action for e in _events(app_db, req)[before:]] == ["submitted"]


def test_an_originator_without_a_plant_may_resubmit_in_any_plant(app_db, client_for):
    _account(app_db, "boss@carabao.co.th", role="procurement", plant=None)
    req = _on_behalf(app_db, plant="ACM", email="boss@carabao.co.th")
    assert client_for("boss@carabao.co.th").post(_url(req), data=_form(req)).status_code == 200
    assert _fresh(app_db, req).status == "submitted"


# --- Refused Originators: 403, nothing written --------------------------------------------------------

def test_an_originator_in_another_plant_gets_403(app_db, client_for):
    _account(app_db, ORIGINATOR, plant="ACM")
    req = _on_behalf(app_db)
    c = client_for(ORIGINATOR)
    assert c.get(_url(req)).status_code == 403
    assert c.post(_url(req), data=_form(req)).status_code == 403
    assert _fresh(app_db, req).status == "needs_info"


def test_an_originator_in_another_plant_sees_the_row_without_the_button(app_db, client_for):
    # Shown, read-only: they get the same data by email (Peter, 2026-10-19).
    _account(app_db, ORIGINATOR, plant="ACM")
    req = _on_behalf(app_db)
    page = client_for(ORIGINATOR).get("/my-requests").text
    assert f'id="request-{req.id}"' in page and "ขอแทนโดย Test procurement" in page
    assert f'href="{_url(req)}"' not in page


def test_an_inactive_originator_gets_403(app_db):
    # A deactivated Account cannot log in, so this is checked on the service.
    originator = _account(app_db, ORIGINATOR)
    originator.active = False
    app_db.commit()
    req = _on_behalf(app_db)
    with pytest.raises(svc.RequestForbidden):
        resubmit_request(app_db, req.id, originator, **_form(req))
    assert _fresh(app_db, req).status == "needs_info"


# --- The Requester changes the originator ------------------------------------------------------------

def _requester_client(app_db, client_as) -> tuple[TestClient, ItemRequest]:
    """Procurement (logged in) and a Needs Info request it made for ORIGINATOR."""
    c = client_as("procurement")
    me = app_db.scalar(select(Account).where(Account.email == "procurement0@test.local"))
    factory, system, group, sub = central_ids(app_db)
    req = submit_request(app_db, me, factory_id=factory.id, code_system_id=system.id,
                         group_id=group.id, subgroup_id=sub.id, item_name="Ball Bearing",
                         on_behalf_of="สมชาย ใจดี", originator_email=ORIGINATOR)
    change_status(app_db, req.id, new_status="needs_info", account=me, note="ขอขนาด")
    return c, req


def test_the_requester_form_is_prefilled_with_the_originator(app_db, client_as):
    c, req = _requester_client(app_db, client_as)
    page = c.get(_url(req)).text
    assert 'name="on_behalf_of" value="สมชาย ใจดี"' in page
    assert f'name="originator_email" type="email" value="{ORIGINATOR}"' in page
    before = len(_events(app_db, req))
    assert c.post(_url(req), data=_form(req)).status_code == 200
    assert [e.action for e in _events(app_db, req)[before:]] == ["submitted"]


def test_the_requester_may_change_the_originator(app_db, client_as):
    c, req = _requester_client(app_db, client_as)
    r = c.post(_url(req), data=_form(req, on_behalf_of="สมหญิง", originator_email="Ying@APG.co.th"))
    assert r.status_code == 200, r.text
    req = _fresh(app_db, req)
    assert (req.originator_name, req.originator_email) == ("สมหญิง", "ying@apg.co.th")
    edited = [e for e in _events(app_db, req) if e.action == "request_edited"][-1]
    assert "ขอแทน: สมชาย ใจดี → สมหญิง" in edited.detail
    assert f"อีเมลผู้ขอจริง: {ORIGINATOR} → ying@apg.co.th" in edited.detail


def test_a_form_without_originator_fields_keeps_them(app_db, client_as, client_for):
    _account(app_db, ORIGINATOR)
    c, req = _requester_client(app_db, client_as)
    form = _form(req, size="20 L")
    del form["on_behalf_of"], form["originator_email"]
    assert c.post(_url(req), data=form).status_code == 200
    req = _fresh(app_db, req)
    assert (req.originator_name, req.originator_email) == ("สมชาย ใจดี", ORIGINATOR)
    edited = [e for e in _events(app_db, req) if e.action == "request_edited"][-1]
    assert "ขอแทน" not in edited.detail and "อีเมลผู้ขอจริง" not in edited.detail
    # ...and the Originator can still answer the next Needs Info.
    change_status(app_db, req.id, new_status="needs_info", note="ขอรุ่นด้วย",
                  account=account_for(app_db, "procurement"))
    r = client_for(ORIGINATOR).post(_url(req), data=_form(_fresh(app_db, req)))
    assert r.status_code == 200, r.text
    assert _fresh(app_db, req).status == "submitted"


def test_clearing_the_originator_is_still_a_change(app_db, client_as):
    c, req = _requester_client(app_db, client_as)
    assert c.post(_url(req), data=_form(req, on_behalf_of="", originator_email="")).status_code == 200
    req = _fresh(app_db, req)
    assert (req.originator_name, req.originator_email) == (None, None)
    edited = [e for e in _events(app_db, req) if e.action == "request_edited"][-1]
    assert edited.detail.splitlines() == ["ขอแทน: สมชาย ใจดี → -",
                                          f"อีเมลผู้ขอจริง: {ORIGINATOR} → -"]


def _switch_off(db: Session, domain: str) -> None:
    from app.models import MailDomain
    from app.services import config_admin

    config_admin.toggle_mail_domain(
        db, db.scalar(select(MailDomain.id).where(MailDomain.domain == domain)))


def test_a_switched_off_stored_domain_does_not_block_a_name_fix(app_db, client_as):
    c, req = _requester_client(app_db, client_as)
    _switch_off(app_db, "apm.co.th")
    r = c.post(_url(req), data=_form(req, size="20 L", on_behalf_of="สมชาย ใจดีมาก"))
    assert r.status_code == 200, r.text
    req = _fresh(app_db, req)
    assert req.originator_name == "สมชาย ใจดีมาก" and req.size == "20 L"
    assert req.originator_email == ORIGINATOR


def test_a_new_email_on_a_switched_off_domain_is_refused(app_db, client_as):
    c, req = _requester_client(app_db, client_as)
    _switch_off(app_db, "apm.co.th")
    r = c.post(_url(req), data=_form(req, originator_email="other@apm.co.th"))
    assert r.status_code == 422
    assert _fresh(app_db, req).originator_email == ORIGINATOR


def test_originator_lines_come_after_the_item_name_line(app_db, client_as):
    c, req = _requester_client(app_db, client_as)
    assert c.post(_url(req), data=_form(req, brand="NSK", on_behalf_of="สมหญิง")).status_code == 200
    edited = [e for e in _events(app_db, req) if e.action == "request_edited"][-1]
    labels = [line.split(":")[0] for line in edited.detail.splitlines()]
    assert labels == ["แบรนด์", "ชื่อสินค้า", "ขอแทน"]


def test_a_not_allowed_originator_domain_is_refused_and_nothing_saved(app_db, client_as):
    c, req = _requester_client(app_db, client_as)
    before = len(_events(app_db, req))
    r = c.post(_url(req), data=_form(req, size="20 L", originator_email="x@gmail.com"))
    assert r.status_code == 422
    assert "อีเมล" in r.text
    req = _fresh(app_db, req)
    assert req.status == "needs_info" and req.originator_email == ORIGINATOR
    assert req.size is None
    assert len(_events(app_db, req)) == before


# --- Requester and Originator at once: one wins ---------------------------------------------------------

def test_the_requester_and_the_originator_at_once_one_wins(tmp_path, seeded_template,
                                                           monkeypatch):
    factory = _file_db(tmp_path, seeded_template)
    with factory() as db:
        _account(db, ORIGINATOR)
        request_id = _on_behalf(db).id
        before = len(_events(db, db.get(ItemRequest, request_id)))

    def job(email: str, brand: str, reply: str):
        def run(db: Session) -> None:
            req = db.get(ItemRequest, request_id)
            actor = db.scalar(select(Account).where(Account.email == email))
            form = _form(req, brand=brand, reply=reply)
            resubmit_request(db, request_id, actor, **form)
        return run

    marks = {"requester": ("procurement-any@test.local", "BRAND-R", "REPLY-R"),
             "originator": (ORIGINATOR, "BRAND-O", "REPLY-O")}
    results = _race(monkeypatch, factory, {n: job(*m) for n, m in marks.items()})
    winner, loser = _one_winner(results)
    with factory() as db:
        new = _events(db, db.get(ItemRequest, request_id))[before:]
        assert [e.action for e in new].count("submitted") == 1
        assert {e.actor for e in new} == {marks[winner][0]}
        assert db.get(ItemRequest, request_id).brand == marks[winner][1]
        text = _all_text(db, request_id)
        assert marks[winner][2] in text
        assert marks[loser][1] not in text and marks[loser][2] not in text
