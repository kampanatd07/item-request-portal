"""STORY-010 ticket 03: override accepts only a real group code, and the register keeps up."""

import pytest
from sqlalchemy import event, func, select

from app.models import ItemRequest, ItemSnapshot, RequestEvent, RetiredCode, RunningRegister, SnapshotImport
from app.services.codegen import retire_code
from app.services.requests import (
    SKIP_CONFIRM_LIMIT,
    RequestError,
    change_category,
    change_status,
    check_override,
    override_code,
    submit_request,
)
from tests.conftest import account_for, central_ids, load_master, next_code

REASON = "มีรหัสใน master ของกลุ่มแล้ว"


def _submit(db, sub_code="01"):
    factory, system, group, sub = central_ids(db, "APM", "900", sub_code)
    return submit_request(db, account_for(db), factory_id=factory.id, code_system_id=system.id,
                          group_id=group.id, subgroup_id=sub.id, item_name="Ball Bearing")


def _approved(db, sub_code="01"):
    return change_status(db, _submit(db, sub_code).id, new_status="approved",
                         account=account_for(db, "administrator"))


def _last(db, sub="01") -> int:
    return db.scalar(select(RunningRegister.last_running).where(
        RunningRegister.group_code == "900", RunningRegister.sub_code == sub))


def _code(n: int, sub="01") -> str:
    return f"900{sub}00{n:04d}"


def _state(db, req) -> tuple:
    db.expire_all()
    return (db.get(ItemRequest, req.id).generated_code, _last(db),
            db.scalar(select(func.count(RetiredCode.id))),
            db.scalar(select(func.count(RequestEvent.id))))


def _override(db, req, code, **kw):
    kw.setdefault("reason", REASON)
    return override_code(db, req.id, new_code=code, account=account_for(db, "administrator"), **kw)


def _plant_snapshot(db, codes, source="D365"):
    imp = SnapshotImport(source=source, filename="ax.xlsx", row_count=len(codes),
                         uploaded_by="t@test.local")
    db.add(imp)
    db.flush()
    for c in codes:
        db.add(ItemSnapshot(source=source, item_number=c, name="in AX", normalized_name="in ax",
                            import_id=imp.id))
    db.commit()


# --- Each rule refuses and changes nothing --------------------------------------------------------

@pytest.mark.parametrize("make_code,reason,message", [
    (lambda db: next_code(db), "", "เหตุผล"),
    (lambda db: "9000100001", REASON, "11 หลัก"),
    (lambda db: "9000100001A", REASON, "11 หลัก"),
    (lambda db: "90101000001", REASON, "ไม่ตรงกับหมวด"),
    (lambda db: "90002000001", REASON, "ไม่ตรงกับหมวด"),
    (lambda db: "90001010001", REASON, "หลัก 6–7"),
    (lambda db: _code(1234), REASON, "ไม่พบรหัส"),        # not in the master
])
def test_rule_refuses_and_nothing_changes(db_session, make_code, reason, message):
    req = _approved(db_session)
    load_master(db_session, [next_code(db_session)])
    before = _state(db_session, req)
    with pytest.raises(RequestError, match=message):
        _override(db_session, req, make_code(db_session), reason=reason)
    assert _state(db_session, req) == before


def test_no_master_uploaded_refuses(db_session):
    req = _approved(db_session)
    before = _state(db_session, req)
    with pytest.raises(RequestError, match="ยังไม่มี Master"):
        _override(db_session, req, next_code(db_session))
    assert _state(db_session, req) == before


def test_code_already_in_this_plants_ax_is_refused_with_advice_to_reject(db_session):
    req = _approved(db_session)  # APM -> D365 snapshot
    x = next_code(db_session)
    load_master(db_session, [x])
    _plant_snapshot(db_session, [x])
    before = _state(db_session, req)
    with pytest.raises(RequestError, match="มีอยู่ในระบบของโรงงาน APM.*ไม่อนุมัติ") as e:
        _override(db_session, req, x)
    assert f'"ซ้ำกับ {x}"' in str(e.value) and "{code}" not in str(e.value)
    assert _state(db_session, req) == before


def test_no_plant_snapshot_warns_but_allows(db_session):
    req = _approved(db_session)
    x = next_code(db_session)
    load_master(db_session, [x])
    check = check_override(db_session, req, x)
    assert check.ok and any("ยังไม่มี snapshot ของโรงงาน APM" in w for w in check.warnings)
    _override(db_session, req, x)
    assert req.generated_code == x


def test_plant_snapshot_without_the_code_passes_silently(db_session):
    req = _approved(db_session)
    x = next_code(db_session)
    load_master(db_session, [x])
    _plant_snapshot(db_session, ["64000123"])
    check = check_override(db_session, req, x)
    assert check.ok and check.warnings == []


def test_retired_code_is_refused(db_session):
    req = _approved(db_session)
    x = next_code(db_session)
    load_master(db_session, [x])
    retire_code(db_session, x, request_id=None, reason="skipped", actor="a@test.local")
    db_session.commit()
    with pytest.raises(RequestError, match="ถูกทิ้งไปแล้ว"):
        _override(db_session, req, x)


