"""STORY-001 ticket 07: "My requests" page (AC12)."""

import pytest
from sqlalchemy import select

from app.models import Account, ItemRequest
from app.services import auth
from app.services.requests import change_status, list_my_requests, submit_request
from tests.conftest import TEST_PASSWORD, account_for, central_ids, login


def _submit(db, account: Account, name: str = "Ball Bearing", plant: str = "APM") -> ItemRequest:
    factory, system, group, sub = central_ids(db, plant)
    return submit_request(db, account, factory_id=factory.id, code_system_id=system.id,
                          group_id=group.id, subgroup_id=sub.id, item_name=name)


def _me(db, email: str) -> Account:
    return db.scalar(select(Account).where(Account.email == email))


# --- Whose requests (AC12) ------------------------------------------------------------------

def test_lists_only_the_logged_in_accounts_requests(client_as, app_db):
    mine_client = client_as("requester", plant="APM")
    me = _me(app_db, "requester0@test.local")
    colleague = account_for(app_db, "requester", plant="APM")  # same Plant
    _submit(app_db, me, "Mine Bearing")
    _submit(app_db, colleague, "Theirs Bearing")

    page = mine_client.get("/my-requests").text
    assert "Mine Bearing" in page
    assert "Theirs Bearing" not in page


def test_newest_first(app_db):
    me = account_for(app_db, "procurement")
    first, second, third = (_submit(app_db, me, n) for n in ("One", "Two", "Three"))
    assert [r.id for r in list_my_requests(app_db, me)] == [third.id, second.id, first.id]


def test_email_is_stored_lowercase_and_matched_without_case(app_db):
    me = auth.create_account(app_db, "  Mixed.Case@Test.Local ", "M", "procurement",
                             TEST_PASSWORD, must_change_password=False)
    assert me.email == "mixed.case@test.local"
    old = _submit(app_db, me)
    # A request typed in before login existed, with the address as written.
    old.requester_email = " Mixed.CASE@test.local "
    app_db.commit()
    assert [r.id for r in list_my_requests(app_db, me)] == [old.id]


@pytest.mark.parametrize("role,plant", [
    ("requester", "APM"), ("procurement", None), ("administrator", None),
])
def test_available_to_every_role(client_as, role, plant):
    r = client_as(role, plant=plant).get("/my-requests")
    assert r.status_code == 200 and "คำขอของฉัน" in r.text
    assert 'href="/my-requests"' in r.text  # nav link


def test_empty_state_points_to_the_form(client_as):
    assert "ยังไม่มีคำขอ" in client_as("requester", plant="APM").get("/my-requests").text


# --- What a row shows ---------------------------------------------------------------------

def test_review_note_and_usable_code_show(client_as, app_db):
    c = client_as("requester", plant="APM")
    me = _me(app_db, "requester0@test.local")
    req = _submit(app_db, me)
    admin = account_for(app_db, "administrator")
    change_status(app_db, req.id, new_status="approved", account=admin, note="ตรวจแล้ว")

    page = c.get("/my-requests").text
    assert "ตรวจแล้ว" in page
    assert f"<code>{req.generated_code}</code>" in page
    assert "ยกเลิกแล้ว ห้ามใช้" not in page


@pytest.mark.parametrize("status", ["approved", "exported"])
def test_code_not_yet_in_ax_says_it_cannot_be_ordered(client_as, app_db, status):
    c = client_as("requester", plant="APM")
    req = _submit(app_db, _me(app_db, "requester0@test.local"))
    change_status(app_db, req.id, new_status="approved",
                  account=account_for(app_db, "administrator"))
    if status == "exported":
        from app.services.exporter import export_pending
        export_pending(app_db, req.factory_id, account=account_for(app_db))
    assert "รอสร้างใน AX — ยังสั่งซื้อไม่ได้" in c.get("/my-requests").text


def test_created_code_has_no_waiting_notice(client_as, app_db):
    from app.services.exporter import export_pending

    c = client_as("requester", plant="APM")
    req = _submit(app_db, _me(app_db, "requester0@test.local"))
    change_status(app_db, req.id, new_status="approved",
                  account=account_for(app_db, "administrator"))
    export_pending(app_db, req.factory_id, account=account_for(app_db))
    change_status(app_db, req.id, new_status="created", account=account_for(app_db))
    page = c.get("/my-requests").text
    assert req.generated_code in page and "รอสร้างใน AX" not in page


