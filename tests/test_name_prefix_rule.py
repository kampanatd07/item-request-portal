"""STORY-013 ticket 01: one Name Prefix rule; the queue warns when a name does
not start with its category's prefix."""

import pytest

from app.models import CodeGroup, ItemRequest
from app.services.requests import change_status, edit_name, submit_request
from tests.conftest import account_for, central_ids

WARNING = "ชื่อไม่ได้ขึ้นต้นด้วย prefix ของหมวดปัจจุบัน"


# --- The rule ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("name, prefix, starts", [
    ("BEARING - Ball Bearing SKF - 20 L", "BEARING", True),
    ("Bearing - Ball Bearing", "BEARING", True),           # any case (Q8)
    ("BEARING - ลูกปืน 6205 - 20 L", "Bearing", True),      # prefix as stored, Thai after it
    ("Ball Bearing SKF - 20 L", "BEARING", False),         # Name Override without a prefix
    ("SEAL - Oil Seal", "BEARING", False),                 # another category's prefix
    ("BEARING", "BEARING", False),                         # only the prefix, no separator
    ("BEARING-Ball Bearing", "BEARING", False),            # "-" without spaces
    ("BEARINGS - Ball Bearing", "BEARING", False),         # a longer word is not the prefix
    ("BEARING - Ball Bearing", None, False),               # no prefix in the taxonomy
    ("BEARING - Ball Bearing", "", False),
])
def test_starts_with_prefix(name, prefix, starts):
    from app.services.naming import starts_with_prefix

    assert starts_with_prefix(name, prefix) is starts


@pytest.mark.parametrize("name, prefix, searchable", [
    ("BEARING - Ball Bearing SKF - 20 L", "BEARING", "Ball Bearing SKF - 20 L"),
    ("bearing - Ball Bearing", "BEARING", "Ball Bearing"),
    ("BEARING - ลูกปืน 6205", "BEARING", "ลูกปืน 6205"),
    ("Ball Bearing SKF - 20 L", "BEARING", "Ball Bearing SKF - 20 L"),  # whole name kept
    ("SEAL - Oil Seal", "BEARING", "SEAL - Oil Seal"),
    ("BEARING", "BEARING", "BEARING"),
    ("BEARING - Ball Bearing", None, "BEARING - Ball Bearing"),
])
def test_searchable_part(name, prefix, searchable):
    from app.services.naming import searchable_part

    assert searchable_part(name, prefix) == searchable


def test_the_prefix_is_compared_as_compose_name_writes_it():
    # compose_name cleans the prefix and cuts it to 16 characters; the rule must
    # match what compose_name actually put in the name.
    from app.services.naming import compose_name, starts_with_prefix

    long_prefix = "MAINTENANCE SERVICE WORK"
    name = compose_name("Pump repair", category_prefix=long_prefix)
    assert starts_with_prefix(name, long_prefix)


# --- The queue detail -----------------------------------------------------------------------------------

def _request(db) -> ItemRequest:
    factory, system, group, sub = central_ids(db)
    return submit_request(db, account_for(db, "requester", plant="APM"),
                          factory_id=factory.id, code_system_id=system.id, group_id=group.id,
                          subgroup_id=sub.id, item_name="Ball Bearing", brand="SKF")


def _panel(page: str) -> str:
    start = page.index('id="name-panel"')
    return page[start:page.index("</div>", start)]


def test_a_composed_name_has_no_warning(client_as, app_db):
    req = _request(app_db)
    page = client_as("procurement").get(f"/queue/{req.id}").text
    assert WARNING not in page


def test_a_name_override_without_the_prefix_warns_in_the_name_panel(client_as, app_db):
    req = _request(app_db)
    edit_name(app_db, req.id, new_name="Ball Bearing SKF - 20 L",
              account=account_for(app_db, "procurement"))
    page = client_as("procurement").get(f"/queue/{req.id}").text
    assert f"{WARNING} (BEARING)" in _panel(page)


def test_a_name_override_with_the_prefix_in_another_case_does_not_warn(client_as, app_db):
    req = _request(app_db)
    edit_name(app_db, req.id, new_name="Bearing - Ball Bearing SKF",
              account=account_for(app_db, "procurement"))
    assert WARNING not in client_as("procurement").get(f"/queue/{req.id}").text


