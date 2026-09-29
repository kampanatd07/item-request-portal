"""STORY-001 ticket 03: only Administrators consume the Running Register (AC4, AC8)."""

import pytest
from sqlalchemy import select

from app.models import ExportBatch, ItemRequest, RequestEvent, RunningRegister
from app.services.exporter import export_pending
from app.services.requests import (
    RequestError,
    RequestForbidden,
    change_category,
    change_status,
    edit_name,
    override_code,
    submit_request,
)
from tests.conftest import account_for, central_ids


def _register(db, group_code: str = "900", sub_code: str = "01") -> int | None:
    reg = db.scalar(select(RunningRegister).where(
        RunningRegister.group_code == group_code, RunningRegister.sub_code == sub_code))
    db.refresh(reg) if reg else None
    return reg.last_running if reg else None


def _submit(db, group_code: str = "900", sub_code: str = "01") -> ItemRequest:
    factory, system, group, sub = central_ids(db, "APM", group_code, sub_code)
    return submit_request(
        db, account_for(db), factory_id=factory.id, code_system_id=system.id,
        group_id=group.id, subgroup_id=sub.id, item_name="Ball Bearing",
    )


def _approved(db, group_code: str = "900", sub_code: str = "01") -> ItemRequest:
    req = _submit(db, group_code, sub_code)
    return change_status(db, req.id, new_status="approved",
                         account=account_for(db, "administrator"))


def _other_sub(db):
    return central_ids(db, "APM", "900", "02")[3]


# --- Service: Procurement refused, register untouched (AC8) --------------------

@pytest.mark.parametrize("via_in_review", [False, True])
def test_procurement_cannot_approve_and_register_is_unchanged(db_session, via_in_review):
    req = _submit(db_session)
    if via_in_review:
        change_status(db_session, req.id, new_status="in_review",
                      account=account_for(db_session))
    before = _register(db_session)
    with pytest.raises(RequestForbidden):
        change_status(db_session, req.id, new_status="approved",
                      account=account_for(db_session))
    assert _register(db_session) == before
    db_session.refresh(req)
    assert req.generated_code is None
    assert req.status == ("in_review" if via_in_review else "submitted")


def test_procurement_cannot_override_code(db_session):
    req = _approved(db_session)
    code = req.generated_code
    with pytest.raises(RequestForbidden):
        override_code(db_session, req.id, new_code="90001009999",
                      account=account_for(db_session))
    db_session.refresh(req)
    assert req.generated_code == code


def test_procurement_cannot_recategorise_coded_request_and_register_is_unchanged(db_session):
    req = _approved(db_session)
    before_old, before_new = _register(db_session, "900", "01"), _register(db_session, "900", "02")
    with pytest.raises(RequestForbidden):
        change_category(db_session, req.id, subgroup_id=_other_sub(db_session).id,
                        account=account_for(db_session))
    assert _register(db_session, "900", "01") == before_old
    assert _register(db_session, "900", "02") == before_new
    db_session.refresh(req)
    assert req.subgroup.code == "01"


def test_requester_cannot_approve(db_session):
    req = _submit(db_session)
    with pytest.raises(RequestForbidden):
        change_status(db_session, req.id, new_status="approved",
                      account=account_for(db_session, "requester", plant="APM"))


# --- Service: Administrator ----------------------------------------------------

@pytest.mark.parametrize("via_in_review", [False, True])
def test_administrator_approves_from_submitted_or_in_review(db_session, via_in_review):
    req = _submit(db_session)
    if via_in_review:
        change_status(db_session, req.id, new_status="in_review",
                      account=account_for(db_session))
    before = _register(db_session)
    change_status(db_session, req.id, new_status="approved",
                  account=account_for(db_session, "administrator"))
    assert req.status == "approved"
    assert req.generated_code == f"9000100{before + 1:04d}"
    assert _register(db_session) == before + 1


