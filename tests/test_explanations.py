"""STORY-018: on-page explanations: status meanings, the requester's progress
bar, "waiting for you" first on My requests, and the help page."""

from app.services.requests import change_status, submit_request
from app.templating import PROGRESS_STEPS, STATUS_HELP, STATUS_LABELS, STATUS_STEPS_DONE, templates
from tests.conftest import account_for, central_ids


def _submit(db, name: str = "Ball Bearing", requester=None):
    factory, system, group, sub = central_ids(db)
    return submit_request(db, requester or account_for(db, "requester", plant="APM"),
                          factory_id=factory.id, code_system_id=system.id,
                          group_id=group.id, subgroup_id=sub.id, item_name=name)


def _progress(status: str) -> str:
    return templates.get_template("partials/progress.html").render(
        status=status, progress_steps=PROGRESS_STEPS, status_steps_done=STATUS_STEPS_DONE)


def test_every_status_has_a_meaning_and_a_who() -> None:
    assert set(STATUS_HELP) == set(STATUS_LABELS)
    assert all(meaning and who for meaning, who in STATUS_HELP.values())


def test_every_status_but_rejected_has_a_place_on_the_progress_bar() -> None:
    assert set(STATUS_STEPS_DONE) == set(STATUS_LABELS) - {"rejected"}
    assert all(1 <= n <= len(PROGRESS_STEPS) for n in STATUS_STEPS_DONE.values())


def test_progress_marks_done_and_current_steps() -> None:
    html = _progress("in_review")
    assert html.count('class="done"') == 2 and html.count('class="current"') == 1
    assert "เสร็จ 2 จาก 4 ขั้น" in html
    assert 'class="progress waiting"' in _progress("needs_info")
    assert _progress("notified").count('class="done"') == 4 and 'class="current"' not in _progress("notified")
    assert "<ol" not in _progress("rejected")


def test_queue_and_my_requests_carry_the_legend(client_as, app_db) -> None:
    from sqlalchemy import select

    from app.models import Account
    requester = client_as("requester", plant="APM")
    _submit(app_db, requester=app_db.scalar(
        select(Account).where(Account.email == "requester0@test.local")))
    for page in (client_as("procurement").get("/queue").text,
                 requester.get("/my-requests").text):
        assert "สถานะหมายถึงอะไร?" in page
        assert STATUS_HELP["approved"][0] in page


def test_my_requests_without_requests_has_no_legend(client_as, app_db) -> None:
    page = client_as("requester", plant="APM").get("/my-requests").text
    assert "ยังไม่มีคำขอ" in page and "สถานะหมายถึงอะไร?" not in page


def test_my_requests_puts_requests_waiting_for_me_first(client_as, app_db) -> None:
    c = client_as("requester", plant="APM")
    from sqlalchemy import select

    from app.models import Account
    me = app_db.scalar(select(Account).where(Account.email == "requester0@test.local"))
    older = _submit(app_db, "Seal Ring", requester=me)
    _submit(app_db, "Ball Bearing", requester=me)  # newest, not waiting
    change_status(app_db, older.id, new_status="needs_info", note="ขอรุ่น",
                  account=account_for(app_db))
    page = c.get("/my-requests").text
    body = page.split("<tbody>", 1)[1]
    assert body.index("Seal Ring") < body.index("Ball Bearing")
    assert "จัดซื้อขอข้อมูลเพิ่ม 1 คำขอ" in page and f'href="#request-{older.id}"' in page
    assert page.count(f'id="request-{older.id}"') == 1


def test_my_requests_without_waiting_requests_has_no_callout(client_as, app_db) -> None:
    c = client_as("requester", plant="APM")
    from sqlalchemy import select

    from app.models import Account
    me = app_db.scalar(select(Account).where(Account.email == "requester0@test.local"))
    _submit(app_db, requester=me)
    assert "จัดซื้อขอข้อมูลเพิ่ม" not in c.get("/my-requests").text.split("<details", 1)[0]


def test_status_panel_says_what_the_status_means(client_as, app_db) -> None:
    req = _submit(app_db)
    page = client_as("procurement").get(f"/queue/{req.id}").text
    assert STATUS_HELP["submitted"][0] in page and "ใครทำต่อ: จัดซื้อ" in page


def test_help_page_for_anyone_signed_in(client_as) -> None:
    page = client_as("requester", plant="APM").get("/help")
    assert page.status_code == 200
    assert "วิธีใช้งาน" in page.text and STATUS_HELP["needs_info"][0] in page.text
    assert 'href="/help" aria-current="page"' in page.text


def test_help_page_needs_a_login(anon_client) -> None:
    r = anon_client.get("/help", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/login")
