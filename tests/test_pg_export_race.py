"""PostgreSQL: an export of a Plant's approved requests and a change to one of
them never interleave, and no exported request ends up with a code different
from the one in its export file (STORY-006 ticket 03, AC 4; locks from
STORY-001 ticket 03).

The file is built from the database when it is downloaded (rows with the
batch's id), so "the file" here is that workbook, built the same way.
Expected values follow the existing rules: a request with a code moves only
within its Item Group, gets a new code from the new Sub-Category's register,
and its old code is retired "reissued"; once exported it cannot move.
"""

import io
from collections.abc import Callable

import pytest
from openpyxl import load_workbook
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.models import ItemRequest, RetiredCode, RunningRegister
from app.services.codegen import central_code
from app.services.exporter import build_workbook_bytes, export_pending
from app.services.requests import (
    RequestError,
    change_category,
    change_status,
    submit_request,
)
from tests.conftest import account_for, central_ids
from tests.pg_race import Race, session_on

pytestmark = pytest.mark.postgres

PLANT, GROUP, FROM_SUB, TO_SUB = "APM", "900", "01", "02"


def _register_last(db: Session, sub: str) -> int:
    return db.scalar(select(RunningRegister.last_running).where(
        RunningRegister.group_code == GROUP, RunningRegister.sub_code == sub)) or 0


def _submit(db: Session) -> int:
    factory, system, group, sub = central_ids(db, PLANT, GROUP, FROM_SUB)
    return submit_request(db, account_for(db), factory_id=factory.id, code_system_id=system.id,
                          group_id=group.id, subgroup_id=sub.id, item_name="Ball Bearing").id


def _approve(request_id: int) -> Callable[[Session], str]:
    def run(db: Session) -> str:
        return change_status(db, request_id, new_status="approved",
                             account=account_for(db, "administrator")).generated_code
    return run


def _export(db: Session) -> int:
    factory, *_ = central_ids(db, PLANT, GROUP, FROM_SUB)
    return export_pending(db, factory.id, account=account_for(db, "administrator")).id


def _move_to_other_sub(request_id: int) -> Callable[[Session], str]:
    def run(db: Session) -> str:
        *_, sub = central_ids(db, PLANT, GROUP, TO_SUB)
        return change_category(db, request_id, subgroup_id=sub.id,
                               account=account_for(db, "administrator")).req.generated_code
    return run


def _request(engine: Engine, request_id: int) -> ItemRequest:
    with session_on(engine) as db:
        return db.get(ItemRequest, request_id)


def _codes_in_file(engine: Engine, batch_id: int) -> set[str]:
    """Every cell value of the batch's workbook, built as the download builds it."""
    with session_on(engine) as db:
        reqs = list(db.scalars(select(ItemRequest).where(ItemRequest.export_batch_id == batch_id)))
        data = build_workbook_bytes(db, PLANT, reqs)
    wb = load_workbook(io.BytesIO(data), read_only=True)
    return {str(v) for ws in wb.worksheets for row in ws.iter_rows(values_only=True)
            for v in row if v is not None}


def _retired(engine: Engine, codes: list[str]) -> dict[str, str]:
    with session_on(engine) as db:
        return {r.code: r.reason for r in db.scalars(
            select(RetiredCode).where(RetiredCode.code.in_(codes)))}


def _setup(engine: Engine, approved: int = 1, submitted: int = 0) -> list[int]:
    with session_on(engine) as db:
        account_for(db, "administrator")  # created before the race, not inside it
        ids = [_submit(db) for _ in range(approved + submitted)]
        for request_id in ids[:approved]:
            _approve(request_id)(db)
    return ids


def test_export_first_then_the_waiting_move_is_refused_and_the_file_keeps_the_code(
        pg_engine: Engine) -> None:
    (r1,) = _setup(pg_engine)
    code = _request(pg_engine, r1).generated_code
    with session_on(pg_engine) as db:
        to_sub_last = _register_last(db, TO_SUB)

    with Race(pg_engine) as race:
        batch_id, outcome = race.run(_export, _move_to_other_sub(r1))

    assert isinstance(outcome, RequestError), outcome
    assert "เปลี่ยนหมวดไม่ได้หลัง export แล้ว" in str(outcome)
    req = _request(pg_engine, r1)
    assert (req.status, req.export_batch_id, req.generated_code) == ("exported", batch_id, code)
    assert code in _codes_in_file(pg_engine, batch_id)
    with session_on(pg_engine) as db:
        assert _register_last(db, TO_SUB) == to_sub_last
    assert _retired(pg_engine, [code, central_code(GROUP, TO_SUB, to_sub_last + 1)]) == {}


def test_move_first_then_the_waiting_export_writes_the_new_code(pg_engine: Engine) -> None:
    (r1,) = _setup(pg_engine)
    old = _request(pg_engine, r1).generated_code
    with session_on(pg_engine) as db:
        new = central_code(GROUP, TO_SUB, _register_last(db, TO_SUB) + 1)

    with Race(pg_engine) as race:
        moved, batch_id = race.run(_move_to_other_sub(r1), _export)

    assert moved == new
    assert isinstance(batch_id, int), batch_id
    req = _request(pg_engine, r1)
    assert (req.status, req.export_batch_id, req.generated_code) == ("exported", batch_id, new)
    in_file = _codes_in_file(pg_engine, batch_id)
    assert new in in_file and old not in in_file
    assert _retired(pg_engine, [old, new]) == {old: "reissued"}


def test_approval_during_an_export_neither_blocks_nor_joins_that_batch(pg_engine: Engine) -> None:
    r1, r2 = _setup(pg_engine, approved=1, submitted=1)
    r1_code = _request(pg_engine, r1).generated_code

    # Expected from the code: the export locks only rows already committed as
    # approved; R2 is still "submitted" for it while the Approval holds.
    with Race(pg_engine) as race:
        r2_code, first_batch = race.run_without_wait(_approve(r2), _export)

    assert isinstance(first_batch, int), first_batch
    req1, req2 = _request(pg_engine, r1), _request(pg_engine, r2)
    assert (req1.status, req1.export_batch_id) == ("exported", first_batch)
    assert (req2.status, req2.export_batch_id, req2.generated_code) == ("approved", None, r2_code)
    first_file = _codes_in_file(pg_engine, first_batch)
    assert r1_code in first_file and r2_code not in first_file

    with session_on(pg_engine) as db:
        second_batch = _export(db)
    req2 = _request(pg_engine, r2)
    assert (req2.status, req2.export_batch_id, req2.generated_code) == (
        "exported", second_batch, r2_code)
    assert r2_code in _codes_in_file(pg_engine, second_batch)
