"""STORY-010 ticket 01: every thrown-away Central Code becomes a Retired Code."""

from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.models import RequestEvent, RetiredCode, RunningRegister
from app.services.codegen import CodegenError, is_retired, retire_code
from app.services.requests import (
    RequestError,
    RequestForbidden,
    change_category,
    change_status,
    override_code,
    submit_request,
)
from tests.conftest import account_for, central_ids, load_master, next_code


def _approved(db, sub_code: str = "01"):
    factory, system, group, sub = central_ids(db, "APM", "900", sub_code)
    req = submit_request(db, account_for(db), factory_id=factory.id, code_system_id=system.id,
                         group_id=group.id, subgroup_id=sub.id, item_name="Ball Bearing")
    return change_status(db, req.id, new_status="approved",
                         account=account_for(db, "administrator"))


def _retired(db) -> list[tuple[str, str, int | None, str]]:
    return [(r.code, r.reason, r.request_id, r.actor)
            for r in db.scalars(select(RetiredCode).order_by(RetiredCode.id))]


# --- Every burn point writes exactly one Retired Code ---------------------------------------

def test_reissue_retires_the_old_code(db_session):
    admin = account_for(db_session, "administrator")
    req = _approved(db_session)
    old = req.generated_code
    change_category(db_session, req.id, subgroup_id=central_ids(db_session, "APM", "900", "02")[3].id,
                    account=admin)
    assert _retired(db_session) == [(old, "reissued", req.id, admin.email)]
    assert is_retired(db_session, old) and not is_retired(db_session, req.generated_code)


def test_reject_after_approval_retires_the_code_and_keeps_it_on_the_request(db_session):
    admin = account_for(db_session, "administrator")
    req = _approved(db_session)
    change_status(db_session, req.id, new_status="rejected", note="ซ้ำ", account=admin)
    assert _retired(db_session) == [(req.generated_code, "rejected", req.id, admin.email)]
    assert req.generated_code  # still on the request (unique constraint)


def test_override_retires_the_replaced_code(db_session):
    admin = account_for(db_session, "administrator")
    req = _approved(db_session)
    old = req.generated_code
    x = next_code(db_session)
    load_master(db_session, [x])
    override_code(db_session, req.id, new_code=x, reason="มีใน master แล้ว", account=admin)
    assert _retired(db_session) == [(old, "overridden", req.id, admin.email)]


def test_override_to_the_same_code_changes_nothing(db_session):
    req = _approved(db_session)
    override_code(db_session, req.id, new_code=req.generated_code,
                  account=account_for(db_session, "administrator"))
    assert _retired(db_session) == []
    assert not [e for e in req.events if e.action == "code_overridden"]


def test_reject_before_approval_retires_nothing(db_session):
    factory, system, group, sub = central_ids(db_session)
    req = submit_request(db_session, account_for(db_session), factory_id=factory.id,
                         code_system_id=system.id, group_id=group.id, subgroup_id=sub.id,
                         item_name="Ball Bearing")
    change_status(db_session, req.id, new_status="rejected", account=account_for(db_session))
    assert _retired(db_session) == []


# --- Refusals and failures write nothing ------------------------------------------------------

def test_refused_action_writes_nothing(db_session):
    req = _approved(db_session)
    with pytest.raises(RequestForbidden):
        change_category(db_session, req.id,
                        subgroup_id=central_ids(db_session, "APM", "900", "02")[3].id,
                        account=account_for(db_session))  # Procurement
    assert _retired(db_session) == []


def test_failed_change_rolls_back_the_retired_code_too(db_session):
    # Override onto a code another request holds: the unique constraint on the
    # request refuses it, and the Retired Code of the replaced number must go too.
    first, second = _approved(db_session), _approved(db_session)
    kept = second.generated_code
    load_master(db_session, [first.generated_code])
    with pytest.raises(RequestError, match="ถูกใช้"):
        override_code(db_session, second.id, new_code=first.generated_code, reason="ทดสอบ",
                      account=account_for(db_session, "administrator"))
    assert _retired(db_session) == []
    db_session.refresh(second)
    assert second.generated_code == kept