def test_burned_code_is_struck_through_with_reason_once(client_as, app_db):
    c = client_as("requester", plant="APM")
    req = _submit(app_db, _me(app_db, "requester0@test.local"))
    admin = account_for(app_db, "administrator")
    change_status(app_db, req.id, new_status="approved", account=admin)
    change_status(app_db, req.id, new_status="rejected", account=admin,
                  note="ผิด Group ส่งใหม่")

    page = c.get("/my-requests").text
    assert f"<s><code>{req.generated_code}</code></s>" in page
    assert "ยกเลิกแล้ว ห้ามใช้" in page
    assert page.count("ผิด Group ส่งใหม่") == 1  # in the note column only
    assert "รอสร้างใน AX" not in page


def test_item_links_to_queue_only_for_procurement(client_as, app_db):
    requester = client_as("requester", plant="APM")
    procurement = client_as("procurement")
    r_req = _submit(app_db, _me(app_db, "requester0@test.local"))
    p_req = _submit(app_db, _me(app_db, "procurement1@test.local"))
    assert f'href="/queue/{r_req.id}"' not in requester.get("/my-requests").text
    assert f'href="/queue/{p_req.id}"' in procurement.get("/my-requests").text


# --- Landing after login -----------------------------------------------------------------

@pytest.fixture()
def requester_email(app_db) -> str:
    return account_for(app_db, "requester", plant="APM").email


def _login_next(c, email: str, next_path: str | None):
    data = {"email": email, "password": TEST_PASSWORD}
    if next_path is not None:
        data["next"] = next_path
    return c.post("/login", data=data, follow_redirects=False)


def test_requester_lands_on_my_requests_after_login(anon_client, requester_email):
    assert login(anon_client, requester_email).headers["location"] == "/my-requests"


def test_requester_with_a_page_to_return_to_goes_there(anon_client, requester_email):
    r = _login_next(anon_client, requester_email, "/account/password")
    assert r.headers["location"] == "/account/password"


@pytest.mark.parametrize("evil", ["https://evil.com", "//evil.com", "/\\evil.com"])
def test_off_site_next_is_ignored(anon_client, requester_email, evil):
    r = _login_next(anon_client, requester_email, evil)
    assert r.headers["location"] == "/my-requests"


def test_other_roles_still_land_on_the_form(anon_client, app_db):
    email = account_for(app_db, "procurement").email
    assert login(anon_client, email).headers["location"] == "/"


# --- After submitting ---------------------------------------------------------------------

def test_success_message_links_to_my_requests_not_the_queue_for_a_requester(client_as, app_db):
    c = client_as("requester", plant="APM")
    factory, system, group, sub = central_ids(app_db)
    r = c.post("/requests", data={"factory_id": factory.id, "code_system_id": system.id,
                                  "group_id": group.id, "subgroup_id": sub.id,
                                  "item_name": "Ball Bearing"})
    assert 'href="/my-requests"' in r.text
    assert "/queue/" not in r.text  # a Requester would get 403 there


# --- Review fixes: every way into the app leads a Requester to "My requests" ------------------

def test_logged_in_requester_opening_login_goes_to_my_requests(client_as):
    c = client_as("requester", plant="APM")
    assert c.get("/login", follow_redirects=False).headers["location"] == "/my-requests"


def test_procurement_opening_login_still_goes_to_the_form(client_as):
    c = client_as("procurement")
    assert c.get("/login", follow_redirects=False).headers["location"] == "/"


def test_requester_first_login_ends_with_a_link_to_my_requests(anon_client, app_db):
    factory_id = central_ids(app_db, "APM")[0].id
    auth.create_account(app_db, "new.req@test.local", "New", "requester", TEST_PASSWORD,
                        factory_id=factory_id)  # temporary password: must change
    assert login(anon_client, "new.req@test.local").headers["location"] == "/account/password"
    r = anon_client.post("/account/password", data={
        "current_password": TEST_PASSWORD, "new_password": "my-own-password-7",
        "confirm_password": "my-own-password-7"})
    assert 'href="/my-requests"' in r.text  # followed the redirect to ?done=1
