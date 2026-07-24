from sqlalchemy import select

from app.models import CodeGroup, CodeSystem, Factory, ItemRequest, RequestEvent


def _ids(db, factory_code: str, system_code: str, group_code: str):
    factory = db.scalar(select(Factory).where(Factory.code == factory_code))
    system = db.scalar(select(CodeSystem).where(CodeSystem.code == system_code))
    group = db.scalar(
        select(CodeGroup).where(
            CodeGroup.code_system_id == system.id,
            CodeGroup.code == group_code,
            CodeGroup.parent_id.is_(None),
        )
    )
    return factory, system, group


def test_submit_d365_stock_request_happy_path(client, db_session):
    factory, system, group = _ids(db_session, "APM", "D365_STOCK", "800")
    resp = client.post(
        "/requests",
        data={
            "requester_name": "สมชาย ทดสอบ",
            "requester_email": "somchai@example.com",
            "factory_id": factory.id,
            "code_system_id": system.id,
            "group_id": group.id,
            "item_name": "Ball Bearing",
            "brand": "SKF",
            "model": "UCF209-28",
        },
    )
    assert resp.status_code == 200
    assert "ส่งคำขอเรียบร้อย" in resp.text

    req = db_session.scalar(select(ItemRequest))
    assert req.status == "submitted"
    assert req.item_name == "Ball Bearing"
    events = list(db_session.scalars(select(RequestEvent)))
    assert [e.action for e in events] == ["submitted"]


def test_submit_cbd_stock_requires_subgroup(client, db_session):
    factory, system, group = _ids(db_session, "CBD", "CBD_STOCK", "01")
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


def test_submit_rejects_group_from_wrong_system(client, db_session):
    factory, system, _ = _ids(db_session, "APM", "D365_STOCK", "800")
    wrong_system = db_session.scalar(
        select(CodeSystem).where(CodeSystem.code == "D365_SERVICE")
    )
    wrong_group = db_session.scalar(
        select(CodeGroup).where(
            CodeGroup.code_system_id == wrong_system.id, CodeGroup.code == "700"
        )
    )
    resp = client.post(
        "/requests",
        data={
            "requester_name": "ทดสอบ",
            "requester_email": "t@example.com",
            "factory_id": factory.id,
            "code_system_id": system.id,
            "group_id": wrong_group.id,
            "item_name": "งานซ่อม",
        },
    )
    assert resp.status_code == 422
    assert "ไม่ถูกต้อง" in resp.text
