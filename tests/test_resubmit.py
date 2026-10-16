"""STORY-009 ticket 02: a Requester resubmits their own Needs Info request."""

from sqlalchemy import select

from app.models import Account, CodeGroup, ItemRequest, RequestEvent
from app.services.requests import change_category, change_status, edit_name, submit_request
from tests.conftest import account_for, central_ids

REPLY = "เพิ่มขนาดและแบรนด์ให้แล้วครับ"


def _me(db, email: str) -> Account:
    return db.scalar(select(Account).where(Account.email == email))


def _submit(db, account: Account, base: str = "Ball Bearing", plant: str = "APM",
            **fields) -> ItemRequest:
    factory, system, group, sub = central_ids(db, plant)
    return submit_request(db, account, factory_id=factory.id, code_system_id=system.id,
                          group_id=group.id, subgroup_id=sub.id, item_name=base, **fields)


def _needs_info(db, req: ItemRequest, note: str = "ขอขนาดและแบรนด์") -> None:
    change_status(db, req.id, new_status="needs_info", account=account_for(db, "procurement"),
                  note=note)


def _requester_with_request(client_as, app_db, **fields):
    """A logged-in Requester (APM) and their own request, now in Needs Info."""
    c = client_as("requester", plant="APM")
    me = _me(app_db, "requester0@test.local")
    req = _submit(app_db, me, **fields)
    _needs_info(app_db, req)
    return c, me, req


def _form(req: ItemRequest, **over) -> dict:
    """The resubmit form as the page prefills it, with `over` applied."""
    data = {
        "code_system_id": req.code_system_id, "group_id": req.group_id,
        "subgroup_id": req.subgroup_id or "", "item_name": req.base_name or "",
        "brand": req.brand or "", "model": req.model or "", "size": req.size or "",
        "variant": req.variant or "", "spec_note": req.spec_note or "", "uom": req.uom or "",
        "search_name": req.search_name or "", "purchase_price": req.purchase_price or "",
        "procurement_category": req.procurement_category or "", "reply": REPLY,
    }
    data.update(over)
    return data


def _events(db, req: ItemRequest) -> list[RequestEvent]:
    db.expire_all()
    return list(db.scalars(select(RequestEvent).where(RequestEvent.request_id == req.id)
                           .order_by(RequestEvent.id)))


def _fresh(db, req: ItemRequest) -> ItemRequest:
    db.expire_all()
    return db.get(ItemRequest, req.id)


def _url(req: ItemRequest) -> str:
    return f"/my-requests/{req.id}/resubmit"


# --- 1. Happy path ----------------------------------------------------------------------------------

def test_resubmit_recomposes_the_name_and_goes_back_to_the_queue(client_as, app_db):
    c, me, req = _requester_with_request(client_as, app_db, brand="SKF")
    before = len(_events(app_db, req))
    r = c.post(_url(req), data=_form(req, brand="NSK", size="20 L"))
    assert r.status_code == 200, r.text

    req = _fresh(app_db, req)
    assert req.status == "submitted"
    assert req.item_name == "BEARING - Ball Bearing NSK - 20 L"
    assert req.brand == "NSK" and req.size == "20 L"
    assert req.review_note is None
    edited, submitted = _events(app_db, req)[before:]
    assert edited.action == "request_edited" and edited.actor == me.email
    assert "แบรนด์: SKF → NSK" in edited.detail
    assert "ขนาด: - → 20 L" in edited.detail
    assert "ชื่อสินค้า: BEARING - Ball Bearing SKF → BEARING - Ball Bearing NSK - 20 L" in edited.detail
    assert submitted.action == "submitted" and submitted.detail.splitlines()[0] == REPLY


# --- 2. Nothing changed: no request_edited, name untouched --------------------------------------

def test_resubmit_without_changes_keeps_the_name_and_logs_no_edit(client_as, app_db):
    c, _, req = _requester_with_request(client_as, app_db, brand="SKF")
    name = req.item_name
    before = len(_events(app_db, req))
    assert c.post(_url(req), data=_form(req)).status_code == 200
    req = _fresh(app_db, req)
    assert req.status == "submitted" and req.item_name == name
    assert [e.action for e in _events(app_db, req)[before:]] == ["submitted"]


