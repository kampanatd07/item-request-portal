"""Carabao Group central standard: 11-digit code + naming convention.

Reference: hand-off/_HANDOVER.md §2, CBD_NonStock_Restructure_Proposal_v1.md §2.3
"""

import pytest
from sqlalchemy import select

from app.models import CodeGroup, CodeSystem, Factory, RunningRegister
from app.services.naming import NamingError, compose_name
from app.services.requests import change_status, submit_request


def _central(db):
    return db.scalar(select(CodeSystem).where(CodeSystem.code == "CENTRAL"))


def _sub(db, group_code: str, sub_code: str):
    system = _central(db)
    grp = db.scalar(
        select(CodeGroup).where(
            CodeGroup.code_system_id == system.id,
            CodeGroup.code == group_code,
            CodeGroup.parent_id.is_(None),
        )
    )
    sub = db.scalar(
        select(CodeGroup).where(
            CodeGroup.parent_id == grp.id, CodeGroup.code == sub_code
        )
    )
    return grp, sub


def _submit(db, factory_code, group_code, sub_code, **kw):
    factory = db.scalar(select(Factory).where(Factory.code == factory_code))
    system = _central(db)
    grp, sub = _sub(db, group_code, sub_code)
    kwargs = dict(
        requester_name="ทดสอบ", requester_email="t@example.com",
        factory_id=factory.id, code_system_id=system.id,
        group_id=grp.id, subgroup_id=sub.id, item_name="Ball Bearing",
    )
    kwargs.update(kw)
    return submit_request(db, **kwargs)


# --- taxonomy ---------------------------------------------------------------

def test_taxonomy_seeded_20_groups_130_subs(db_session):
    system = _central(db_session)
    groups = db_session.scalars(
        select(CodeGroup).where(
            CodeGroup.code_system_id == system.id, CodeGroup.parent_id.is_(None)
        )
    ).all()
    subs = db_session.scalars(
        select(CodeGroup).where(
            CodeGroup.code_system_id == system.id, CodeGroup.parent_id.is_not(None)
        )
    ).all()
    assert len(groups) == 20
    assert len(subs) == 130
    assert all(s.name_prefix for s in subs)
    assert {s.product_type for s in subs} == {"Item", "Service"}


def test_legacy_systems_kept_but_inactive(db_session):
    systems = {s.code: s.active for s in db_session.scalars(select(CodeSystem))}
    assert systems["CENTRAL"] is True
    # kept in place so stock can be switched on later without a code change
    assert systems["CBD_STOCK"] is False
    assert systems["D365_SERVICE"] is False


def test_every_factory_uses_the_central_system(db_session):
    from app.services.catalog import list_factories, systems_for_factory

    for factory in list_factories(db_session):
        codes = [s.code for s in systems_for_factory(db_session, factory.id)]
        assert codes == ["CENTRAL"], f"{factory.code} should only offer CENTRAL"


# --- code structure ---------------------------------------------------------

def test_code_is_group_sub_00_running(db_session):
    req = _submit(db_session, "CBD", "900", "01")
    change_status(db_session, req.id, new_status="approved", actor="t")
    code = req.generated_code
    assert len(code) == 11 and code.isdigit()
    assert code[:3] == "900"       # Item Group
    assert code[3:5] == "01"       # Sub-Category
    assert code[5:7] == "00"       # Item Type reserved
    assert code[7:].isdigit()


def test_running_continues_from_the_register(db_session):
    reg = db_session.scalar(
        select(RunningRegister).where(
            RunningRegister.group_code == "900", RunningRegister.sub_code == "01"
        )
    )
    before = reg.last_running
    req = _submit(db_session, "APM", "900", "01")
    change_status(db_session, req.id, new_status="approved", actor="t")
    assert req.generated_code == f"90001{'00'}{before + 1:04d}"
    db_session.refresh(reg)
    assert reg.last_running == before + 1


def test_central_codes_never_collide_with_legacy_zero_zero_zero_zero(db_session):
    """Legacy ACM/APM/APG codes all carry 0000 in digits 4-7; central codes
    always carry a sub-category >= 01, so the two ranges are disjoint."""
    req = _submit(db_session, "ACM", "700", "02")
    change_status(db_session, req.id, new_status="approved", actor="t")
    assert req.generated_code[3:7] != "0000"


def test_one_item_one_code_across_plants(db_session):
    """Different plants requesting in the same sub-category draw from one
    series — no plant-specific numbering."""
    codes = []
    for plant in ["CBD", "APM", "APG", "ACM"]:
        req = _submit(db_session, plant, "907", "01", item_name=f"Notebook {plant}")
        change_status(db_session, req.id, new_status="approved", actor="t")
        codes.append(req.generated_code)
    assert len(set(codes)) == 4                     # all distinct
    assert len({c[:7] for c in codes}) == 1         # same group+sub prefix
    runs = sorted(int(c[7:]) for c in codes)
    assert runs == list(range(runs[0], runs[0] + 4))  # consecutive series


# --- naming convention ------------------------------------------------------

def test_name_uses_category_prefix_and_dash_separator(db_session):
    req = _submit(
        db_session, "CBD", "900", "01",
        item_name="Ball Bearing", brand="SKF", model="6205-2Z", size="25 มม.",
    )
    assert req.item_name == "BEARING - Ball Bearing SKF 6205-2Z - 25 mm"


def test_service_name_example_from_the_standard(db_session):
    req = _submit(
        db_session, "CBD", "700", "02",
        item_name="งานซ่อม Air Blower", variant="Air Diffuser Part",
    )
    assert req.item_name == "MACHINE REPAIR - งานซ่อม Air Blower - Air Diffuser Part"


def test_units_are_spaced_per_rule_4():
    name = compose_name(
        "Hydraulic Oil MOBIL NUTO H 32", size="208 L", detail="Drum",
        category_prefix="LUBRICANT",
    )
    assert name == "LUBRICANT - Hydraulic Oil MOBIL NUTO H 32 - 208 L Drum"


def test_forbidden_separators_are_stripped():
    name = compose_name(
        "Repair Air Blower--Asset", category_prefix="MACHINE REPAIR"
    )
    assert "--" not in name
    assert name.count(" - ") == 1


def test_cancelled_marker_never_enters_the_name():
    name = compose_name("(ยกเลิก) ชุด PPE", category_prefix="PPE")
    assert "ยกเลิก" not in name
    assert name == "PPE - ชุด PPE"


def test_name_may_not_start_with_punctuation():
    assert compose_name(". - อุปกรณ์", category_prefix="TOOL").startswith("TOOL - ")


def test_length_limits_enforced():
    with pytest.raises(NamingError):
        compose_name("X" * 60, category_prefix="BEARING")     # base > 50
    with pytest.raises(NamingError):
        compose_name("Pump", detail="Y" * 50, category_prefix="PUMP MOTOR")  # detail > 40
