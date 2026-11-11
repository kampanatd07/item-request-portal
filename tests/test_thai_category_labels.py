"""STORY-019: Thai names and hints for the central categories (display only)."""

import io

import pytest
from openpyxl import load_workbook

from app.models import CodeGroup
from app.services.exporter import build_workbook_bytes
from app.services.requests import change_status, submit_request
from tests.conftest import account_for, central_ids

SEAL_TH = "ซีล โอริง และปะเก็น"
SEAL_HINT = "เช่น ซีลน้ำมัน โอริงยาง ปะเก็นหน้าแปลน"
GROUP_TH = "อะไหล่และชิ้นส่วนเครื่องกล"


def _label_seal(db) -> tuple[CodeGroup, CodeGroup]:
    group, seal = central_ids(db, "APM", "900", "02")[2:]
    group.name_th = GROUP_TH
    seal.name_th, seal.hint_th = SEAL_TH, SEAL_HINT
    db.commit()
    return group, seal


def _submit_seal(db):
    factory, system, group, seal = central_ids(db, "APM", "900", "02")
    return submit_request(
        db, account_for(db, "requester", plant="APM"),
        factory_id=factory.id, code_system_id=system.id,
        group_id=group.id, subgroup_id=seal.id, item_name="Oil Seal", uom="EA",
    )


# --- Request form -------------------------------------------------------------

def test_options_without_thai_read_exactly_as_before(client_as, app_db) -> None:
    group, seal = central_ids(app_db, "APM", "900", "02")[2:]
    c = client_as("requester", plant="APM")
    subs = c.get(f"/fragments/subgroups?group_id={group.id}").text
    assert f'<option value="{seal.id}">02 — Seal, O-Ring &amp; Gasket</option>' in subs
    assert "data-hint" not in subs
    groups = c.get(f"/fragments/groups?code_system_id={group.code_system_id}").text
    assert f'<option value="{group.id}">900 — Spare Parts &amp; Mechanical Parts</option>' in groups


def test_options_with_thai_add_it_after_the_english_name(client_as, app_db) -> None:
    group, seal = _label_seal(app_db)
    c = client_as("requester", plant="APM")
    subs = c.get(f"/fragments/subgroups?group_id={group.id}").text
    assert (f'<option value="{seal.id}" data-hint="{SEAL_HINT}">'
            f"02 — Seal, O-Ring &amp; Gasket ({SEAL_TH})</option>") in subs
    groups = c.get(f"/fragments/groups?code_system_id={group.code_system_id}").text
    assert f"900 — Spare Parts &amp; Mechanical Parts ({GROUP_TH})</option>" in groups


def test_the_hint_is_shown_as_text_only_for_a_sub_category_that_has_one(client_as, app_db) -> None:
    group, _seal = _label_seal(app_db)
    c = client_as("requester", plant="APM")
    subs = c.get(f"/fragments/subgroups?group_id={group.id}").text
    assert '<p class="hint" id="subgroup-hint" aria-live="polite" hidden></p>' in subs
    script = c.get("/").text.split("function showSubgroupHint", 1)[1].split("\n}", 1)[0]
    assert "p.textContent = hint;" in script and "innerHTML" not in script
    assert "p.hidden = !hint;" in script  # nothing shows without a hint


def test_a_hint_with_markup_is_escaped(client_as, app_db) -> None:
    group, seal = central_ids(app_db, "APM", "900", "02")[2:]
    seal.hint_th = '"><script>alert(1)</script>'
    app_db.commit()
    subs = client_as("requester", plant="APM").get(f"/fragments/subgroups?group_id={group.id}").text
    assert "<script>alert(1)" not in subs
    assert 'data-hint="&#34;&gt;&lt;script&gt;' in subs


def test_suggestion_chips_show_the_thai_name(client_as, app_db, monkeypatch) -> None:
    from app.services import categorizer
    from app.services.categorizer import Suggestion

    group, seal = _label_seal(app_db)
    monkeypatch.setattr(categorizer, "suggest_category",
                        lambda db, name, **kw: [Suggestion(group, seal, 0.95, "test")])
    factory = central_ids(app_db, "APM")[0]
    r = client_as("requester", plant="APM").post(
        "/fragments/duplicates", data={"factory_id": factory.id, "item_name": "Oil Seal"})
    assert f"900-02 Seal, O-Ring &amp; Gasket ({SEAL_TH})" in r.text


# --- Detail page ----------------------------------------------------------------

def test_the_detail_page_shows_the_thai_name(client_as, app_db) -> None:
    req = _submit_seal(app_db)
    _label_seal(app_db)
    page = client_as("procurement").get(f"/queue/{req.id}").text
    assert f"02 — Seal, O-Ring &amp; Gasket ({SEAL_TH})" in page  # request summary
    assert f"Seal, O-Ring &amp; Gasket · {SEAL_TH}" in page  # category panel


# --- Administrator edits --------------------------------------------------------

def test_an_administrator_sets_and_clears_the_thai_label(client_as, app_db) -> None:
    seal = central_ids(app_db, "APM", "900", "02")[3]
    c = client_as("administrator")
    assert "ชื่อไทยของหมวด" in c.get("/admin/config").text
    r = c.post(f"/admin/config/thai/{seal.id}",
               data={"name_th": f"  {SEAL_TH} ", "hint_th": SEAL_HINT})
    assert r.status_code == 200
    app_db.refresh(seal)
    assert (seal.name_th, seal.hint_th) == (SEAL_TH, SEAL_HINT)
    assert f'value="{SEAL_TH}"' in r.text
    c.post(f"/admin/config/thai/{seal.id}", data={"name_th": "", "hint_th": " "})
    app_db.refresh(seal)
    assert (seal.name_th, seal.hint_th) == (None, None)


