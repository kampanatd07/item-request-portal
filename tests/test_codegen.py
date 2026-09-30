"""Central code issuance + the legacy pattern engine kept for the future
stock scope (see docs/decisions.md 2026-08-10)."""

import pytest
from sqlalchemy import select

from app.models import ItemRequest, RunningRegister
from app.services.codegen import CodegenError, build_prefix_and_runlen
from app.services.requests import RequestError, change_status, override_code, submit_request
from tests.conftest import account_for, central_ids, load_master, next_code


def _submit(db, factory_code="APM", group_code="900", sub_code="01", **kw):
    factory, system, group, sub = central_ids(db, factory_code, group_code, sub_code)
    kwargs = dict(
        account=account_for(db),
        factory_id=factory.id, code_system_id=system.id,
        group_id=group.id, subgroup_id=sub.id, item_name="Test item",
    )
    kwargs.update(kw)
    return submit_request(db, **kwargs)


def _approve(db, req):
    return change_status(db, req.id, new_status="approved", account=account_for(db, "administrator"))


def test_two_approvals_same_subcategory_get_consecutive_codes(db_session):
    r1 = _approve(db_session, _submit(db_session, group_code="907", sub_code="01"))
    r2 = _approve(db_session, _submit(db_session, group_code="907", sub_code="01"))
    assert int(r2.generated_code[7:]) == int(r1.generated_code[7:]) + 1


def test_each_subcategory_has_its_own_series(db_session):
    a = _approve(db_session, _submit(db_session, group_code="900", sub_code="01"))
    b = _approve(db_session, _submit(db_session, group_code="900", sub_code="02"))
    assert a.generated_code[:5] == "90001"
    assert b.generated_code[:5] == "90002"


def test_register_is_the_only_source_of_numbers(db_session):
    """Deleting a code from a request must not hand the number back out —
    the register, not the request table, owns the series."""
    req = _approve(db_session, _submit(db_session, group_code="902", sub_code="01"))
    issued = req.generated_code
    reg = db_session.scalar(
        select(RunningRegister).where(
            RunningRegister.group_code == "902", RunningRegister.sub_code == "01"
        )
    )
    after_first = reg.last_running

    req.generated_code = None
    db_session.commit()
    nxt = _approve(db_session, _submit(db_session, group_code="902", sub_code="01"))
    assert int(nxt.generated_code[7:]) == after_first + 1
    assert nxt.generated_code != issued


def test_override_code_logs_and_rejects_duplicates(db_session):
    r1 = _approve(db_session, _submit(db_session, group_code="907", sub_code="01"))
    r2 = _approve(db_session, _submit(db_session, group_code="907", sub_code="01"))
    x = next_code(db_session, "907", "01")
    load_master(db_session, [x])
    override_code(db_session, r2.id, new_code=x, reason="มีใน master แล้ว",
                  account=account_for(db_session, "administrator"))
    assert r2.generated_code == x
    with pytest.raises(RequestError, match="ถูกใช้กับคำขออื่น"):
        override_code(db_session, r1.id, new_code=x, reason="ซ้ำ",
                      account=account_for(db_session, "administrator"))
    assert [e.action for e in r2.events][-1] == "code_overridden"


def test_missing_subcategory_fails_cleanly(db_session):
    req = _submit(db_session, group_code="900", sub_code="01")
    req.subgroup_id = None
    db_session.commit()
    with pytest.raises(RequestError, match="หมวดย่อย"):
        _approve(db_session, req)


def test_request_without_subcategory_is_rejected_at_submit(db_session):
    factory, system, group, _sub = central_ids(db_session)
    with pytest.raises(RequestError, match="หมวดย่อย"):
        submit_request(
            db_session, account=account_for(db_session),
            factory_id=factory.id, code_system_id=system.id,
            group_id=group.id, subgroup_id=None, item_name="No sub",
        )


# --- legacy pattern engine (inactive systems, retained for stock) -----------

class _FakeGroup:
    def __init__(self, code, override=None):
        self.code = code
        self.pattern_override = override


class _FakeSystem:
    def __init__(self, template):
        self.pattern_template = template
        self.code = "LEGACY"


class _FakeRequest:
    def __init__(self, template, group_code, sub_code=None, override=None):
        self.code_system = _FakeSystem(template)
        self.group = _FakeGroup(group_code, override)
        self.subgroup = _FakeGroup(sub_code) if sub_code else None


def test_legacy_pattern_parsing_still_works():
    assert build_prefix_and_runlen(
        _FakeRequest("{group}0000{run:4}", "800")
    ) == ("8000000", 4)
    assert build_prefix_and_runlen(
        _FakeRequest("9905{cat}{sub}{run:4}", "01", "02")
    ) == ("99050102", 4)


def test_legacy_pattern_requires_subgroup_when_template_needs_it():
    with pytest.raises(CodegenError, match="หมวดย่อย"):
        build_prefix_and_runlen(_FakeRequest("9905{cat}{sub}{run:4}", "01"))
