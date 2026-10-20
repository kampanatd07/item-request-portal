"""STORY-013 ticket 04: category suggestion learns from the renamed name, without its prefix."""

from sqlalchemy import select

from app.models import ItemSnapshot
from app.services.categorizer import suggest_category
from app.services.requests import change_category, edit_name, submit_request
from app.services.snapshots import normalize
from tests.conftest import account_for, central_ids

BASE = "ซีลยางพิเศษ ZQ-77"  # unlikely to match anything already learned


def _move_to_seal(db, override: str | None = None) -> None:
    factory, system, group, sub = central_ids(db)  # 900-01 BEARING
    req = submit_request(db, account_for(db, "requester", plant="APM"),
                         factory_id=factory.id, code_system_id=system.id, group_id=group.id,
                         subgroup_id=sub.id, item_name=BASE)
    if override:
        edit_name(db, req.id, new_name=override, account=account_for(db, "procurement"))
    seal = central_ids(db, "APM", "900", "02")[3]
    change_category(db, req.id, subgroup_id=seal.id, account=account_for(db, "procurement"))


def _learned(db) -> list[str]:
    return list(db.scalars(select(ItemSnapshot.normalized_name)
                           .where(ItemSnapshot.source == "LEARNED")))


def test_the_learned_text_has_no_name_prefix(db_session):
    _move_to_seal(db_session)  # renamed SEAL - ซีลยางพิเศษ ZQ-77
    assert normalize(BASE) in _learned(db_session)
    assert not any(n.startswith("seal") or n.startswith("bearing") for n in _learned(db_session))


def test_the_name_without_a_prefix_suggests_the_new_category(db_session):
    _move_to_seal(db_session)
    row = db_session.scalar(select(ItemSnapshot).where(ItemSnapshot.source == "LEARNED"))
    assert (row.name, row.group_code, row.sub_code) == (BASE, "900", "02")
    out = suggest_category(db_session, BASE)
    assert (out[0].group.code, out[0].sub.code) == ("900", "02")


def test_a_kept_name_without_a_prefix_is_learned_whole(db_session):
    _move_to_seal(db_session, override="ซีลยางพิเศษ ZQ-77 - ขนาด 20 mm")  # ticket 03: kept
    assert normalize("ซีลยางพิเศษ ZQ-77 - ขนาด 20 mm") in _learned(db_session)


def test_a_kept_name_with_another_categorys_prefix_is_learned_whole(db_session):
    # Agreed rule (grilling Q11): only the new category's prefix is cut; a name
    # that does not start with it is learned as it is.
    _move_to_seal(db_session, override="VALVE - ซีลยางพิเศษ ZQ-77")
    assert normalize("VALVE - ซีลยางพิเศษ ZQ-77") in _learned(db_session)
