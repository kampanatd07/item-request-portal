"""STORY-018 follow-ups (review of f0384b4..997dc0f): queue row clicks, the
sub-category select, one tab per status, one shared status table."""

from app.services.requests import submit_request
from app.templating import STATUS_HELP
from tests.conftest import account_for, central_ids


def _submit(db):
    factory, system, group, sub = central_ids(db)
    return submit_request(db, account_for(db, "requester", plant="APM"),
                          factory_id=factory.id, code_system_id=system.id,
                          group_id=group.id, subgroup_id=sub.id, item_name="Ball Bearing")


def _queue_script(page: str) -> str:
    return page.split('table.queue")', 1)[1].split("</script>", 1)[0]


def test_a_click_on_a_code_never_opens_the_request(client_as, app_db) -> None:
    _submit(app_db)
    script = _queue_script(client_as("procurement").get("/queue").text)
    skipped = script.split("closest(", 1)[1].split(")", 1)[0]
    assert "code" in skipped  # a double-click on a code selects it for copying
    assert "window.getSelection()" in script


def test_modifier_and_middle_clicks_open_a_new_tab(client_as, app_db) -> None:
    _submit(app_db)
    script = _queue_script(client_as("procurement").get("/queue").text)
    assert "e.ctrlKey || e.metaKey || e.shiftKey" in script
    assert "auxclick" in script and 'window.open(link.href, "_blank")' in script


def test_pick_category_keeps_an_empty_sub_category_disabled(client_as) -> None:
    page = client_as("requester", plant="APM").get("/").text
    script = page.split("function pickCategory", 1)[1].split("\n}\n", 1)[0]
    assert "if (hasOptions) { subSel.disabled = false;" in script


def test_every_reachable_status_has_exactly_one_tab() -> None:
    from app.services.requests import DONE_STATUSES, TRANSITIONS, WORK_STATUSES

    reachable = set(TRANSITIONS) | {s for t in TRANSITIONS.values() for s in t}
    assert sorted(WORK_STATUSES + DONE_STATUSES) == sorted(reachable)


def test_the_queue_legend_uses_the_shared_status_table(client_as, app_db) -> None:
    _submit(app_db)
    page = client_as("procurement").get("/queue").text
    assert page.count('<table class="legend-table">') == 1
    table = page.split('<table class="legend-table">', 1)[1].split("</table>", 1)[0]
    for status in STATUS_HELP:
        assert f'<span class="badge {status}">' in table


# --- Review of 3888c5a..b7a8352: the automatic pick never overwrites a manual choice ---

def _pick_category_script(page: str) -> str:
    return page.split("function pickCategory", 1)[1].split("\n}\n", 1)[0]


def test_auto_pick_still_runs_and_its_note_can_be_hidden(client_as, app_db, monkeypatch) -> None:
    from app.models import CodeGroup
    from app.services import categorizer
    from app.services.categorizer import Suggestion

    seal = central_ids(app_db, "APM", "900", "02")[3]
    monkeypatch.setattr(categorizer, "suggest_category", lambda db, name, **kw: [
        Suggestion(app_db.get(CodeGroup, seal.parent_id), seal, 0.95, "test")])
    c = client_as("requester", plant="APM")
    factory = central_ids(app_db, "APM")[0]
    r = c.post("/fragments/duplicates", data={"factory_id": factory.id, "item_name": "Oil Seal"})
    assert "<script>pickCategory(" in r.text  # nobody chose yet: the top suggestion is picked
    assert "data-autopick-note" in r.text  # and the script can hide its note when it is not


def test_auto_pick_keeps_a_category_the_requester_chose(client_as) -> None:
    page = client_as("requester", plant="APM").get("/").text
    script = _pick_category_script(page)
    guard, rest = script.split("groupSel.value = groupId;", 1)
    # The automatic call (no button) returns before touching the selects once
    # the Requester has chosen; a chip click counts as choosing.
    assert "if (!btn && categoryChosenByUser && groupSel.value)" in guard
    assert "return;" in guard.split("categoryChosenByUser && groupSel.value", 1)[1]
    assert "if (btn) categoryChosenByUser = true;" in guard
    # A select changed by hand marks the choice.
    listener = page.split("var categoryChosenByUser = false;", 1)[1].split("function pickCategory", 1)[0]
    assert "'group_id'" in listener and "'subgroup_id'" in listener
    assert "categoryChosenByUser = true" in listener