def test_resubmit_without_changes_keeps_a_name_procurement_typed(client_as, app_db):
    c, _, req = _requester_with_request(client_as, app_db, brand="SKF")
    edit_name(app_db, req.id, new_name="BEARING - Ball Bearing SKF แบบพิเศษ",
              account=account_for(app_db, "procurement"))
    assert c.post(_url(req), data=_form(_fresh(app_db, req))).status_code == 200
    req = _fresh(app_db, req)
    assert req.item_name == "BEARING - Ball Bearing SKF แบบพิเศษ"
    assert "request_edited" not in [e.action for e in _events(app_db, req)]


# --- 3. One field changed after Procurement typed a name: recomposed, typed name kept in the log

def test_an_edit_replaces_a_name_procurement_typed_and_logs_it(client_as, app_db):
    c, _, req = _requester_with_request(client_as, app_db, brand="SKF")
    typed = "BEARING - Ball Bearing SKF แบบพิเศษ"
    edit_name(app_db, req.id, new_name=typed, account=account_for(app_db, "procurement"))
    r = c.post(_url(req), data=_form(_fresh(app_db, req), model="6205"))
    assert r.status_code == 200, r.text
    req = _fresh(app_db, req)
    assert req.item_name == "BEARING - Ball Bearing SKF 6205"
    edited = [e for e in _events(app_db, req) if e.action == "request_edited"][-1]
    assert f"ชื่อสินค้า: {typed} → BEARING - Ball Bearing SKF 6205" in edited.detail


# --- 4. Not the Requester: 403, whatever the Role --------------------------------------------------

def test_another_requester_in_the_same_plant_gets_403(client_as, app_db):
    _, _, req = _requester_with_request(client_as, app_db)
    other = client_as("requester", plant="APM")
    assert other.get(_url(req)).status_code == 403
    assert other.post(_url(req), data=_form(req)).status_code == 403
    assert _fresh(app_db, req).status == "needs_info"


def test_procurement_that_did_not_submit_it_gets_403(client_as, app_db):
    _, _, req = _requester_with_request(client_as, app_db)
    proc = client_as("procurement")
    assert proc.get(_url(req)).status_code == 403
    assert proc.post(_url(req), data=_form(req)).status_code == 403
    assert _fresh(app_db, req).status == "needs_info"


# --- 5. Own request no longer in Needs Info: 409, nothing saved ----------------------------------

def test_own_request_not_in_needs_info_gets_409(client_as, app_db):
    c = client_as("requester", plant="APM")
    me = _me(app_db, "requester0@test.local")
    for status in ("submitted", "rejected"):
        req = _submit(app_db, me, brand="SKF")
        if status == "rejected":
            change_status(app_db, req.id, new_status="rejected",
                          account=account_for(app_db, "procurement"), note="ซ้ำ")
        before = len(_events(app_db, req))
        assert c.get(_url(req)).status_code == 409
        r = c.post(_url(req), data=_form(req, brand="NSK"))
        assert r.status_code == 409
        label = "ส่งคำขอแล้ว" if status == "submitted" else "ไม่อนุมัติ"
        assert f"คำขอนี้ไม่ได้รอข้อมูลแล้ว (สถานะปัจจุบัน: {label})" in r.text
        req = _fresh(app_db, req)
        assert req.status == status and req.brand == "SKF"
        assert len(_events(app_db, req)) == before


# --- 6. Plant always from the stored request ---------------------------------------------------

def test_a_posted_plant_is_ignored(client_as, app_db):
    c, _, req = _requester_with_request(client_as, app_db)
    other_plant = central_ids(app_db, "APG")[0]
    plant = req.factory_id
    r = c.post(_url(req), data=_form(req, factory_id=other_plant.id, brand="NSK"))
    assert r.status_code == 200, r.text
    assert _fresh(app_db, req).factory_id == plant


# --- 7. Validation fails after the claim: rolled back to Needs Info -----------------------------

