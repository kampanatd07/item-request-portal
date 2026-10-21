"""STORY-013 closing review (2026-10-21): fixes found by the branch-wide review."""

import io

import pytest
from openpyxl import Workbook
from sqlalchemy import select

from app.models import ItemRequest, RequestEvent
from app.services import naming
from app.services.requests import change_category, edit_name, submit_request
from tests.conftest import account_for, central_ids


def _request(db, override: str | None = None) -> ItemRequest:
    factory, system, group, sub = central_ids(db)  # 900-01 BEARING
    req = submit_request(db, account_for(db, "requester", plant="APM"),
                         factory_id=factory.id, code_system_id=system.id, group_id=group.id,
                         subgroup_id=sub.id, item_name="Ball Bearing")
    if override:
        edit_name(db, req.id, new_name=override, account=account_for(db, "procurement"))
    return req


def _seal(db):
    return central_ids(db, "APM", "900", "02")[3]


# --- 1. The move redraws the request summary (heading + table) too ----------------------------------

def test_the_move_redraws_the_heading_and_the_summary_table(client_as, app_db):
    req = _request(app_db)
    c = client_as("procurement")
    assert 'id="request-summary"' in c.get(f"/queue/{req.id}").text
    r = c.post(f"/queue/{req.id}/category", data={"subgroup_id": _seal(app_db).id})
    assert r.status_code == 200, r.text
    start = r.text.index('id="request-summary"')
    summary = r.text[start - 60:]
    assert 'hx-swap-oob="innerHTML"' in summary[:120]
    assert f"คำขอ #{req.id} — SEAL - Ball Bearing" in summary
    assert "02 — " in summary  # the new Sub-Category row


# --- 2. A kept name with the new prefix in another case gets it in upper case (AC3) ------------------

def test_a_kept_name_with_the_new_prefix_in_another_case_is_written_upper(app_db):
    req = _request(app_db, override="Seal - O-ring 20 mm")
    change_category(app_db, req.id, subgroup_id=_seal(app_db).id,
                    account=account_for(app_db, "procurement"))
    app_db.expire_all()
    assert app_db.get(ItemRequest, req.id).item_name == "SEAL - O-ring 20 mm"
    events = [(e.action, e.detail) for e in app_db.scalars(
        select(RequestEvent).where(RequestEvent.request_id == req.id).order_by(RequestEvent.id))]
    assert events[-2:] == [("category_changed", "900-01 -> 900-02"),
                           ("name_prefix_changed", "Seal - O-ring 20 mm → SEAL - O-ring 20 mm")]


def test_a_kept_name_with_the_new_prefix_already_upper_is_untouched(app_db):
    req = _request(app_db, override="SEAL - O-ring 20 mm")
    change_category(app_db, req.id, subgroup_id=_seal(app_db).id,
                    account=account_for(app_db, "procurement"))
    actions = list(app_db.scalars(select(RequestEvent.action)
                                  .where(RequestEvent.request_id == req.id)))
    assert "name_prefix_changed" not in actions


# --- 4. The seed refuses a prefix that cleaning would change -------------------------------------------

@pytest.mark.parametrize("prefix", ["PIPE , FITTING", "PIPE / FITTING", "-PIPE", "PIPE  FITTING"])
def test_the_seed_refuses_a_prefix_cleaning_changes(monkeypatch, prefix):
    from tests.test_seed_prefix_guard import _taxonomy_with
    from app import seed as seed_module

    _taxonomy_with(monkeypatch, g900_04=prefix)
    with pytest.raises(seed_module.SeedError) as refused:
        seed_module.check_taxonomy(seed_module._load_json("taxonomy.json"))
    assert "900-04" in str(refused.value) and prefix in str(refused.value)


# --- 6-8. The same Name Prefix is normalised once, not per row / per check -------------------------

@pytest.fixture()
def cleanings(monkeypatch):
    """Counts how many times a Name Prefix is cleaned (cache misses)."""
    clear = getattr(naming.prefix_as_written, "cache_clear", lambda: None)
    clear()
    calls = []
    real = naming.clean_part

    def counting(part):
        calls.append(part)
        return real(part)

    monkeypatch.setattr(naming, "clean_part", counting)
    yield calls
    clear()


def test_the_master_import_cleans_each_prefix_once(db_session, cleanings):
    from app.services.snapshots import import_labeled_master

    wb = Workbook()
    ws = wb.active
    ws.append(["Item Number", "Product Name", "Category Code", "Sub-Category Code"])
    for n in range(1, 201):
        ws.append([f"90001{n:06d}", f"BEARING - Ball Bearing {n}", "900", "01"])
    buf = io.BytesIO()
    wb.save(buf)
    import_labeled_master(db_session, filename="m.xlsx", data=buf.getvalue(),
                          uploaded_by="admin@test.local")
    assert cleanings.count("BEARING") == 1


def test_the_name_panel_check_cleans_the_prefix_once(app_db, cleanings):
    from app.services.queue_view import name_prefix_warning

    req = _request(app_db, override="Ball Bearing SKF")
    cleanings.clear()
    assert name_prefix_warning(req) == "BEARING"
    assert len(cleanings) <= 1


def test_a_category_move_cleans_each_prefix_once(app_db, cleanings):
    req = _request(app_db)
    cleanings.clear()
    change_category(app_db, req.id, subgroup_id=_seal(app_db).id,
                    account=account_for(app_db, "procurement"))
    assert cleanings.count("BEARING") <= 1 and cleanings.count("SEAL") <= 1
