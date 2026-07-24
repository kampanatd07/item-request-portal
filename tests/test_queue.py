from sqlalchemy import select

from app.models import CodeGroup, CodeSystem, Factory
from app.services.requests import RequestError, change_status, submit_request

import pytest


def _make_request(db):
    factory = db.scalar(select(Factory).where(Factory.code == "APM"))
    system = db.scalar(select(CodeSystem).where(CodeSystem.code == "D365_STOCK"))
    group = db.scalar(
        select(CodeGroup).where(
            CodeGroup.code_system_id == system.id, CodeGroup.code == "800"
        )
    )
    return submit_request(
        db,
        requester_name="ทดสอบ",
        requester_email="t@example.com",
        factory_id=factory.id,
        code_system_id=system.id,
        group_id=group.id,
        subgroup_id=None,
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
    change_status(db_session, req.id, new_status="rejected", actor="test")
    with pytest.raises(RequestError):
        change_status(db_session, req.id, new_status="approved", actor="test")


def test_needs_info_roundtrip(db_session):
    req = _make_request(db_session)
    change_status(db_session, req.id, new_status="needs_info", actor="test", note="ขอสเปค")
    change_status(db_session, req.id, new_status="submitted", actor="test")
    assert req.status == "submitted"
    assert [e.action for e in req.events] == ["submitted", "needs_info", "submitted"]
