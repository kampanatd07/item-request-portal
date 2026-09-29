from sqlalchemy import select

from app.services.requests import RequestError, change_status, submit_request
from tests.conftest import account_for, central_ids

import pytest


def _make_request(db):
    factory, system, group, sub = central_ids(db)
    return submit_request(
        db,
        account=account_for(db),
        factory_id=factory.id,
        code_system_id=system.id,
        group_id=group.id,
        subgroup_id=sub.id,
        item_name="Bearing 6205 SKF",
    )


def test_queue_page_lists_request(client, db_session):
    req = _make_request(db_session)
    resp = client.get("/queue")
    assert resp.status_code == 200
    assert "Bearing 6205 SKF" in resp.text

    detail = client.get(f"/queue/{req.id}")
    assert detail.status_code == 200
    assert "ส่งคำขอแล้ว" in detail.text


def test_approve_flow_and_double_approve_blocked(client, db_session):
    req = _make_request(db_session)
    resp = client.post(
        f"/queue/{req.id}/status", data={"new_status": "approved", "note": "ok"}
    )
    assert resp.status_code == 200
    db_session.refresh(req)
    assert req.status == "approved"

    resp2 = client.post(f"/queue/{req.id}/status", data={"new_status": "approved"})
    assert resp2.status_code == 422


def test_invalid_transition_raises(db_session):
    req = _make_request(db_session)
    change_status(db_session, req.id, new_status="rejected", account=account_for(db_session))
    with pytest.raises(RequestError):
        change_status(db_session, req.id, new_status="approved", account=account_for(db_session, "administrator"))


def test_needs_info_roundtrip(db_session):
    req = _make_request(db_session)
    change_status(db_session, req.id, new_status="needs_info", account=account_for(db_session), note="ขอสเปค")
    change_status(db_session, req.id, new_status="submitted", account=account_for(db_session))
    assert req.status == "submitted"
    assert [e.action for e in req.events] == ["submitted", "needs_info", "submitted"]
