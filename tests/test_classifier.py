from sqlalchemy import select

from app.models import CodeGroup, CodeSystem, Factory, ItemRequest, SearchTerm
from app.services.classifier import classify, promote_term, suggest_from_dictionary
from app.services.requests import submit_request


def _terms(db):
    return list(db.scalars(select(SearchTerm.term).where(SearchTerm.active)))


def test_specific_term_beats_generic(db_session):
    terms = _terms(db_session)
    hits = suggest_from_dictionary("Ball Bearing SKF UCF209-28 44.45mm", terms)
    assert hits[0][0] == "BALL BEARING"  # not the generic "BEARING"


def test_dictionary_classify_common_types(db_session):
    assert classify(db_session, "GASKET AY9W72AA010#29")["suggestion"] == "GASKET"
    assert classify(db_session, "Solenoid Valve for Air Block")["suggestion"] == "SOLENOID VALVE"
    r = classify(db_session, "Wear Strip Profile 8mm")
    assert r["suggestion"] == "WEAR STRIP PROFILE"
    assert r["source"] == "dictionary"
    # when two product terms appear, the leading one is the head noun
    assert classify(db_session, "แหวนสปริง Wear Strip 8mm")["suggestion"] == "แหวนสปริง"


def test_unknown_name_falls_back_without_llm(db_session):
    r = classify(db_session, "Zorptronic Flux Capacitor XYZ")
    assert r["source"] == "fallback"
    assert r["suggestion"]  # non-empty, upper-cased head tokens


def test_llm_used_only_when_dictionary_misses(db_session):
    calls = []

    def fake_llm(name, candidates):
        calls.append(name)
        return "FLUX CAPACITOR"

    # dictionary hit -> llm not called
    r1 = classify(db_session, "Ball Bearing 6205", llm=fake_llm)
    assert r1["source"] == "dictionary" and calls == []

    # dictionary miss -> llm consulted
    r2 = classify(db_session, "Zorptronic gizmo", llm=fake_llm)
    assert r2["source"] == "llm" and r2["suggestion"] == "FLUX CAPACITOR"
    assert calls == ["Zorptronic gizmo"]


def test_llm_exception_falls_back_gracefully(db_session):
    def broken_llm(name, candidates):
        raise RuntimeError("api down")

    r = classify(db_session, "Zorptronic gizmo", llm=broken_llm)
    assert r["source"] == "fallback"


def test_promote_term_adds_and_bumps(db_session):
    promote_term(db_session, "flux capacitor")
    st = db_session.scalar(select(SearchTerm).where(SearchTerm.term == "FLUX CAPACITOR"))
    assert st and st.usage_count == 1
    promote_term(db_session, "Flux Capacitor")
    db_session.refresh(st)
    assert st.usage_count == 2


def test_duplicates_fragment_carries_searchname_oob(client, db_session):
    """Regression: the search-name suggestion must ride along with the duplicate
    check (its own hx-trigger never fired in the browser)."""
    import io

    from openpyxl import Workbook

    from app.models import Factory
    from app.services.snapshots import import_snapshot

    wb = Workbook()
    wb.active.append(["Item number", "Product name"])
    wb.active.append(["990501012260", "Bearing SKF 6205"])
    buf = io.BytesIO()
    wb.save(buf)
    import_snapshot(db_session, source="CBD", filename="t.xlsx", data=buf.getvalue(), uploaded_by="test@test.local")

    cbd = db_session.scalar(select(Factory).where(Factory.code == "CBD"))
    resp = client.post(
        "/fragments/duplicates",
        data={"factory_id": cbd.id, "item_name": "Ball Bearing SKF 6205"},
    )
    assert resp.status_code == 200
    assert 'id="sn-slot"' in resp.text and "hx-swap-oob" in resp.text
    assert "BALL BEARING" in resp.text
    assert "พบรายการใกล้เคียง" in resp.text


def test_submit_autofills_search_name_when_blank(db_session):
    from tests.conftest import account_for, central_ids

    factory, system, group, sub = central_ids(db_session, "APM")
    req = submit_request(
        db_session, account=account_for(db_session),
        factory_id=factory.id, code_system_id=system.id, group_id=group.id,
        subgroup_id=sub.id, item_name="Ball Bearing SKF 6205", search_name="",
    )
    assert req.search_name == "BALL BEARING"
