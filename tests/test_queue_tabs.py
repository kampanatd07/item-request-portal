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


# --- The "already in AX" tab folds exported / created / notified (Peter, 2026-11-09) ----------

def _set_status(db, req, status: str) -> None:
    req.status = status  # straight to a post-export status: these tests only read the queue
    db.commit()


def _tabs(page: str) -> str:
    return page.split('<nav class="tabs"', 1)[1].split("</nav>", 1)[0]


def test_list_queue_done_group_returns_every_post_export_status(app_db) -> None:
    from app.services.requests import DONE_GROUP, list_queue

    open_req = _submit(app_db, "Open")
    done = [_submit(app_db, s) for s in ("Exported", "Created", "Notified")]
    for req, status in zip(done, ("exported", "created", "notified")):
        _set_status(app_db, req, status)
    ids = {r.id for r in list_queue(app_db, DONE_GROUP)}
    assert ids == {r.id for r in done} and open_req.id not in ids
    assert [r.id for r in list_queue(app_db, "created")] == [done[1].id]


def test_done_tab_counts_and_sub_filters(client_as, app_db) -> None:
    _submit(app_db, "Open")
    for name, status in (("A", "exported"), ("B", "notified"), ("C", "notified")):
        _set_status(app_db, _submit(app_db, name), status)
    c = client_as("procurement")

    page = c.get("/queue").text
    done_tab = _tabs(page).split('href="/queue?status=done"', 1)[1].split("</a>", 1)[0]
    assert "ส่งเข้า AX แล้ว" in done_tab and '<span class="tab-count">3</span>' in done_tab
    assert 'class="subfilters"' not in page  # sub-filters only inside the tab

    page = c.get("/queue?status=notified").text
    done_tab = _tabs(page).split('href="/queue?status=done"', 1)[1].split("</a>", 1)[0]
    assert 'aria-current="page"' in done_tab  # a sub-status keeps the group tab on
    subs = page.split('class="subfilters"', 1)[1].split("</nav>", 1)[0]
    chip = subs.split('href="/queue?status=notified"', 1)[1].split("</a>", 1)[0]
    assert 'aria-current="page"' in chip and '<span class="tab-count">2</span>' in chip
    assert "Open" not in page.split("<tbody>", 1)[1] and "A</a>" not in page


def test_every_status_is_reachable_and_the_tabs_add_up(client_as, app_db) -> None:
    from app.templating import STATUS_LABELS

    for status in STATUS_LABELS:
        _set_status(app_db, _submit(app_db, status), status)
    tabs = _tabs(client_as("procurement").get("/queue").text)
    counts = [int(x.split("</span>", 1)[0]) for x in tabs.split('<span class="tab-count">')[1:]]
    assert counts[0] == len(STATUS_LABELS) and sum(counts[1:]) == counts[0]