def test_administrator_recategorise_reissues_code_from_new_sub(db_session):
    req = _approved(db_session)
    old_code = req.generated_code
    before_old, before_new = _register(db_session, "900", "01"), _register(db_session, "900", "02")

    change_category(db_session, req.id, subgroup_id=_other_sub(db_session).id,
                    account=account_for(db_session, "administrator"))

    assert req.generated_code == f"9000200{before_new + 1:04d}"
    assert _register(db_session, "900", "02") == before_new + 1
    assert _register(db_session, "900", "01") == before_old  # old number burned, never reused
    actions = [(e.action, e.detail) for e in req.events]
    assert ("code_reissued", f"{old_code} -> {req.generated_code}") in actions
    assert ("category_changed", "900-01 -> 900-02") in actions


def test_recategorise_after_export_is_refused_even_for_administrator(db_session):
    req = _approved(db_session)
    export_pending(db_session, req.factory_id, account=account_for(db_session))
    before = _register(db_session, "900", "02")
    with pytest.raises(RequestError, match="export"):
        change_category(db_session, req.id, subgroup_id=_other_sub(db_session).id,
                        account=account_for(db_session, "administrator"))
    assert _register(db_session, "900", "02") == before


def test_administrator_can_override_code(db_session):
    req = _approved(db_session)
    override_code(db_session, req.id, new_code="90001009999",
                  account=account_for(db_session, "administrator"))
    assert req.generated_code == "90001009999"


# --- Service: Procurement keeps the review work ----------------------------------

def test_procurement_reviews_edits_and_recategorises_before_a_code(db_session):
    procurement = account_for(db_session)
    req = _submit(db_session)
    edit_name(db_session, req.id, new_name="BEARING - Ball Bearing 6205", account=procurement)
    change_category(db_session, req.id, subgroup_id=_other_sub(db_session).id,
                    account=procurement)
    change_status(db_session, req.id, new_status="in_review", account=procurement)
    change_status(db_session, req.id, new_status="needs_info", account=procurement, note="สเปค?")
    change_status(db_session, req.id, new_status="submitted", account=procurement)
    change_status(db_session, req.id, new_status="rejected", account=procurement)
    db_session.refresh(req)
    assert req.status == "rejected" and req.subgroup.code == "02"
    assert req.generated_code is None


# --- Audit trail (AC4) -----------------------------------------------------------

def test_every_event_records_the_acting_accounts_email(client_as, app_db):
    procurement = client_as("procurement")          # procurement0@test.local
    admin = client_as("administrator")              # administrator1@test.local
    factory, system, group, sub = central_ids(app_db, "APM")
    procurement.post("/requests", data={
        "factory_id": factory.id, "code_system_id": system.id, "group_id": group.id,
        "subgroup_id": sub.id, "item_name": "Ball Bearing",
    })
    req = app_db.scalar(select(ItemRequest))
    procurement.post(f"/queue/{req.id}/name", data={"new_name": "BEARING - Ball Bearing X"})
    procurement.post(f"/queue/{req.id}/status", data={"new_status": "in_review"})
    admin.post(f"/queue/{req.id}/status", data={"new_status": "approved"})
    procurement.post(f"/exports/{factory.id}")
    app_db.refresh(req)
    procurement.post(f"/exports/{req.export_batch_id}/mark-created")

    events = list(app_db.scalars(
        select(RequestEvent).where(RequestEvent.request_id == req.id).order_by(RequestEvent.id)))
    by_action = {e.action: e.actor for e in events}
    assert by_action == {
        "submitted": "procurement0@test.local",
        "name_edited": "procurement0@test.local",
        "in_review": "procurement0@test.local",
        "approved": "administrator1@test.local",
        "code_generated": "administrator1@test.local",
        "exported": "procurement0@test.local",
        "created": "procurement0@test.local",
    }
    assert app_db.get(ExportBatch, req.export_batch_id).created_by == "procurement0@test.local"


# --- HTTP ------------------------------------------------------------------------

def test_procurement_gets_403_on_approve_override_and_coded_recategorise(client_as, app_db):
    procurement = client_as("procurement")
    pending = _submit(app_db)
    coded = _approved(app_db)
    before = (_register(app_db, "900", "01"), _register(app_db, "900", "02"))

    r = procurement.post(f"/queue/{pending.id}/status", data={"new_status": "approved"})
    assert r.status_code == 403 and "ผู้ดูแลระบบ" in r.text
    r = procurement.post(f"/queue/{coded.id}/code", data={"new_code": "90001009999"})
    assert r.status_code == 403
    r = procurement.post(f"/queue/{coded.id}/category",
                         data={"subgroup_id": _other_sub(app_db).id})
    assert r.status_code == 403

    assert (_register(app_db, "900", "01"), _register(app_db, "900", "02")) == before