def test_retiring_a_code_twice_is_a_thai_error_not_a_500(db_session):
    admin = account_for(db_session, "administrator")
    retire_code(db_session, "90001000123", request_id=None, reason="skipped", actor=admin.email)
    with pytest.raises(CodegenError, match="ถูกทิ้งไปแล้ว"):
        retire_code(db_session, "90001000123", request_id=None, reason="skipped",
                    actor=admin.email)


def test_unique_constraint_backs_up_the_check(db_session):
    db_session.add(RetiredCode(code="90001000124", reason="skipped", actor="a@test.local"))
    db_session.flush()
    db_session.add(RetiredCode(code="90001000124", reason="skipped", actor="a@test.local"))
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_retired_code_during_reissue_is_refused_in_thai_and_rolls_back(db_session):
    # If the number being thrown away is somehow already retired, the whole
    # re-categorise is refused and the register does not move.
    admin = account_for(db_session, "administrator")
    req = _approved(db_session)
    retire_code(db_session, req.generated_code, request_id=None, reason="skipped",
                actor=admin.email)
    db_session.commit()
    reg = db_session.scalar(select(RunningRegister).where(
        RunningRegister.group_code == "900", RunningRegister.sub_code == "02"))
    before = reg.last_running
    with pytest.raises(RequestError, match="ถูกทิ้งไปแล้ว"):
        change_category(db_session, req.id,
                        subgroup_id=central_ids(db_session, "APM", "900", "02")[3].id,
                        account=admin)
    db_session.refresh(reg)
    assert reg.last_running == before


def test_unknown_reason_is_a_programming_error(db_session):
    with pytest.raises(ValueError):
        retire_code(db_session, "90001000125", request_id=None, reason="lost", actor="a@x.co")


# --- Migration backfill -----------------------------------------------------------------------

def test_migration_backfills_from_existing_events(tmp_path, monkeypatch, capsys):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine

    url = f"sqlite:///{(tmp_path / 'backfill.db').as_posix()}"
    monkeypatch.setattr(settings, "database_url", url)
    cfg = Config(str(Path(__file__).resolve().parent.parent / "alembic.ini"))
    command.upgrade(cfg, "2c0198e8b4a2")  # the revision before retired_codes

    engine = create_engine(url)
    try:
        with engine.begin() as c:
            def request(code, status):
                c.execute(text(
                    "INSERT INTO item_requests (requester_name, requester_email, factory_id, "
                    "code_system_id, group_id, item_name, status, generated_code) "
                    "VALUES ('t', 't@x.co', 1, 1, 1, 'x', :s, :g)"), {"s": status, "g": code})
                return c.execute(text("SELECT max(id) FROM item_requests")).scalar()

            live = request("90002000001", "approved")        # carries the reissued code
            burned = request("90001000009", "rejected")      # rejected after approval
            back = request("90001000006", "approved")        # overridden back to an old code

            def event(rid, action, detail, at):
                c.execute(text(
                    "INSERT INTO request_events (request_id, actor, action, detail, at) "
                    "VALUES (:r, 'peter@test.local', :a, :d, :t)"),
                    {"r": rid, "a": action, "d": detail, "t": at})

            event(live, "code_reissued", "90001000005 -> 90002000001", "2026-09-01 10:00:00")
            event(live, "code_reissued", "90001000005 -> 90002000001", "2026-09-02 10:00:00")
            event(back, "code_overridden", "90001000006 -> 90001000007", "2026-09-03 10:00:00")
            event(back, "code_overridden", "90001000007 -> 90001000006", "2026-09-04 10:00:00")
            event(back, "code_overridden", "ABC -> 90001000008", "2026-09-05 10:00:00")
            event(burned, "code_burned", "code 90001000009 ถูกทิ้งถาวร (ไม่อนุมัติหลังออกรหัส)",
                  "2026-09-06 10:00:00")

        command.upgrade(cfg, "head")
        with engine.connect() as c:
            got = {r[0]: (r[1], r[2]) for r in c.execute(text(
                "SELECT code, reason, request_id FROM retired_codes"))}
    finally:
        engine.dispose()

    assert got == {
        "90001000005": ("reissued", live),     # once, despite two events
        "90001000007": ("overridden", back),
        "90001000009": ("rejected", burned),   # kept on the rejected request, still retired
    }
    # 90001000006 is back in use on a live request; "ABC" was never a code.
    out = capsys.readouterr().out
    assert "3 added, 1 skipped (still in use), 1 skipped (no 11-digit code" in out