def test_fixing_the_name_removes_the_warning_at_once(client_as, app_db):
    req = _request(app_db)
    edit_name(app_db, req.id, new_name="Ball Bearing SKF",
              account=account_for(app_db, "procurement"))
    c = client_as("procurement")
    assert WARNING in c.get(f"/queue/{req.id}").text
    r = c.post(f"/queue/{req.id}/name", data={"new_name": "BEARING - Ball Bearing SKF"})
    assert r.status_code == 200 and WARNING not in r.text  # the re-drawn name panel
    bad = c.post(f"/queue/{req.id}/name", data={"new_name": "Ball Bearing SKF"})
    assert f"{WARNING} (BEARING)" in bad.text


def test_a_name_prefix_edited_in_the_taxonomy_since_warns(client_as, app_db):
    req = _request(app_db)
    sub = app_db.get(CodeGroup, req.subgroup_id)
    sub.name_prefix = "BALL BEARING"
    app_db.commit()
    page = client_as("procurement").get(f"/queue/{req.id}").text
    assert f"{WARNING} (BALL BEARING)" in _panel(page)


def test_approval_is_not_blocked_by_the_warning(client_as, app_db):
    req = _request(app_db)
    edit_name(app_db, req.id, new_name="Ball Bearing SKF",
              account=account_for(app_db, "procurement"))
    r = client_as("administrator").post(f"/queue/{req.id}/status",
                                        data={"new_status": "approved"})
    assert r.status_code == 200, r.text
    app_db.expire_all()
    assert app_db.get(ItemRequest, req.id).status == "approved"



# --- Review 2026-10-20: prefixes longer than 16, None names, exported requests ----------------------

def test_a_cut_on_a_space_leaves_no_double_space():
    from app.services.naming import compose_name, searchable_part, starts_with_prefix

    prefix = "SPARE PARTS AND ITEMS"  # the 16-character cut ends on a space
    name = compose_name("Bolt", category_prefix=prefix)
    assert name == "SPARE PARTS AND - Bolt"
    assert starts_with_prefix(name, prefix)
    assert searchable_part(name, prefix) == "Bolt"


def test_searchable_part_of_no_name_is_empty():
    from app.services.naming import searchable_part

    assert searchable_part(None, "BEARING") == ""
    assert searchable_part("", "BEARING") == ""


def _with_prefix(db, req: ItemRequest, prefix: str) -> None:
    sub = db.get(CodeGroup, req.subgroup_id)
    sub.name_prefix = prefix
    db.commit()


def test_the_warning_names_the_prefix_as_a_name_carries_it(client_as, app_db):
    req = _request(app_db)
    _with_prefix(app_db, req, "MAINTENANCE SERVICE WORK")
    c = client_as("procurement")
    assert f"{WARNING} (MAINTENANCE SERV)" in _panel(c.get(f"/queue/{req.id}").text)
    # Following the warning word for word clears it.
    r = c.post(f"/queue/{req.id}/name", data={"new_name": "MAINTENANCE SERV - Ball Bearing"})
    assert r.status_code == 200 and WARNING not in r.text


def test_a_trailing_space_cut_can_be_matched_by_a_typed_name(client_as, app_db):
    req = _request(app_db)
    _with_prefix(app_db, req, "SPARE PARTS AND ITEMS")
    c = client_as("procurement")
    page = c.get(f"/queue/{req.id}").text
    assert f"{WARNING} (SPARE PARTS AND)" in _panel(page)
    r = c.post(f"/queue/{req.id}/name", data={"new_name": "SPARE PARTS AND - Ball Bearing"})
    assert WARNING not in r.text


def test_an_exported_request_is_warned_but_not_asked_to_edit(client_as, app_db):
    req = _request(app_db)
    edit_name(app_db, req.id, new_name="Ball Bearing SKF",
              account=account_for(app_db, "procurement"))
    req.status = "exported"  # the name can no longer be edited
    app_db.commit()
    panel = _panel(client_as("procurement").get(f"/queue/{req.id}").text)
    assert f"{WARNING} (BEARING)" in panel
    assert "แก้ชื่อ" not in panel.split(WARNING, 1)[1].split("</p>", 1)[0]


def test_an_editable_request_is_asked_to_fix_the_name(client_as, app_db):
    req = _request(app_db)
    edit_name(app_db, req.id, new_name="Ball Bearing SKF",
              account=account_for(app_db, "procurement"))
    panel = _panel(client_as("procurement").get(f"/queue/{req.id}").text)
    assert f"{WARNING} (BEARING) — ตรวจและแก้ชื่อ" in panel
