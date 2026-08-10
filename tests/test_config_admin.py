from sqlalchemy import select

from app.models import CodeGroup, CodeSystem, GroupExportMap, ProcurementCategory, Uom
from app.services import config_admin
from app.services.config_admin import ConfigError

import pytest


def test_add_and_toggle_uom(db_session):
    before = len(config_admin.list_uoms(db_session))
    u = config_admin.add_uom(db_session, "Roll", "ม้วน")
    assert len(config_admin.list_uoms(db_session)) == before + 1
    assert u.active
    config_admin.toggle_uom(db_session, u.id)
    assert not db_session.get(Uom, u.id).active


def test_add_duplicate_uom_rejected(db_session):
    config_admin.add_uom(db_session, "Roll", "ม้วน")
    with pytest.raises(ConfigError):
        config_admin.add_uom(db_session, "Roll", "again")


def test_categories_scoped_by_source(db_session):
    config_admin.add_category(db_session, "CBD", "99 Test CBD cat")
    d365 = config_admin.active_categories(db_session, "D365")
    cbd = config_admin.active_categories(db_session, "CBD")
    assert any("Computer expenses" in c.label for c in d365)
    assert all(c.source == "CBD" for c in cbd)
    assert any("Test CBD" in c.label for c in cbd)


def test_set_group_map_creates_then_updates(db_session):
    from tests.conftest import central_ids

    _f, system, group, _sub = central_ids(db_session)
    config_admin.set_group_map(
        db_session, group.id, item_group_id="SP", model_group_id="EN", group_type_code="SP"
    )
    mp = db_session.scalar(
        select(GroupExportMap).where(GroupExportMap.code_group_id == group.id)
    )
    assert mp.item_group_id == "SP"
    config_admin.set_group_map(
        db_session, group.id, item_group_id="TES", model_group_id="EN", group_type_code="SP"
    )
    db_session.refresh(mp)
    assert mp.item_group_id == "TES"


def test_config_page_and_add_via_http(client, db_session):
    resp = client.get("/admin/config")
    assert resp.status_code == 200
    assert "Procurement Category" in resp.text

    r = client.post("/admin/config/uom", data={"code": "Btl", "name": "ขวด"})
    assert r.status_code == 200
    assert db_session.scalar(select(Uom).where(Uom.code == "Btl")) is not None


def test_category_dropdown_reflects_factory_source(client, db_session):
    from app.models import Factory

    apm = db_session.scalar(select(Factory).where(Factory.code == "APM"))
    resp = client.get(f"/fragments/categories?factory_id={apm.id}")
    assert resp.status_code == 200
    assert "Computer expenses" in resp.text