def test_invalid_fields_roll_back_to_needs_info(client_as, app_db):
    c, _, req = _requester_with_request(client_as, app_db, brand="SKF")
    foreign_sub = central_ids(app_db, "APM", "701", "01")[3]  # not under 900
    before = len(_events(app_db, req))
    r = c.post(_url(req), data=_form(req, brand="NSK", subgroup_id=foreign_sub.id))
    assert r.status_code == 422 and "หมวดย่อยไม่ถูกต้อง" in r.text
    req = _fresh(app_db, req)
    assert req.status == "needs_info" and req.brand == "SKF"
    assert req.review_note == "ขอขนาดและแบรนด์"
    assert len(_events(app_db, req)) == before


# --- 8. Reply required -------------------------------------------------------------------------------

def test_an_empty_reply_is_refused(client_as, app_db):
    c, _, req = _requester_with_request(client_as, app_db, brand="SKF")
    before = len(_events(app_db, req))
    r = c.post(_url(req), data=_form(req, brand="NSK", reply="   "))
    assert r.status_code == 422 and "ตอบจัดซื้อ" in r.text
    req = _fresh(app_db, req)
    assert req.status == "needs_info" and req.brand == "SKF"
    assert len(_events(app_db, req)) == before


# --- 9. No stored Base Name: empty, required field ------------------------------------------------

def test_a_request_without_a_base_name_asks_for_it(client_as, app_db):
    c, _, req = _requester_with_request(client_as, app_db)
    req.base_name = None  # an older request, before the column existed
    app_db.commit()
    page = c.get(_url(req)).text
    assert 'name="item_name" value="" required' in page


# --- 10. The form on load ---------------------------------------------------------------------------

def test_the_form_is_prefilled_with_procurements_category_and_reason(client_as, app_db):
    c, _, req = _requester_with_request(client_as, app_db, brand="SKF", size="20 L")
    seal = central_ids(app_db, "APM", "900", "02")[3]
    # Procurement corrected the Sub-Category while it waited (before a code).
    change_status(app_db, req.id, new_status="submitted",
                  account=account_for(app_db, "procurement"))
    change_category(app_db, req.id, subgroup_id=seal.id,
                    account=account_for(app_db, "procurement"))
    _needs_info(app_db, req, note="ขอรุ่นด้วย")

    r = c.get(_url(req))
    assert r.status_code == 200
    page = r.text
    assert 'name="item_name" value="Ball Bearing" required' in page
    assert 'name="brand" value="SKF"' in page and 'name="size" value="20 L"' in page
    assert f'<option value="{seal.id}" selected>' in page
    assert "จัดซื้อต้องการ: ขอรุ่นด้วย" in page
    assert 'name="reply"' in page and "ส่งกลับให้จัดซื้อ" in page
    assert 'hx-trigger="load"' in page  # dup check on load (duplicates only)
    assert 'name="factory_id"' not in page  # Plant shown, never posted


def test_my_requests_offers_the_resubmit_button_only_for_needs_info(client_as, app_db):
    c, me, req = _requester_with_request(client_as, app_db)
    other = _submit(app_db, me, base="Seal Ring")
    page = c.get("/my-requests").text
    assert f'href="{_url(req)}"' in page
    assert f'href="{_url(other)}"' not in page


# --- 11. Thai text and spaced units survive -----------------------------------------------------

def test_thai_and_units_survive_a_resubmit(client_as, app_db):
    c, _, req = _requester_with_request(client_as, app_db, base="ถังน้ำ", size="20 L")
    assert c.post(_url(req), data=_form(req, brand="ตราช้าง")).status_code == 200
    req = _fresh(app_db, req)
    assert req.base_name == "ถังน้ำ" and req.size == "20 L"
    assert req.item_name == "BEARING - ถังน้ำ ตราช้าง - 20 L"


# --- 12. A blank Search name is classified before the row is claimed ---------------------------

def test_a_blank_search_name_is_classified_before_the_claim(client_as, app_db, monkeypatch):
    from app.services import classifier

    c, _, req = _requester_with_request(client_as, app_db)
    seen: list[str] = []

    def fake_classify(db, name, **kwargs):
        # The status the classifier sees: still needs_info means no claim yet,
        # so no row lock is held while an LLM may be called.
        seen.append(db.scalar(select(ItemRequest.status).where(ItemRequest.id == req.id)))
        return {"suggestion": "BALL BEARING"}

    monkeypatch.setattr(classifier, "classify", fake_classify)
    r = c.post(_url(req), data=_form(req, search_name=""))
    assert r.status_code == 200, r.text
    assert seen == ["needs_info"]
    assert _fresh(app_db, req).search_name == "BALL BEARING"


