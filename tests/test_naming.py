from sqlalchemy import select

import pytest

from app.services.naming import NamingError, compose_name
from app.services.requests import RequestError, change_status, edit_name, submit_request
from app.services.exporter import export_pending
from tests.conftest import central_ids


def test_compose_convention_order():
    assert compose_name(
        "Ball Bearing", brand="SKF", model="6205-2Z", size="25 mm",
        category_prefix="BEARING",
    ) == "BEARING - Ball Bearing SKF 6205-2Z - 25 mm"


def test_compose_cleans_whitespace_and_forbidden_chars():
    assert compose_name("  Ball   Bearing ", brand="SKF|=") == "Ball Bearing SKF"


def test_compose_drops_repeated_tokens():
    # user typed the brand inside the name field too
    assert compose_name("Ball Bearing SKF", brand="SKF", model="6205") == (
        "Ball Bearing SKF 6205"
    )
    # identical part repeated entirely
    assert compose_name("O-Ring", brand="o-ring") == "O-Ring"


def test_compose_empty_and_too_long_raise():
    with pytest.raises(NamingError):
        compose_name("   ")
    with pytest.raises(NamingError):
        compose_name("X" * 90, brand="Y" * 30)


def _submit(db, **overrides):
    factory, system, group, sub = central_ids(db)
    kwargs = dict(
        requester_name="ทดสอบ", requester_email="t@example.com",
        factory_id=factory.id, code_system_id=system.id, group_id=group.id,
        subgroup_id=sub.id, item_name="Ball Bearing", brand="SKF",
        model="6205-2Z", size="25 mm",
    )
    kwargs.update(overrides)
    return submit_request(db, **kwargs)


def test_submit_stores_composed_name(db_session):
    req = _submit(db_session)
    assert req.item_name == "BEARING - Ball Bearing SKF 6205-2Z - 25 mm"
    assert req.search_name == "BALL BEARING"


def test_procurement_can_edit_name_before_export(db_session):
    req = _submit(db_session)
    edit_name(db_session, req.id,
              new_name="BEARING - Ball Bearing SKF 6205-2Z C3 - 25 mm",
              actor="procurement")
    assert req.item_name == "BEARING - Ball Bearing SKF 6205-2Z C3 - 25 mm"
    assert [e.action for e in req.events][-1] == "name_edited"


def test_name_locked_after_export(db_session):
    req = _submit(db_session)
    change_status(db_session, req.id, new_status="approved", actor="test")
    factory, _s, _g, _sub = central_ids(db_session)
    export_pending(db_session, factory.id)
    db_session.refresh(req)
    with pytest.raises(RequestError):
        edit_name(db_session, req.id, new_name="New name", actor="procurement")