def test_code_on_another_request_is_refused(db_session):
    first, second = _approved(db_session), _approved(db_session)
    load_master(db_session, [first.generated_code])
    before = _state(db_session, second)
    with pytest.raises(RequestError, match="ถูกใช้กับคำขออื่น"):
        _override(db_session, second, first.generated_code)
    assert _state(db_session, second) == before


# --- Register: below/equal untouched, above moves and retires only what the master lacks ---------

def test_code_at_or_below_the_register_leaves_it(db_session):
    req = _approved(db_session)
    last = _last(db_session)
    x = _code(last - 50)
    load_master(db_session, [x])
    _override(db_session, req, x)
    assert req.generated_code == x and _last(db_session) == last
    reasons = sorted(r.reason for r in db_session.scalars(select(RetiredCode)))
    assert reasons == ["overridden"]  # only the replaced code


def test_above_the_register_moves_it_and_retires_only_numbers_not_in_the_master(db_session):
    req = _approved(db_session)
    y, last = req.generated_code, _last(db_session)
    x = _code(last + 5)
    in_master_between = _code(last + 2)
    load_master(db_session, [x, in_master_between])

    check = check_override(db_session, req, x)
    assert check.to_retire == [_code(last + 1), _code(last + 3), _code(last + 4)]
    assert check.skipped_in_master == 1 and check.advances_register
    assert not check.needs_confirmation

    _override(db_session, req, x)
    assert _last(db_session) == last + 5
    retired = {r.code: r.reason for r in db_session.scalars(select(RetiredCode))}
    assert retired == {_code(last + 1): "skipped", _code(last + 3): "skipped",
                       _code(last + 4): "skipped", y: "overridden"}
    assert in_master_between not in retired  # a real code in use, never retired
    detail = db_session.scalar(select(RequestEvent.detail).where(
        RequestEvent.action == "register_advanced"))
    assert f"{last} -> {last + 5}" in detail and "ทิ้ง 3" in detail and "มีใน Master 1" in detail


def test_confirmation_threshold_counts_only_numbers_to_throw_away(db_session):
    req = _approved(db_session)
    last = _last(db_session)
    # 12 numbers between; 2 are in the master, so exactly 10 would be thrown away.
    x = _code(last + 13)
    load_master(db_session, [x, _code(last + 4), _code(last + 8)])
    check = check_override(db_session, req, x)
    assert len(check.to_retire) == SKIP_CONFIRM_LIMIT and not check.needs_confirmation
    _override(db_session, req, x)
    assert _last(db_session) == last + 13


def test_more_than_ten_to_throw_away_needs_confirmation(db_session):
    req = _approved(db_session)
    last = _last(db_session)
    x = _code(last + 12)  # 11 numbers would be thrown away
    load_master(db_session, [x])
    assert check_override(db_session, req, x).needs_confirmation
    before = _state(db_session, req)
    with pytest.raises(RequestError, match="11 ตัว.*ยืนยัน"):
        _override(db_session, req, x)
    assert _state(db_session, req) == before
    _override(db_session, req, x, confirm_skip=True)
    assert _last(db_session) == last + 12
    assert db_session.scalar(select(func.count(RetiredCode.id)).where(
        RetiredCode.reason == "skipped")) == 11


def test_check_override_is_read_only(db_session):
    req = _approved(db_session)
    x = _code(_last(db_session) + 20)
    load_master(db_session, [x])
    before = _state(db_session, req)
    check_override(db_session, req, x)
    assert _state(db_session, req) == before


def test_override_event_carries_the_reason(db_session):
    req = _approved(db_session)
    x = next_code(db_session)
    load_master(db_session, [x])
    _override(db_session, req, x, reason="  item มีใน   master  ")
    detail = db_session.scalar(select(RequestEvent.detail).where(
        RequestEvent.action == "code_overridden"))
    assert detail.endswith("เหตุผล: item มีใน master")
    assert req.review_note is None  # the reason is for the audit trail, not the requester


# --- Minting guard ------------------------------------------------------------------------------

@pytest.mark.parametrize("blocker", ["retired", "request", "master"])
def test_approval_refuses_when_the_next_number_is_taken_and_register_stays(db_session, blocker):
    req = _submit(db_session)
    last = _last(db_session)
    taken = _code(last + 1)
    if blocker == "retired":
        retire_code(db_session, taken, request_id=None, reason="skipped", actor="a@test.local")
        db_session.commit()
    elif blocker == "request":
        other = _submit(db_session)
        other.generated_code = taken  # e.g. an old unvalidated override
        db_session.commit()
    else:
        load_master(db_session, [taken])
    with pytest.raises(RequestError, match="900-01.*ตามหลัง.*STORY-005"):
        change_status(db_session, req.id, new_status="approved",
                      account=account_for(db_session, "administrator"))
    assert _last(db_session) == last
    db_session.refresh(req)
    assert req.status == "submitted" and req.generated_code is None


