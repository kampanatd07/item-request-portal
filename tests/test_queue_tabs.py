"""STORY-018: the queue's filter tabs show how many requests each status holds
and mark the current filter."""

from app.services.requests import change_status, count_by_status, submit_request
from tests.conftest import account_for, central_ids


def _submit(db, name: str = "Ball Bearing"):
    factory, system, group, sub = central_ids(db)
    return submit_request(db, account_for(db, "requester", plant="APM"),
                          factory_id=factory.id, code_system_id=system.id,
                          group_id=group.id, subgroup_id=sub.id, item_name=name)


def test_count_by_status_counts_each_status(app_db) -> None:
    assert count_by_status(app_db) == {}
    _submit(app_db)
    second = _submit(app_db, "Seal Ring")
    change_status(app_db, second.id, new_status="needs_info", note="ขอรุ่น",
                  account=account_for(app_db))
    assert count_by_status(app_db) == {"submitted": 1, "needs_info": 1}


def test_tabs_show_counts_and_mark_the_current_filter(client_as, app_db) -> None:
    _submit(app_db)
    _submit(app_db, "Seal Ring")
    c = client_as("procurement")
    page = c.get("/queue?status=submitted").text
    page = page.split('<nav class="tabs"', 1)[1].split("</nav>", 1)[0]  # the tabs, not the sidebar
    tab = page.split('href="/queue?status=submitted"', 1)[1].split("</a>", 1)[0]
    assert 'aria-current="page"' in tab and '<span class="tab-count">2</span>' in tab
    everything = page.split('href="/queue"', 1)[1].split("</a>", 1)[0]
    assert 'aria-current' not in everything and '<span class="tab-count">2</span>' in everything
    rejected = page.split('href="/queue?status=rejected"', 1)[1].split("</a>", 1)[0]
    assert '<span class="tab-count">0</span>' in rejected


def test_an_empty_filter_says_so_and_links_back(client_as, app_db) -> None:
    _submit(app_db)
    page = client_as("procurement").get("/queue?status=rejected").text
    assert "ยังไม่มีคำขอในสถานะนี้" in page and '<a href="/queue">ดูคำขอทั้งหมด</a>' in page