def test_queue_shows_procurement_only_the_buttons_it_can_use(client_as, app_db):
    pending = _submit(app_db)
    coded = _approved(app_db)
    procurement, admin = client_as("procurement"), client_as("administrator")

    page = procurement.get(f"/queue/{pending.id}").text
    assert 'value="approved"' not in page
    assert 'value="in_review"' in page and 'value="rejected"' in page
    page = procurement.get(f"/queue/{coded.id}").text
    assert f"/queue/{coded.id}/code" not in page
    assert f"/queue/{coded.id}/category" not in page

    assert 'value="approved"' in admin.get(f"/queue/{pending.id}").text
    page = admin.get(f"/queue/{coded.id}").text
    assert f"/queue/{coded.id}/code" in page and f"/queue/{coded.id}/category" in page


def test_in_review_label_says_checked_awaiting_approval(client, app_db):
    req = _submit(app_db)
    change_status(app_db, req.id, new_status="in_review", account=account_for(app_db))
    assert "ตรวจแล้ว รออนุมัติ" in client.get("/queue").text


def test_htmx_swaps_validation_and_permission_errors(client):
    # htmx 1.9 drops 4xx by default; base.html must opt 422/403 back in.
    html = client.get("/").text
    assert "htmx:beforeSwap" in html and "422" in html and "403" in html


# --- Row locks (Postgres) ----------------------------------------------------------

@pytest.fixture()
def locked_selects(db_session):
    """ItemRequest SELECTs that ask for FOR UPDATE, compiled as Postgres.

    SQLite silently drops FOR UPDATE, so the race cannot be run here; this
    proves both sides of it at least request the lock.
    """
    from sqlalchemy import event
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.orm import Session

    seen: list[str] = []

    def _capture(state):
        if state.is_select:
            sql = str(state.statement.compile(dialect=postgresql.dialect()))
            if "FROM item_requests" in sql and "FOR UPDATE" in sql:
                seen.append(sql)

    event.listen(Session, "do_orm_execute", _capture)
    yield seen
    event.remove(Session, "do_orm_execute", _capture)


def test_recategorise_locks_the_request_row(db_session, locked_selects):
    req = _approved(db_session)
    locked_selects.clear()
    change_category(db_session, req.id, subgroup_id=_other_sub(db_session).id,
                    account=account_for(db_session, "administrator"))
    assert locked_selects


def test_export_locks_the_request_rows(db_session, locked_selects):
    req = _approved(db_session)
    locked_selects.clear()
    export_pending(db_session, req.factory_id, account=account_for(db_session))
    assert locked_selects


# --- Governance §4: Item Group moves after a code need the Data Owner ---------------

def test_coded_request_cannot_move_to_another_item_group(db_session):
    req = _approved(db_session, "900", "01")
    code = req.generated_code
    other_group_sub = central_ids(db_session, "APM", "901", "01")[3]
    before = (_register(db_session, "900", "01"), _register(db_session, "901", "01"))
    with pytest.raises(RequestError, match="Data Owner"):
        change_category(db_session, req.id, subgroup_id=other_group_sub.id,
                        account=account_for(db_session, "administrator"))
    db_session.refresh(req)
    assert req.generated_code == code and req.group.code == "900"
    assert (_register(db_session, "900", "01"), _register(db_session, "901", "01")) == before


def test_uncoded_request_may_move_to_another_item_group(db_session):
    req = _submit(db_session, "900", "01")
    other_group_sub = central_ids(db_session, "APM", "901", "01")[3]
    change_category(db_session, req.id, subgroup_id=other_group_sub.id,
                    account=account_for(db_session))
    db_session.refresh(req)
    assert (req.group.code, req.subgroup.code) == ("901", "01")


