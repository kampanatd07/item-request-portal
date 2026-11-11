"""STORY-018: the reference-data page in tabs, with filters on the long lists.
The tabs and filters run in the browser; these tests pin the markup they
read and the counts the server writes into it."""

import re

from app.services import config_admin
from tests.conftest import central_ids


def _page(client) -> str:
    r = client.get("/admin/config")
    assert r.status_code == 200
    return r.text


def test_one_tab_per_panel(client, db_session) -> None:
    page = _page(client)
    tabs = re.findall(r'data-tab="([a-z]+)"', page)
    panels = re.findall(r'<section class="card config-panel" id="([a-z]+)"', page)
    assert tabs == panels == ["domains", "uom", "categories", "mapping", "thai", "terms"]


def test_mapping_tab_counts_filled_groups(client, db_session) -> None:
    total = len(config_admin.list_group_maps(db_session))
    _f, _s, group, _sub = central_ids(db_session)
    config_admin.set_group_map(db_session, group.id, item_group_id="SP",
                               model_group_id="", group_type_code="")
    page = _page(client)
    assert f'Mapping D365 <span class="tab-count">1/{total}</span>' in page
    row = re.search(rf'<tr data-search="[^"]*" data-state="(\w+)">\s*<td><code>{group.code}</code>', page)
    assert row and row.group(1) == "filled"
    assert f"ยังไม่กรอก {total - 1}" in page


def test_mapping_inputs_belong_to_their_rows_form(client, db_session) -> None:
    _f, _s, group, _sub = central_ids(db_session)
    page = _page(client)
    assert f'<form id="gm-{group.id}" hx-post="/admin/config/groupmap/{group.id}"' in page
    for field in ("item_group_id", "model_group_id", "group_type_code"):
        assert f'<input form="gm-{group.id}" name="{field}"' in page
    # No form wraps table cells any more (invalid HTML).
    assert not re.search(r"<form[^>]*>\s*<td", page)


def test_terms_rows_carry_search_text_and_state(client, db_session) -> None:
    terms = config_admin.list_terms(db_session)
    page = _page(client)
    assert page.count('data-state="on"') + page.count('data-state="off"') == len(terms)
    first = terms[0]
    assert f'data-search="{first.term.lower()}"' in page
    assert f"ทั้งหมด {len(terms)}" in page


def test_saving_a_mapping_still_works_over_http(client, db_session) -> None:
    from sqlalchemy import select

    from app.models import GroupExportMap
    _f, _s, group, _sub = central_ids(db_session)
    r = client.post(f"/admin/config/groupmap/{group.id}",
                    data={"item_group_id": "SP", "model_group_id": "EN", "group_type_code": "SP"})
    assert r.status_code == 200 and 'data-tab="mapping"' in r.text
    mp = db_session.scalar(select(GroupExportMap).where(GroupExportMap.code_group_id == group.id))
    assert mp.item_group_id == "SP"