def test_thai_text_is_stored_composed(client_as, app_db) -> None:
    seal = central_ids(app_db, "APM", "900", "02")[3]
    decomposed = "น" + "ํา" + "มัน"  # SARA AM as NIKHAHIT + SARA AA
    client_as("administrator").post(f"/admin/config/thai/{seal.id}",
                                    data={"name_th": decomposed, "hint_th": ""})
    app_db.refresh(seal)
    assert seal.name_th == "น" + "ำ" + "มัน"  # one SARA AM


@pytest.mark.parametrize("role", ["procurement", "requester"])
def test_only_an_administrator_may_edit_thai_labels(client_as, app_db, role) -> None:
    seal = central_ids(app_db, "APM", "900", "02")[3]
    c = client_as(role, plant="APM" if role == "requester" else None)
    r = c.post(f"/admin/config/thai/{seal.id}", data={"name_th": "x", "hint_th": ""})
    assert r.status_code == 403
    app_db.refresh(seal)
    assert seal.name_th is None


def test_a_too_long_label_is_refused(client_as, app_db) -> None:
    seal = central_ids(app_db, "APM", "900", "02")[3]
    r = client_as("administrator").post(f"/admin/config/thai/{seal.id}",
                                        data={"name_th": "ก" * 101, "hint_th": ""})
    assert r.status_code == 422 and "ยาวเกิน 100" in r.text
    app_db.refresh(seal)
    assert seal.name_th is None


def test_a_group_outside_the_central_taxonomy_is_refused(client_as, app_db) -> None:
    from sqlalchemy import select

    from app.models import CodeSystem

    other_system = app_db.scalar(select(CodeSystem).where(CodeSystem.code != "CENTRAL"))
    other = CodeGroup(code_system_id=other_system.id, code="ZZ", name="Not central")
    app_db.add(other)
    app_db.commit()
    r = client_as("administrator").post(f"/admin/config/thai/{other.id}",
                                        data={"name_th": "x", "hint_th": ""})
    assert r.status_code == 422


# --- Seed -----------------------------------------------------------------------

def _seed_with(db, monkeypatch, labels: dict) -> None:
    from app import seed as seed_module

    real = seed_module._load_json
    monkeypatch.setattr(seed_module, "_load_json",
                        lambda name: labels if name == "taxonomy_th.json" else real(name))
    seed_module.seed(db)


def test_seed_fills_empty_labels_but_keeps_an_administrators_edit(db_session, monkeypatch) -> None:
    group, seal = central_ids(db_session, "APM", "900", "02")[2:]
    seal.name_th = "แก้โดยผู้ดูแลระบบ"
    db_session.commit()
    _seed_with(db_session, monkeypatch, {
        "900": {"name_th": GROUP_TH},
        "900-02": {"name_th": SEAL_TH, "hint_th": SEAL_HINT},
    })
    db_session.refresh(group)
    db_session.refresh(seal)
    assert group.name_th == GROUP_TH and group.hint_th is None
    assert seal.name_th == "แก้โดยผู้ดูแลระบบ"  # the Administrator's edit wins
    assert seal.hint_th == SEAL_HINT  # the empty field is filled


@pytest.mark.parametrize("labels, message", [
    ({"999-01": {"name_th": "x"}}, "ไม่มีหมวด '999-01'"),
    ({"900-02": "ซีล"}, "ต้องเป็น"),
    ({"900-02": {"name_th": "ก" * 101}}, "ยาวเกิน 100"),
])
def test_seed_refuses_a_bad_thai_label_file_before_writing(db_session, monkeypatch, labels, message) -> None:
    from app.seed import SeedError

    with pytest.raises(SeedError, match=message):
        _seed_with(db_session, monkeypatch, labels)


def test_the_shipped_thai_label_file_loads() -> None:
    import json
    from pathlib import Path

    from app.seed import load_thai_labels

    data = Path(__file__).resolve().parents[1] / "app" / "data"
    labels = json.loads((data / "taxonomy_th.json").read_text(encoding="utf-8"))
    taxonomy = json.loads((data / "taxonomy.json").read_text(encoding="utf-8"))
    load_thai_labels(labels, taxonomy)  # raises SeedError on a bad file


# --- Exports and names stay the same ---------------------------------------------

def _export_values(db, req) -> dict:
    wb = load_workbook(io.BytesIO(build_workbook_bytes(db, "APM", [req])))
    return {ws.title: list(ws.iter_rows(values_only=True)) for ws in wb.worksheets}


def test_exports_and_names_are_the_same_with_thai_labels(db_session) -> None:
    req = _submit_seal(db_session)
    req = change_status(db_session, req.id, new_status="approved",
                        account=account_for(db_session, "administrator"))
    before_name, before = req.item_name, _export_values(db_session, req)
    _label_seal(db_session)
    db_session.refresh(req)
    assert req.item_name == before_name
    assert _export_values(db_session, req) == before
    assert SEAL_TH not in repr(before)