# --- Code review 2026-10-16: an untouched form must not look edited -------------------------------

def test_the_page_checks_duplicates_on_load_without_category_suggestions(client_as, app_db):
    # The suggestions could auto-pick another category on load (review #1).
    c, _, req = _requester_with_request(client_as, app_db)
    page = c.get(_url(req)).text
    item_input = page.split('id="item_name"', 1)[1].split(">", 1)[0]
    assert "load" not in item_input
    assert 'hx-trigger="load"' in page and '"dup_only": "1"' in page


def test_duplicates_only_skips_the_suggestions(client_as, app_db, monkeypatch):
    from app.services import categorizer, classifier

    def boom(*args, **kwargs):
        raise AssertionError("no suggestion on a duplicates-only check")

    monkeypatch.setattr(classifier, "classify", boom)
    monkeypatch.setattr(categorizer, "suggest_category", boom)
    c = client_as("requester", plant="APM")
    factory = central_ids(app_db, "APM")[0]
    r = c.post("/fragments/duplicates",
               data={"factory_id": factory.id, "item_name": "Ball Bearing", "dup_only": "1"})
    assert r.status_code == 200 and "pickCategory" not in r.text


def _no_edit(c, app_db, req) -> ItemRequest:
    """Resubmit exactly what the page shows; the request must not be edited."""
    name = req.item_name
    assert c.post(_url(req), data=_form(req)).status_code == 200
    req = _fresh(app_db, req)
    assert req.item_name == name
    assert "request_edited" not in [e.action for e in _events(app_db, req)]
    return req


def test_an_inactive_procurement_category_and_uom_stay_selected(client_as, app_db):
    from app.models import ProcurementCategory, Uom

    uom = app_db.scalar(select(Uom).where(Uom.active).order_by(Uom.code.desc()))
    c, _, req = _requester_with_request(client_as, app_db, uom=uom.code,
                                        procurement_category="Old Cat")
    app_db.add(ProcurementCategory(source=central_ids(app_db)[0].item_source, label="Old Cat",
                                   active=False))
    uom.active = False
    app_db.commit()
    page = c.get(_url(req)).text
    assert '<option value="Old Cat" selected>' in page
    assert f'<option value="{uom.code}" selected>' in page
    req = _no_edit(c, app_db, req)
    assert req.uom == uom.code and req.procurement_category == "Old Cat"


def test_a_long_stored_search_name_is_not_an_edit(client_as, app_db):
    c, _, req = _requester_with_request(client_as, app_db)
    req.search_name = "S" * 80  # longer than a form submit would store
    app_db.commit()
    assert _no_edit(c, app_db, req).search_name == "S" * 80


def test_a_spec_note_starting_with_a_newline_is_not_an_edit(client_as, app_db):
    c, _, req = _requester_with_request(client_as, app_db, spec_note="\nEPDM")
    data = _form(req, spec_note="EPDM")  # what a browser posts back from the textarea
    assert c.post(_url(req), data=data).status_code == 200
    assert "request_edited" not in [e.action for e in _events(app_db, req)]


def test_an_empty_classification_is_not_retried_under_the_claim(client_as, app_db, monkeypatch):
    from app.services import classifier

    c, _, req = _requester_with_request(client_as, app_db)
    seen: list[str] = []

    def empty_classify(db, name, **kwargs):
        seen.append(db.scalar(select(ItemRequest.status).where(ItemRequest.id == req.id)))
        return {"suggestion": ""}

    monkeypatch.setattr(classifier, "classify", empty_classify)
    r = c.post(_url(req), data=_form(req, search_name="", brand="NSK"))
    assert r.status_code == 200, r.text
    assert seen == ["needs_info"]


def test_a_resubmit_moves_updated_at(client_as, app_db):
    from datetime import datetime

    c, _, req = _requester_with_request(client_as, app_db)
    req.updated_at = datetime(2026, 1, 1)
    req.review_note = None  # Needs Info without a note: no ORM column left to change
    app_db.commit()
    _no_edit(c, app_db, req)
    assert _fresh(app_db, req).updated_at > datetime(2026, 1, 1)