def test_reissue_refuses_when_the_next_number_is_taken_and_registers_stay(db_session):
    req = _approved(db_session, "01")
    last01, last02 = _last(db_session, "01"), _last(db_session, "02")
    load_master(db_session, [_code(last02 + 1, "02")])
    with pytest.raises(RequestError, match="900-02.*ตามหลัง"):
        change_category(db_session, req.id, subgroup_id=central_ids(db_session, "APM", "900", "02")[3].id,
                        account=account_for(db_session, "administrator"))
    assert (_last(db_session, "01"), _last(db_session, "02")) == (last01, last02)
    db_session.refresh(req)
    assert req.subgroup.code == "01"


# --- Lock order: request row, then register row --------------------------------------------------

def _locked_tables(db, action) -> list[str]:
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.orm import Session

    seen: list[str] = []

    def _capture(state):
        if state.is_select:
            sql = str(state.statement.compile(dialect=postgresql.dialect()))
            if "FOR UPDATE" in sql:
                for table in ("item_requests", "running_register"):
                    if f"FROM {table}" in sql:
                        seen.append(table)

    event.listen(Session, "do_orm_execute", _capture)
    try:
        action()
    finally:
        event.remove(Session, "do_orm_execute", _capture)
    return seen


def test_lock_order_is_request_then_register_everywhere(db_session):
    admin = account_for(db_session, "administrator")
    a = _submit(db_session)
    assert _locked_tables(db_session, lambda: change_status(
        db_session, a.id, new_status="approved", account=admin)) == ["item_requests", "running_register"]
    assert _locked_tables(db_session, lambda: change_category(
        db_session, a.id, subgroup_id=central_ids(db_session, "APM", "900", "02")[3].id,
        account=admin)) == ["item_requests", "running_register"]
    x = next_code(db_session, "900", "02")
    load_master(db_session, [x])
    assert _locked_tables(db_session, lambda: _override(db_session, a, x)) == [
        "item_requests", "running_register"]


# --- HTTP -----------------------------------------------------------------------------------------

def test_route_requires_a_reason_and_passes_confirmation(client, app_db):
    req = _approved(app_db)
    last = _last(app_db)
    x = _code(last + 12)
    load_master(app_db, [x])
    r = client.post(f"/queue/{req.id}/code", data={"new_code": x})
    assert r.status_code == 422 and "เหตุผล" in r.text
    r = client.post(f"/queue/{req.id}/code", data={"new_code": x, "reason": REASON})
    assert r.status_code == 422 and "ยืนยัน" in r.text
    r = client.post(f"/queue/{req.id}/code", data={"new_code": x, "reason": REASON,
                                                 "confirm_skip": "1"})
    assert r.status_code == 200 and x in r.text


def test_preview_reports_a_code_on_another_request(db_session):
    # The DB unique constraint would also refuse at save time; the preview must
    # say so before the Administrator confirms (ticket 04).
    first, second = _approved(db_session), _approved(db_session)
    load_master(db_session, [first.generated_code])
    check = check_override(db_session, second, first.generated_code)
    assert not check.ok and "ถูกใช้กับคำขออื่น" in check.errors[0]


def test_override_reads_the_register_only_under_its_lock(db_session):
    # check_override reads register.last_running; inside override_code that read
    # must come after the register row is locked, or it could act on a stale value.
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.orm import Session

    req = _approved(db_session)
    x = _code(_last(db_session) + 3)
    load_master(db_session, [x])
    reads: list[bool] = []

    def _capture(state):
        if state.is_select:
            sql = str(state.statement.compile(dialect=postgresql.dialect()))
            if "FROM running_register" in sql:
                reads.append("FOR UPDATE" in sql)

    event.listen(Session, "do_orm_execute", _capture)
    try:
        _override(db_session, req, x)
    finally:
        event.remove(Session, "do_orm_execute", _capture)
    assert reads and reads[0] is True



def test_preview_refuses_a_request_that_is_not_approved(db_session):
    req = _submit(db_session)
    load_master(db_session, [next_code(db_session)])
    check = check_override(db_session, req, next_code(db_session))
    assert not check.ok and "อนุมัติแล้ว" in check.errors[0]


def test_big_confirmed_jump_uses_a_few_queries_not_one_per_number(db_session):
    from sqlalchemy.orm import Session

    req = _approved(db_session)
    last = _last(db_session)
    x = _code(last + 3001)  # 3,000 numbers skipped
    load_master(db_session, [x])
    selects: list[int] = []

    def _count(state):
        if state.is_select:
            selects.append(1)

    event.listen(Session, "do_orm_execute", _count)
    try:
        _override(db_session, req, x, confirm_skip=True)
    finally:
        event.remove(Session, "do_orm_execute", _count)
    assert db_session.scalar(select(func.count(RetiredCode.id)).where(
        RetiredCode.reason == "skipped")) == 3000
    assert len(selects) < 100  # was ~9,000 (two per number, then one more each)
