from sqlalchemy import select

from app.models import CodeGroup, CodeSystem, Factory, ItemRequest, RequestEvent


from tests.conftest import central_ids


def _ids(db, factory_code: str, group_code: str, sub_code: str = "01"):
    factory, system, group, sub = central_ids(db, factory_code, group_code, sub_code)
    return factory, system, group, sub


def test_submit_central_request_happy_path(client, db_session):
    factory, system, group, sub = _ids(db_session, "APM", "900", "01")
    resp = client.post(
        "/requests",
        data={
            "requester_name": "สมชาย ทดสอบ",
            "requester_email": "somchai@example.com",
            "factory_id": factory.id,
            "code_system_id": system.id,
            "group_id": group.id,
            "subgroup_id": sub.id,
            "item_name": "Ball Bearing",
            "brand": "SKF",
            "model": "UCF209-28",
        },
    )
    assert resp.status_code == 200
    assert "ส่งคำขอเรียบร้อย" in resp.text

    req = db_session.scalar(select(ItemRequest))
    assert req.status == "submitted"
    # name follows the group standard: [CATEGORY] - [name] - [detail]
    assert req.item_name == "BEARING - Ball Bearing SKF UCF209-28"
    events = list(db_session.scalars(select(RequestEvent)))
    assert [e.action for e in events] == ["submitted"]


def test_submit_requires_subcategory(client, db_session):
    factory, system, group, _sub = _ids(db_session, "CBD", "900", "01")
    resp = client.post(
        "/requests",
        data={
            "requester_name": "สมหญิง ทดสอบ",
            "requester_email": "somying@example.com",
            "factory_id": factory.id,
            "code_system_id": system.id,
            "group_id": group.id,
            "item_name": "Bearing 6205",
        },
    )
    assert resp.status_code == 422
    assert "หมวดย่อย" in resp.text
    assert db_session.scalar(select(ItemRequest)) is None


def test_submit_rejects_subcategory_from_another_group(client, db_session):
    factory, system, group, _ = _ids(db_session, "APM", "900", "01")
    _f, _s, _other_group, other_sub = _ids(db_session, "APM", "700", "02")
    resp = client.post(
        "/requests",
        data={
            "requester_name": "ทดสอบ",
            "requester_email": "t@example.com",
            "factory_id": factory.id,
            "code_system_id": system.id,
            "group_id": group.id,
            "subgroup_id": other_sub.id,
            "item_name": "งานซ่อม",
        },
    )
    assert resp.status_code == 422
    assert "ไม่ถูกต้อง" in resp.text


# --- STORY-009 ticket 01: the Base Name is stored -----------------------------------------------

def _submit_base(client, db_session, base: str, **extra):
    factory, system, group, sub = _ids(db_session, "APM", "900", "01")
    resp = client.post("/requests", data={
        "factory_id": factory.id, "code_system_id": system.id, "group_id": group.id,
        "subgroup_id": sub.id, "item_name": base, **extra})
    assert resp.status_code == 200, resp.text
    return db_session.scalar(select(ItemRequest).order_by(ItemRequest.id.desc())), sub


def test_the_base_name_is_stored_cleaned_like_the_name_part(client, db_session):
    # Same cleaning as compose_name's name part: spaces collapsed, separators
    # and "(ยกเลิก)" dropped. Thai SARA AM is kept exactly as typed.
    req, _ = _submit_base(client, db_session, "  ถังน้ำ   พลาสติก (ยกเลิก) -- ใส ",
                          brand="SKF")
    assert req.base_name == "ถังน้ำ พลาสติก ใส"


def test_composing_from_the_stored_base_name_gives_the_same_item_name(client, db_session):
    from app.services.naming import compose_name

    req, sub = _submit_base(client, db_session, " Ball   Bearing :  ", brand="SKF",
                            model="UCF209-28", size="20l", variant="สีดำ")
    recomposed = compose_name(req.base_name, brand=req.brand, model=req.model,
                              size=req.size, detail=req.variant,
                              category_prefix=sub.name_prefix)
    assert recomposed == req.item_name


def test_a_base_name_that_cleans_to_nothing_is_stored_as_empty(client, db_session):
    # Review 2026-10-16: "--" passes today (the brand carries the name) and was
    # stored as "", neither a Base Name nor the NULL that means "ask again".
    req, _ = _submit_base(client, db_session, "--", brand="SKF")
    assert req.item_name == "BEARING - SKF"  # unchanged behaviour
    assert req.base_name is None
