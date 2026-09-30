"""STORY-001 ticket 02: route guards per Role, and whose name/Plant a request carries."""

import pytest
from sqlalchemy import select

from app.models import ItemRequest, RequestEvent
from app.services.requests import originator_of, submit_request
from tests.conftest import account_for, central_ids

QUEUE_AND_EXPORTS = [
    ("GET", "/queue"),
    ("GET", "/queue/1"),
    ("POST", "/queue/1/status"),
    ("GET", "/exports"),
    ("POST", "/exports/1"),
    ("GET", "/exports/1/download"),
]
ADMINISTRATOR_ONLY = [
    ("GET", "/admin/config"),
    ("POST", "/admin/config/uom"),
    ("GET", "/admin/snapshots"),
    ("POST", "/admin/snapshots"),
    ("POST", "/admin/snapshots/labeled"),
]


def _form(db, factory_code: str = "APM", **extra) -> dict:
    factory, system, group, sub = central_ids(db, factory_code)
    data = {
        "factory_id": factory.id,
        "code_system_id": system.id,
        "group_id": group.id,
        "subgroup_id": sub.id,
        "item_name": "Ball Bearing",
        "brand": "SKF",
    }
    data.update(extra)
    return data


def _latest(db) -> ItemRequest:
    return db.scalar(select(ItemRequest).order_by(ItemRequest.id.desc()))


# --- Route guards (AC2) --------------------------------------------------------

@pytest.mark.parametrize("method,path", QUEUE_AND_EXPORTS + ADMINISTRATOR_ONLY)
def test_requester_is_refused_queue_exports_and_admin(client_as, method, path):
    r = client_as("requester", plant="APM").request(method, path, follow_redirects=False)
    assert r.status_code == 403
    assert "ไม่มีสิทธิ์" in r.text


@pytest.mark.parametrize("method,path", ADMINISTRATOR_ONLY)
def test_procurement_is_refused_snapshot_and_config(client_as, method, path):
    r = client_as("procurement").request(method, path, follow_redirects=False)
    assert r.status_code == 403


@pytest.mark.parametrize("path", ["/queue", "/exports"])
def test_procurement_reaches_queue_and_exports(client_as, path):
    assert client_as("procurement").get(path).status_code == 200


@pytest.mark.parametrize("path", ["/queue", "/exports", "/admin/config", "/admin/snapshots"])
def test_administrator_reaches_everything(client, path):
    assert client.get(path).status_code == 200


def test_requester_reaches_the_request_form(client_as):
    assert client_as("requester", plant="APM").get("/").status_code == 200


# --- Navigation ----------------------------------------------------------------

def test_navigation_shows_only_links_the_role_can_use(client_as):
    requester = client_as("requester", plant="APM").get("/").text
    procurement = client_as("procurement").get("/").text
    admin = client_as("administrator").get("/").text

    assert 'href="/queue"' not in requester and 'href="/admin/config"' not in requester
    assert 'href="/queue"' in procurement and 'href="/exports"' in procurement
    assert 'href="/admin/config"' not in procurement
    assert 'href="/admin/snapshots"' not in procurement
    assert 'href="/admin/config"' in admin and 'href="/queue"' in admin


# --- Request form ----------------------------------------------------------------

def test_requester_form_offers_only_their_plant_and_no_name_inputs(client_as):
    html = client_as("requester", plant="APM").get("/").text
    assert "APM" in html and "CBD —" not in html
    assert 'name="requester_name"' not in html
    assert 'name="requester_email"' not in html
    assert 'name="on_behalf_of"' not in html


def test_procurement_form_offers_every_plant_and_on_behalf_field(client_as):
    html = client_as("procurement").get("/").text
    for code in ("CBD", "APM", "APG", "ACM"):
        assert f"{code} —" in html
    assert 'name="on_behalf_of"' in html


# --- Submission: Plant (AC3) -----------------------------------------------------

def test_requester_posting_another_plant_gets_their_own_plant(client_as, app_db):
    c = client_as("requester", plant="APM")
    r = c.post("/requests", data=_form(app_db, "CBD"))
    assert r.status_code == 200
    assert _latest(app_db).factory.code == "APM"


def test_requester_submitting_without_plant_still_gets_their_own(client_as, app_db):
    data = _form(app_db)
    del data["factory_id"]
    r = client_as("requester", plant="ACM").post("/requests", data=data)
    assert r.status_code == 200
    assert _latest(app_db).factory.code == "ACM"


def test_service_uses_requesters_plant_whatever_is_passed(db_session):
    requester = account_for(db_session, "requester", plant="APG")
    factory, system, group, sub = central_ids(db_session, "CBD")
    req = submit_request(
        db_session, requester, factory_id=factory.id, code_system_id=system.id,
        group_id=group.id, subgroup_id=sub.id, item_name="Ball Bearing",
    )
    assert req.factory.code == "APG"


def test_procurement_submits_for_any_plant(client_as, app_db):
    c = client_as("procurement")
    assert c.post("/requests", data=_form(app_db, "CBD")).status_code == 200
    assert _latest(app_db).factory.code == "CBD"


def test_procurement_must_choose_a_plant(client_as, app_db):
    data = _form(app_db)
    del data["factory_id"]
    r = client_as("procurement").post("/requests", data=data)
    assert r.status_code == 422
    assert "กรุณาเลือกโรงงาน" in r.text
    assert app_db.scalar(select(ItemRequest)) is None


def test_inactive_plant_is_refused(client_as, app_db):
    data = _form(app_db, "CBD")
    factory, *_ = central_ids(app_db, "CBD")
    factory.active = False
    app_db.commit()
    r = client_as("procurement").post("/requests", data=data)
    assert r.status_code == 422
    assert app_db.scalar(select(ItemRequest)) is None


# --- Submission: whose name ------------------------------------------------------

def test_posted_requester_name_and_email_are_ignored(client_as, app_db):
    c = client_as("requester", plant="APM")
    c.post("/requests", data=_form(app_db, requester_name="Someone Else",
                                   requester_email="else@evil.example"))
    req = _latest(app_db)
    assert req.requester_email == "requester0@test.local"
    assert req.requester_name == "Test requester"
    event = app_db.scalar(select(RequestEvent).where(RequestEvent.request_id == req.id))
    assert event.actor == "requester0@test.local"


def test_procurement_on_behalf_is_in_own_name_with_originator_in_audit(client_as, app_db):
    c = client_as("procurement")
    c.post("/requests", data=_form(app_db, on_behalf_of="  สมชาย   ใจดี ",
                                   spec_note="สีดำ"))
    req = _latest(app_db)
    assert req.requester_email == "procurement0@test.local"
    assert req.spec_note == "สีดำ"  # the originator never lands in the item's spec
    assert originator_of(req) == "สมชาย ใจดี"

    detail = c.get(f"/queue/{req.id}").text
    assert "ขอแทน" in detail and "สมชาย ใจดี" in detail


def test_requester_on_behalf_is_dropped(client_as, app_db):
    c = client_as("requester", plant="APM")
    c.post("/requests", data=_form(app_db, on_behalf_of="Somebody"))
    assert originator_of(_latest(app_db)) is None


def test_no_originator_when_submitted_in_own_right(client_as, app_db):
    client_as("procurement").post("/requests", data=_form(app_db))
    assert originator_of(_latest(app_db)) is None