def test_the_reply_is_one_normalised_line(client_as, app_db):
    # A reply line must never pass for a system line ("duplicate candidates: …").
    c, _, req = _requester_with_request(client_as, app_db)
    reply = "ใส่ขนาดแล้ว\nduplicate candidates: X  นํา"
    assert c.post(_url(req), data=_form(req, reply=reply)).status_code == 200
    submitted = [e for e in _events(app_db, req) if e.action == "submitted"][-1]
    assert submitted.detail.splitlines()[0] == "ใส่ขนาดแล้ว duplicate candidates: X นำ"


def test_an_overlong_reply_is_refused(client_as, app_db):
    c, _, req = _requester_with_request(client_as, app_db)
    r = c.post(_url(req), data=_form(req, reply="ก" * 1001))
    assert r.status_code == 422 and "1000" in r.text
    assert _fresh(app_db, req).status == "needs_info"


# --- Code review round 2 (2026-10-16) ------------------------------------------------------------

def test_an_inactive_sub_category_stays_selected(client_as, app_db):
    c, _, req = _requester_with_request(client_as, app_db)
    sub = app_db.get(CodeGroup, req.subgroup_id)
    sub.active = False
    app_db.commit()
    page = c.get(_url(req)).text
    assert f'<option value="{sub.id}" selected>' in page
    req = _no_edit(c, app_db, req)
    assert req.subgroup_id == sub.id


def test_typing_on_the_resubmit_form_never_auto_picks_a_category(client_as, app_db):
    c, _, req = _requester_with_request(client_as, app_db)
    page = c.get(_url(req)).text
    for field in ("item_name", "brand", "model"):
        tag = page.split(f'name="{field}"', 1)[1].split(">", 1)[0]
        assert '"dup_only": "1"' in tag, field


def test_a_spec_note_posted_back_with_crlf_is_not_an_edit(client_as, app_db):
    c, _, req = _requester_with_request(client_as, app_db, spec_note="a\nb")
    assert c.post(_url(req), data=_form(req, spec_note="a\r\nb")).status_code == 200
    assert "request_edited" not in [e.action for e in _events(app_db, req)]


def test_clearing_the_search_name_is_an_edit_whatever_the_classifier_says(
        client_as, app_db, monkeypatch):
    from app.services import classifier

    c, _, req = _requester_with_request(client_as, app_db)
    monkeypatch.setattr(classifier, "classify",
                        lambda db, name, **kw: {"suggestion": req.search_name})
    assert c.post(_url(req), data=_form(req, search_name="")).status_code == 200
    assert "request_edited" in [e.action for e in _events(app_db, req)]


def test_a_request_deleted_before_the_claim_is_404_not_500(app_db, monkeypatch):
    from sqlalchemy import delete

    from app.services import requests as svc

    me = account_for(app_db, "requester", plant="APM")
    req = _submit(app_db, me)
    _needs_info(app_db, req)
    real = svc.resubmittable

    def then_deleted(db, request_id, account):
        found = real(db, request_id, account)
        db.execute(delete(RequestEvent).where(RequestEvent.request_id == request_id))
        db.execute(delete(ItemRequest).where(ItemRequest.id == request_id))
        db.commit()
        return found

    monkeypatch.setattr(svc, "resubmittable", then_deleted)
    import pytest

    with pytest.raises(svc.RequestNotFound):
        svc.resubmit_request(app_db, req.id, me, reply=REPLY, **{
            k: v for k, v in _form(req).items() if k != "reply"})


def test_the_preview_starts_with_the_stored_item_name(client_as, app_db):
    # With no edit the stored name is kept, even one Procurement typed.
    c, _, req = _requester_with_request(client_as, app_db)
    edit_name(app_db, req.id, new_name="BEARING - ชื่อที่จัดซื้อพิมพ์",
              account=account_for(app_db, "procurement"))
    page = c.get(_url(req)).text
    preview = page.split('id="name-preview"', 1)[1].split("</div>", 1)[0]
    assert "BEARING - ชื่อที่จัดซื้อพิมพ์" in preview
