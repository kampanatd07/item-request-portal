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
