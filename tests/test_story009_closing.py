"""STORY-009 closing review (2026-10-19): fixes found by the branch-wide review."""

import pytest
from sqlalchemy import select, text

from app.models import CodeGroup, CodeSystem, Factory, FactoryCodeSystem, ItemRequest
from app.services import requests as svc
from app.services.requests import RequestError, change_status, resubmit_request, submit_request
from tests.conftest import account_for, central_ids

REPLY = "ตอบแล้วครับ"


def _needs_info(db, plant: str = "APM") -> ItemRequest:
    me = account_for(db, "requester", plant=plant)
    factory, system, group, sub = central_ids(db, plant)
    req = submit_request(db, me, factory_id=factory.id, code_system_id=system.id,
                         group_id=group.id, subgroup_id=sub.id, item_name="Ball Bearing")
    change_status(db, req.id, new_status="needs_info", note="ขอขนาด",
                  account=account_for(db, "procurement"))
    return req


def _system_with_group(db, code: str, *, active: bool, plants: list[str]) -> CodeGroup:
    """A code system linked to `plants`, with one active group (no sub-categories)."""
    system = db.scalar(select(CodeSystem).where(CodeSystem.code == code))
    if system is None:
        system = CodeSystem(code=code, name_th=code, pattern_template="{group}{run}", active=active)
        db.add(system)
        db.flush()
    system.active = active
    for plant in plants:
        factory_id = db.scalar(select(Factory.id).where(Factory.code == plant))
        db.add(FactoryCodeSystem(factory_id=factory_id, code_system_id=system.id))
    group = CodeGroup(code_system_id=system.id, code="999", name="TEST", active=True)
    db.add(group)
    db.commit()
    return group


def _resubmit(db, req: ItemRequest, **over):
    db.expire_all()
    req = db.get(ItemRequest, req.id)
    # Everything else posted back as stored, so only `over` counts as an edit.
    fields = {"code_system_id": req.code_system_id, "group_id": req.group_id,
              "subgroup_id": req.subgroup_id, "item_name": req.base_name or "",
              "brand": req.brand, "model": req.model, "size": req.size,
              "variant": req.variant, "spec_note": req.spec_note, "uom": req.uom,
              "search_name": req.search_name, "purchase_price": req.purchase_price,
              "procurement_category": req.procurement_category}
    fields.update(over)
    return resubmit_request(db, req.id, account_for(db, "requester", plant="APM"),
                            reply=REPLY, **fields)


def _status(db, req: ItemRequest) -> str:
    db.expire_all()
    return db.get(ItemRequest, req.id).status


# --- (ก) 1. The code system must belong to the request's Plant and be active --------------------------------
# A bug on master too: new requests share this validation.

@pytest.mark.parametrize("code, active, plants", [
    ("ACM_ONLY", True, ["ACM"]),         # another Plant's system
    ("CBD_STOCK", False, ["APM"]),       # linked, but the stock system is inactive
])
def test_a_new_request_refuses_a_system_it_may_not_use(app_db, code, active, plants):
    group = _system_with_group(app_db, code, active=active, plants=plants)
    factory, *_ = central_ids(app_db, "APM")
    with pytest.raises(RequestError, match="ระบบรหัส"):
        submit_request(app_db, account_for(app_db, "procurement"), factory_id=factory.id,
                       code_system_id=group.code_system_id, group_id=group.id,
                       subgroup_id=None, item_name="Ball Bearing")
    assert app_db.scalar(select(ItemRequest).where(ItemRequest.group_id == group.id)) is None


@pytest.mark.parametrize("code, active, plants", [
    ("ACM_ONLY", True, ["ACM"]),
    ("CBD_STOCK", False, ["APM"]),
])
def test_a_resubmit_refuses_a_system_the_plant_may_not_use(app_db, code, active, plants):
    req = _needs_info(app_db)
    group = _system_with_group(app_db, code, active=active, plants=plants)
    with pytest.raises(RequestError, match="ระบบรหัส"):
        _resubmit(app_db, req, code_system_id=group.code_system_id, group_id=group.id,
                  subgroup_id=None)
    assert _status(app_db, req) == "needs_info"
    assert app_db.get(ItemRequest, req.id).group_id != group.id


def test_a_resubmit_over_http_refuses_another_plants_system(client_as, app_db):
    c = client_as("requester", plant="APM")
    req = _needs_info(app_db)
    req.requester_email = "requester0@test.local"
    app_db.commit()
    group = _system_with_group(app_db, "ACM_ONLY", active=True, plants=["ACM"])
    r = c.post(f"/my-requests/{req.id}/resubmit", data={
        "code_system_id": group.code_system_id, "group_id": group.id,
        "item_name": "Ball Bearing", "reply": REPLY})
    assert r.status_code == 422 and "ระบบรหัส" in r.text
    assert _status(app_db, req) == "needs_info"


def test_the_central_system_still_works(app_db):
    req = _needs_info(app_db)
    _resubmit(app_db, req, brand="SKF")
    assert _status(app_db, req) == "submitted"


# --- (ก) 2. An empty Base Name is refused on the server, also on old rows -----------------------------------

def test_an_old_row_without_a_base_name_needs_one(app_db):
    req = _needs_info(app_db)
    req.base_name = None  # a request from before STORY-009
    app_db.commit()
    with pytest.raises(RequestError, match="ชื่อเรียกสินค้า"):
        _resubmit(app_db, req, item_name="   ")
    assert _status(app_db, req) == "needs_info"


def test_an_old_row_gets_its_base_name_on_resubmit(app_db):
    req = _needs_info(app_db)
    req.base_name = None
    app_db.commit()
    _resubmit(app_db, req, item_name="Ball Bearing")
    app_db.expire_all()
    req = app_db.get(ItemRequest, req.id)
    assert req.status == "submitted" and req.base_name == "Ball Bearing"


# --- (ข) 4. The Duplicate Check search runs before the claim ----------------------------------------------

def test_the_duplicate_search_runs_before_the_row_is_claimed(app_db, monkeypatch):
    req = _needs_info(app_db)
    seen: list[str] = []
    real = svc._duplicate_line

    def watching(db, *args, **kwargs):
        seen.append(db.execute(text("SELECT status FROM item_requests WHERE id = :id"),
                               {"id": req.id}).scalar_one())
        return real(db, *args, **kwargs)

    monkeypatch.setattr(svc, "_duplicate_line", watching)
    _resubmit(app_db, req, brand="SKF")
    assert seen == ["needs_info"]
    assert _status(app_db, req) == "submitted"