def test_backfill_actor_and_time_come_from_the_event(tmp_path, monkeypatch):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine

    url = f"sqlite:///{(tmp_path / 'backfill2.db').as_posix()}"
    monkeypatch.setattr(settings, "database_url", url)
    cfg = Config(str(Path(__file__).resolve().parent.parent / "alembic.ini"))
    command.upgrade(cfg, "2c0198e8b4a2")
    engine = create_engine(url)
    try:
        with engine.begin() as c:
            c.execute(text(
                "INSERT INTO item_requests (requester_name, requester_email, factory_id, "
                "code_system_id, group_id, item_name, status, generated_code) "
                "VALUES ('t', 't@x.co', 1, 1, 1, 'x', 'approved', '90002000001')"))
            c.execute(text(
                "INSERT INTO request_events (request_id, actor, action, detail, at) "
                "VALUES (1, 'admin@test.local', 'code_reissued', "
                "'90001000005 -> 90002000001', '2026-09-01 10:00:00')"))
        command.upgrade(cfg, "head")
        with engine.connect() as c:
            actor, at = c.execute(text("SELECT actor, at FROM retired_codes")).one()
    finally:
        engine.dispose()
    assert actor == "admin@test.local" and str(at).startswith("2026-09-01 10:00:00")


def test_events_still_record_the_burn_for_people_to_read(db_session):
    admin = account_for(db_session, "administrator")
    req = _approved(db_session)
    change_status(db_session, req.id, new_status="rejected", note="ซ้ำ", account=admin)
    assert db_session.scalar(select(RequestEvent).where(RequestEvent.action == "code_burned"))



# --- Review fixes ------------------------------------------------------------------------------

def test_override_back_onto_a_retired_code_is_refused(db_session):
    admin = account_for(db_session, "administrator")
    req = _approved(db_session)
    a, x = req.generated_code, next_code(db_session)
    load_master(db_session, [a, x])
    override_code(db_session, req.id, new_code=x, reason="มีใน master", account=admin)  # A retired
    with pytest.raises(RequestError, match="ถูกทิ้งไปแล้ว"):
        override_code(db_session, req.id, new_code=a, reason="กลับ", account=admin)
    db_session.refresh(req)
    assert req.generated_code == x
    # ...so the request can still leave the normal way.
    change_status(db_session, req.id, new_status="rejected", note="ซ้ำ", account=admin)
    assert (x, "rejected") in {(c, r) for c, r, _, _ in _retired(db_session)}


def test_backfill_prefers_the_rejection_as_the_reason(tmp_path, monkeypatch):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine

    url = f"sqlite:///{(tmp_path / 'backfill3.db').as_posix()}"
    monkeypatch.setattr(settings, "database_url", url)
    cfg = Config(str(Path(__file__).resolve().parent.parent / "alembic.ini"))
    command.upgrade(cfg, "2c0198e8b4a2")
    engine = create_engine(url)
    try:
        with engine.begin() as c:
            c.execute(text(
                "INSERT INTO item_requests (requester_name, requester_email, factory_id, "
                "code_system_id, group_id, item_name, status, generated_code) "
                "VALUES ('t', 't@x.co', 1, 1, 1, 'x', 'rejected', '90001000011')"))
            for action, detail, at in [
                ("code_overridden", "90001000011 -> 90001000012", "2026-09-01 10:00:00"),
                ("code_overridden", "90001000012 -> 90001000011", "2026-09-02 10:00:00"),
                ("code_burned", "code 90001000011 ถูกทิ้งถาวร", "2026-09-03 10:00:00"),
            ]:
                c.execute(text(
                    "INSERT INTO request_events (request_id, actor, action, detail, at) "
                    "VALUES (1, 'a@test.local', :a, :d, :t)"), {"a": action, "d": detail, "t": at})
        command.upgrade(cfg, "head")
        with engine.connect() as c:
            got = dict(c.execute(text("SELECT code, reason FROM retired_codes")).all())
    finally:
        engine.dispose()
    assert got == {"90001000011": "rejected", "90001000012": "overridden"}
