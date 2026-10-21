"""STORY-013 ticket 06: a Name Override longer than 110 characters is refused."""

import pytest
from sqlalchemy import select

from app.models import ItemRequest, RequestEvent
from app.services.requests import RequestError, edit_name, submit_request
from tests.conftest import account_for, central_ids


def _request(db) -> ItemRequest:
    factory, system, group, sub = central_ids(db)
    return submit_request(db, account_for(db, "requester", plant="APM"),
                          factory_id=factory.id, code_system_id=system.id, group_id=group.id,
                          subgroup_id=sub.id, item_name="Ball Bearing")


def _state(db, req: ItemRequest) -> tuple[str, int]:
    db.expire_all()
    events = db.scalars(select(RequestEvent).where(RequestEvent.request_id == req.id)).all()
    return db.get(ItemRequest, req.id).item_name, len(events)


def test_110_characters_are_saved(app_db):
    req = _request(app_db)
    name = "BEARING - " + "x" * 100
    edit_name(app_db, req.id, new_name=name, account=account_for(app_db, "procurement"))
    assert _state(app_db, req)[0] == name


def test_111_characters_are_refused_and_nothing_changes(app_db):
    req = _request(app_db)
    before = _state(app_db, req)
    with pytest.raises(RequestError) as refused:
        edit_name(app_db, req.id, new_name="BEARING - " + "x" * 101,
                  account=account_for(app_db, "procurement"))
    assert "111" in str(refused.value) and "110" in str(refused.value)
    assert _state(app_db, req) == before


def test_the_length_counts_the_name_as_stored(app_db):
    req = _request(app_db)
    # 112 typed, 110 once the doubled spaces are collapsed as edit_name stores it.
    typed = "BEARING  -  " + "x" * 100
    edit_name(app_db, req.id, new_name=typed, account=account_for(app_db, "procurement"))
    assert _state(app_db, req)[0] == "BEARING - " + "x" * 100


def test_the_queue_answers_422_in_thai(client_as, app_db):
    req = _request(app_db)
    before = _state(app_db, req)
    r = client_as("procurement").post(f"/queue/{req.id}/name",
                                      data={"new_name": "BEARING - " + "ก" * 101})
    assert r.status_code == 422
    assert "111" in r.text and "110" in r.text
    assert _state(app_db, req) == before


def test_the_name_panel_says_the_limit(client_as, app_db):
    req = _request(app_db)
    assert "ไม่เกิน 110 ตัวอักษร" in client_as("procurement").get(f"/queue/{req.id}").text
