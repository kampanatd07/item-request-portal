"""PostgreSQL: a Code Override and an Approval in the same Sub-Category at the
same moment never issue one number twice, and never retire a number in use
(STORY-006 ticket 02, AC 4; locks from STORY-010 ticket 03).

Expected values follow the STORY-010 rules as tested on SQLite in
tests/test_override_checks.py and tests/test_retired_codes.py: the replaced
code is retired "overridden"; when the override moves the register up, each
number in between that the group master does not hold and that is not
already used is retired "skipped"; ≤ SKIP_CONFIRM_LIMIT of them needs no
confirmation. Here the register is `last` right after R1's Approval (R1 holds
code(last)) and the group master holds X = code(last + 2).
"""

from collections.abc import Callable

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ItemRequest, RetiredCode, RunningRegister
from app.services.override_preview import plan_of
from app.services.requests import (
    RequestError,
    change_status,
    check_override,
    override_code,
    submit_request,
)
from tests.conftest import account_for, central_ids, load_master
from tests.pg_race import Race, session_on

pytestmark = pytest.mark.postgres

REASON = "มีรหัสใน master ของกลุ่มแล้ว"


def _code(n: int) -> str:
    return f"9000100{n:04d}"


def _submit(db: Session) -> int:
    factory, system, group, sub = central_ids(db, "APM", "900", "01")
    return submit_request(db, account_for(db), factory_id=factory.id, code_system_id=system.id,
                          group_id=group.id, subgroup_id=sub.id, item_name="Ball Bearing").id


def _approve(request_id: int) -> Callable[[Session], str]:
    def run(db: Session) -> str:
        return change_status(db, request_id, new_status="approved",
                             account=account_for(db, "administrator")).generated_code
    return run


def _override(request_id: int, code: str, expected: dict | None = None) -> Callable[[Session], str]:
    def run(db: Session) -> str:
        return override_code(db, request_id, new_code=code, reason=REASON, expected=expected,
                             account=account_for(db, "administrator")).generated_code
    return run


def _setup(engine) -> tuple[int, int, int]:
    """R1 approved (holds code(last)), R2 submitted, X = code(last + 2) in the
    group master. Returns (r1, r2, last)."""
    with session_on(engine) as db:
        account_for(db, "administrator")  # created before the race, not inside it
        r1, r2 = _submit(db), _submit(db)
        _approve(r1)(db)
        last = db.scalar(select(RunningRegister.last_running).where(
            RunningRegister.group_code == "900", RunningRegister.sub_code == "01"))
        load_master(db, [_code(last + 2)])
    return r1, r2, last


def _state(engine) -> tuple[dict[int, str | None], int, dict[str, str]]:
    """(code per request id, register last, retired code -> reason), as committed."""
    with session_on(engine) as db:
        codes = {r.id: r.generated_code for r in db.scalars(select(ItemRequest))}
        last = db.scalar(select(RunningRegister.last_running).where(
            RunningRegister.group_code == "900", RunningRegister.sub_code == "01"))
        retired = {r.code: r.reason for r in db.scalars(select(RetiredCode))}
    return codes, last, retired


def _no_number_twice(codes: dict[int, str | None], retired: dict[str, str]) -> None:
    on_requests = [c for c in codes.values() if c]
    assert len(on_requests) == len(set(on_requests)), codes
    assert not set(on_requests) & set(retired), (codes, retired)


def test_override_first_then_the_waiting_approval_takes_the_next_free_number(pg_engine):
    r1, r2, last = _setup(pg_engine)
    x = _code(last + 2)

    with Race(pg_engine) as race:
        overridden, approved = race.run(_override(r1, x), _approve(r2))

    assert overridden == x
    assert approved == _code(last + 3), approved
    codes, register, retired = _state(pg_engine)
    assert codes == {r1: x, r2: _code(last + 3)}
    assert register == last + 3
    assert retired == {_code(last): "overridden", _code(last + 1): "skipped"}
    _no_number_twice(codes, retired)


def test_approval_first_then_the_waiting_override_never_retires_the_new_number(pg_engine):
    r1, r2, last = _setup(pg_engine)
    x = _code(last + 2)

    with Race(pg_engine) as race:
        approved, overridden = race.run(_approve(r2), _override(r1, x))

    assert approved == _code(last + 1)
    assert overridden == x, overridden
    codes, register, retired = _state(pg_engine)
    assert codes == {r1: x, r2: _code(last + 1)}
    assert register == last + 2
    # The override read the register after the Approval committed: nothing
    # lies between it and X any more, so only the replaced code is retired.
    assert _code(last + 1) not in retired
    assert retired == {_code(last): "overridden"}
    _no_number_twice(codes, retired)


def test_override_confirmed_on_a_stale_preview_is_refused_after_the_approval(pg_engine):
    r1, r2, last = _setup(pg_engine)
    x = _code(last + 2)
    with session_on(pg_engine) as db:
        # What the screen showed: register at `last`, code(last + 1) to throw away.
        shown = plan_of(check_override(db, db.get(ItemRequest, r1), x))

    with Race(pg_engine) as race:
        approved, outcome = race.run(_approve(r2), _override(r1, x, expected=shown))

    assert approved == _code(last + 1)
    assert isinstance(outcome, RequestError), outcome
    assert "ข้อมูลเปลี่ยนไปหลังตรวจรหัส" in str(outcome)
    codes, register, retired = _state(pg_engine)
    assert codes == {r1: _code(last), r2: _code(last + 1)}
    assert register == last + 1
    assert retired == {}
    _no_number_twice(codes, retired)
