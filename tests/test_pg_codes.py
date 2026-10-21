"""PostgreSQL: Central Codes stay unique when Approvals overlap (STORY-006 AC 2)."""

from collections.abc import Callable

import pytest
from sqlalchemy.orm import Session

from app.services.requests import change_status, submit_request
from tests.conftest import account_for, central_ids
from tests.pg_race import Race, session_on

pytestmark = pytest.mark.postgres


def _submit(db: Session, group_code: str = "900", sub_code: str = "01") -> int:
    factory, system, group, sub = central_ids(db, "APM", group_code, sub_code)
    return submit_request(
        db, account=account_for(db), factory_id=factory.id, code_system_id=system.id,
        group_id=group.id, subgroup_id=sub.id, item_name="Test item",
    ).id


def _approve(request_id: int) -> Callable[[Session], str]:
    def run(db: Session) -> str:
        return change_status(db, request_id, new_status="approved",
                             account=account_for(db, "administrator")).generated_code
    return run


def test_two_overlapping_approvals_in_one_subcategory_get_consecutive_codes(pg_engine):
    with session_on(pg_engine) as setup:
        first, second = _submit(setup), _submit(setup)
        account_for(setup, "administrator")  # created before the race, not inside it

    with Race(pg_engine) as race:
        code_a, code_b = race.run(_approve(first), _approve(second))

    assert isinstance(code_b, str), code_b
    assert code_a != code_b
    assert code_a[:7] == code_b[:7] == "9000100"
    assert int(code_b[7:]) == int(code_a[7:]) + 1
