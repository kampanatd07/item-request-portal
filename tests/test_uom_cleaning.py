from sqlalchemy import select

from app.models import CodeGroup, CodeSystem, Factory, Uom, UomAlias
from app.services.config_admin import ConfigError, canonical_uom, merge_uoms
from app.services.requests import submit_request

import pytest


def _uom(db, code):
    return db.scalar(select(Uom).where(Uom.code == code))


def test_canonical_exact_and_alias(db_session):
    job = _uom(db_session, "Job")
    db_session.add(UomAlias(alias="งาน", uom_id=job.id))
    db_session.commit()
    assert canonical_uom(db_session, "Job") == "Job"
    assert canonical_uom(db_session, "งาน") == "Job"
    assert canonical_uom(db_session, "  งาน  ") == "Job"


def test_canonical_ambiguous_lookalikes_left_alone(db_session):
    # Job and JOB both active -> 'job' is ambiguous, must NOT guess
    assert canonical_uom(db_session, "job") == "job"


def test_canonical_unique_case_insensitive_match(db_session):
    assert canonical_uom(db_session, "set") == "Set"
    assert canonical_uom(db_session, "SET") == "Set"


def test_merge_creates_alias_deactivates_and_rewrites_requests(db_session):
    from tests.conftest import account_for, central_ids

    factory, system, group, sub = central_ids(db_session, "ACM", "700", "02")
    req = submit_request(
        db_session, account=account_for(db_session),
        factory_id=factory.id, code_system_id=system.id, group_id=group.id,
        subgroup_id=sub.id, item_name="งานซ่อมปั๊ม", uom="JOB",
    )
    assert req.uom == "JOB"

    job, JOB = _uom(db_session, "Job"), _uom(db_session, "JOB")
    merge_uoms(db_session, source_id=JOB.id, target_id=job.id)

    db_session.refresh(JOB)
    db_session.refresh(req)
    assert not JOB.active
    assert req.uom == "Job"  # old data cleaned
    assert canonical_uom(db_session, "JOB") == "Job"  # future input normalized
    assert canonical_uom(db_session, "job") == "Job"  # no longer ambiguous


def test_merge_self_rejected(db_session):
    job = _uom(db_session, "Job")
    with pytest.raises(ConfigError):
        merge_uoms(db_session, source_id=job.id, target_id=job.id)


def test_merge_via_http(client, db_session):
    pcs, pc = _uom(db_session, "Pcs"), _uom(db_session, "PC")
    resp = client.post(
        "/admin/config/uom/merge", data={"source_id": pc.id, "target_id": pcs.id}
    )
    assert resp.status_code == 200
    db_session.refresh(pc)
    assert not pc.active
    assert canonical_uom(db_session, "PC") == "Pcs"