def test_coded_picker_offers_only_the_same_item_group(client, app_db):
    coded = _approved(app_db, "900", "01")
    page = client.get(f"/queue/{coded.id}").text
    assert "900-02" in page and "901-01" not in page
    uncoded = _submit(app_db, "900", "01")
    assert "901-01" in client.get(f"/queue/{uncoded.id}").text


# --- Rejecting an approved request (burns its code) --------------------------------

def test_administrator_rejects_approved_request_with_reason_and_code_is_burned(db_session):
    req = _approved(db_session)
    code, before = req.generated_code, _register(db_session)
    change_status(db_session, req.id, new_status="rejected", note="ผิด Group ต้องส่งใหม่",
                  account=account_for(db_session, "administrator"))
    assert req.status == "rejected" and req.review_note == "ผิด Group ต้องส่งใหม่"
    assert req.generated_code == code  # kept, so the number can never be reused
    burned = [e.detail for e in req.events if e.action == "code_burned"]
    assert burned and code in burned[0] and "ทิ้งถาวร" in burned[0]
    assert _register(db_session) == before  # never moves backwards

    nxt = _approved(db_session)
    assert nxt.generated_code != code
    assert _register(db_session) == before + 1


def test_procurement_cannot_reject_an_approved_request(db_session):
    req = _approved(db_session)
    with pytest.raises(RequestForbidden):
        change_status(db_session, req.id, new_status="rejected", note="x",
                      account=account_for(db_session))
    db_session.refresh(req)
    assert req.status == "approved"


@pytest.mark.parametrize("note", [None, "", "   "])
def test_rejecting_an_approved_request_needs_a_reason(db_session, note):
    req = _approved(db_session)
    with pytest.raises(RequestError, match="เหตุผล"):
        change_status(db_session, req.id, new_status="rejected", note=note,
                      account=account_for(db_session, "administrator"))
    db_session.refresh(req)
    assert req.status == "approved"


def test_exported_request_cannot_be_rejected(db_session):
    req = _approved(db_session)
    export_pending(db_session, req.factory_id, account=account_for(db_session))
    with pytest.raises(RequestError):
        change_status(db_session, req.id, new_status="rejected", note="x",
                      account=account_for(db_session, "administrator"))
    db_session.refresh(req)
    assert req.status == "exported"


def test_reject_button_on_approved_request_is_administrator_only(client_as, app_db):
    req = _approved(app_db)
    assert 'value="rejected"' in client_as("administrator").get(f"/queue/{req.id}").text
    assert 'value="rejected"' not in client_as("procurement").get(f"/queue/{req.id}").text
    r = client_as("procurement").post(f"/queue/{req.id}/status",
                                      data={"new_status": "rejected", "note": "x"})
    assert r.status_code == 403


def test_cross_group_refusal_tells_to_reject_and_resubmit(db_session):
    req = _approved(db_session, "900", "01")
    with pytest.raises(RequestError, match="ไม่อนุมัติ.*ส่งคำขอใหม่"):
        change_category(db_session, req.id,
                        subgroup_id=central_ids(db_session, "APM", "901", "01")[3].id,
                        account=account_for(db_session, "administrator"))


# --- Showing a burned code -----------------------------------------------------------

def _reject_approved(db) -> ItemRequest:
    req = _approved(db)
    return change_status(db, req.id, new_status="rejected", note="ผิด Group",
                         account=account_for(db, "administrator"))


def test_burned_code_is_struck_through_on_detail_and_queue(client, app_db):
    req = _reject_approved(app_db)
    for page in (client.get(f"/queue/{req.id}").text, client.get("/queue").text):
        assert f"<s><code>{req.generated_code}</code></s>" in page
        assert "ยกเลิกแล้ว ห้ามใช้" in page
        assert f'background:#e1f5ee; padding:2px 10px; border-radius:6px;">{req.generated_code}' not in page
    assert "เหตุผล: ผิด Group" in client.get("/queue").text


def test_usable_code_is_not_marked_cancelled(client, app_db):
    req = _approved(app_db)
    page = client.get(f"/queue/{req.id}").text
    assert req.generated_code in page and "ยกเลิกแล้ว ห้ามใช้" not in page
