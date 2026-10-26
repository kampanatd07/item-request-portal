"""STORY-001 ticket 04: Account administration by Administrators."""

import logging
from datetime import datetime

import pytest
from fastapi.routing import APIRoute
from sqlalchemy import select, update

from app.main import app
from app.models import Account, Factory, ItemRequest
from app.services import auth
from app.services.auth import AuthError, authenticate
from app.services.requests import submit_request
from tests.conftest import TEST_IP, TEST_PASSWORD, account_for, central_ids, login


def _plant(db, code: str = "APM") -> int:
    return db.scalar(select(Factory.id).where(Factory.code == code))


def _by_email(db, email: str) -> Account:
    return db.scalar(select(Account).where(Account.email == email))


def _temp_password(html: str) -> str:
    marker = 'user-select:all;">'
    return html.split(marker, 1)[1].split("<", 1)[0]


@pytest.fixture()
def admin(app_db) -> Account:
    return account_for(app_db, "administrator")


# --- Access -------------------------------------------------------------------------

@pytest.mark.parametrize("role,plant", [("procurement", None), ("requester", "APM")])
@pytest.mark.parametrize("method,path", [
    ("GET", "/admin/accounts"),
    ("POST", "/admin/accounts"),
    ("POST", "/admin/accounts/1/access"),
    ("POST", "/admin/accounts/1/deactivate"),
    ("POST", "/admin/accounts/1/reactivate"),
    ("POST", "/admin/accounts/1/reset-password"),
])
def test_only_administrators_reach_account_pages(client_as, role, plant, method, path):
    r = client_as(role, plant=plant).request(method, path, follow_redirects=False)
    assert r.status_code == 403


def test_administrator_sees_account_page_and_nav_link(client):
    r = client.get("/admin/accounts")
    assert r.status_code == 200
    assert 'href="/admin/accounts"' in r.text


def test_no_route_deletes_an_account_or_edits_its_email():
    routes = [r for r in app.routes if isinstance(r, APIRoute)
              and r.path.startswith("/admin/accounts")]
    assert routes
    assert all("DELETE" not in r.methods for r in routes)
    assert not any("email" in r.path or "delete" in r.path for r in routes)


def test_posted_email_is_ignored_when_changing_access(client, app_db):
    target = account_for(app_db, "procurement")
    client.post(f"/admin/accounts/{target.id}/access",
                data={"role": "procurement", "email": "new@evil.example"})
    app_db.refresh(target)
    assert target.email == "procurement-any@test.local"


# --- Create -------------------------------------------------------------------------

@pytest.mark.parametrize("role,plant", [
    ("requester", "ACM"), ("procurement", None), ("administrator", None),
])
def test_administrator_creates_account_for_each_role(client, app_db, role, plant):
    data = {"email": f"New.{role}@Test.Local", "display_name": "คนใหม่", "role": role,
            "factory_id": _plant(app_db, plant) if plant else ""}
    r = client.post("/admin/accounts", data=data)
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"

    account = _by_email(app_db, f"new.{role}@test.local")
    assert account.role == role and account.must_change_password
    assert (account.factory.code if account.factory else None) == plant
    temporary = _temp_password(r.text)
    assert len(temporary) >= auth.MIN_PASSWORD_LENGTH
    assert authenticate(app_db, account.email, temporary, client_ip=TEST_IP).id == account.id


def test_requester_without_plant_is_refused(client, app_db):
    r = client.post("/admin/accounts", data={"email": "r@test.local", "display_name": "R",
                                             "role": "requester", "factory_id": ""})
    assert r.status_code == 422 and "โรงงาน" in r.text
    assert _by_email(app_db, "r@test.local") is None


def test_plant_is_dropped_for_non_requester(client, app_db):
    client.post("/admin/accounts", data={"email": "p@test.local", "display_name": "P",
                                         "role": "procurement", "factory_id": _plant(app_db)})
    assert _by_email(app_db, "p@test.local").factory_id is None


def test_duplicate_email_is_refused(client, app_db):
    account_for(app_db, "procurement")
    r = client.post("/admin/accounts", data={"email": "PROCUREMENT-any@test.local",
                                             "display_name": "X", "role": "procurement"})
    assert r.status_code == 422 and "มีบัญชีอยู่แล้ว" in r.text


# --- Deactivate / reactivate (AC10, deactivation part) --------------------------------

def test_deactivated_account_cannot_log_in_and_its_session_dies(client, client_as, app_db):
    procurement = client_as("procurement")
    assert procurement.get("/queue", follow_redirects=False).status_code == 200
    target = _by_email(app_db, "procurement1@test.local")

    assert client.post(f"/admin/accounts/{target.id}/deactivate").status_code == 200
    assert procurement.get("/queue", follow_redirects=False).status_code == 303
    with pytest.raises(AuthError):
        authenticate(app_db, target.email, TEST_PASSWORD, client_ip=TEST_IP)


def test_reactivate_clears_lockout_and_allows_login(app_db, admin):
    target = account_for(app_db, "procurement")
    auth.deactivate_account(app_db, admin, target.id)
    target.failed_login_count, target.locked_until = 7, datetime(2030, 1, 1)
    app_db.commit()

    auth.reactivate_account(app_db, admin, target.id)
    assert target.active and target.failed_login_count == 0 and target.locked_until is None
    assert authenticate(app_db, target.email, TEST_PASSWORD, client_ip=TEST_IP).id == target.id


def test_administrator_cannot_deactivate_self(app_db, admin):
    with pytest.raises(AuthError, match="ตัวเอง"):
        auth.deactivate_account(app_db, admin, admin.id)
    assert admin.active


def test_last_active_administrator_cannot_be_deactivated(app_db):
    # Only a non-Administrator could ever aim at the last one (an active
    # Administrator actor is in the locked set too); since ticket 04 that actor
    # is refused first, for not being an active Administrator.
    only_admin = account_for(app_db, "administrator")
    someone = account_for(app_db, "procurement")
    with pytest.raises(AuthError, match=auth.PERMISSION_CHANGED):
        auth.deactivate_account(app_db, someone, only_admin.id)
    assert only_admin.active


@pytest.mark.parametrize("lost", ["deactivated", "demoted"])
def test_an_administrator_who_lost_the_role_meanwhile_is_refused(app_db, lost):
    """STORY-006 ticket 04: the route's guard saw an active Administrator, but
    by the time the change runs the actor is not one any more."""
    acting = auth.create_account(app_db, "acting@test.local", "Acting", "administrator",
                                 TEST_PASSWORD)
    target = auth.create_account(app_db, "target@test.local", "Target", "administrator",
                                 TEST_PASSWORD)
    third = auth.create_account(app_db, "third@test.local", "Third", "administrator",
                                TEST_PASSWORD)
    # Another Administrator's change commits first (written straight to the
    # row, so the actor object in hand still looks like an active Administrator).
    values = {"active": False} if lost == "deactivated" else {"role": "procurement"}
    app_db.execute(update(Account).where(Account.id == acting.id)
                   .values(**values).execution_options(synchronize_session=False))
    app_db.commit()
    with pytest.raises(AuthError, match=auth.PERMISSION_CHANGED):
        auth.deactivate_account(app_db, acting, target.id)
    with pytest.raises(AuthError, match=auth.PERMISSION_CHANGED):
        auth.change_access(app_db, acting, target.id, role="procurement", factory_id=None)
    app_db.expire_all()
    assert target.active and target.role == "administrator" and third.active


def test_another_administrator_can_be_deactivated(app_db, admin):
    second = auth.create_account(app_db, "second@test.local", "Second", "administrator",
                                 TEST_PASSWORD)
    auth.deactivate_account(app_db, admin, second.id)
    assert not second.active


# --- Reset password -------------------------------------------------------------------

def test_reset_password_old_fails_temporary_works_sessions_die(client, client_as, app_db):
    requester = client_as("requester", plant="APM")
    target = _by_email(app_db, "requester1@test.local")

    r = client.post(f"/admin/accounts/{target.id}/reset-password")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    temporary = _temp_password(r.text)

    assert requester.get("/", follow_redirects=False).status_code == 303
    with pytest.raises(AuthError):
        authenticate(app_db, target.email, TEST_PASSWORD, client_ip=TEST_IP)
    assert authenticate(app_db, target.email, temporary, client_ip=TEST_IP).id == target.id
    app_db.refresh(target)
    assert target.must_change_password


def test_temporary_passwords_differ(app_db, admin):
    target = account_for(app_db, "procurement")
    assert auth.reset_password(app_db, admin, target.id) != \
        auth.reset_password(app_db, admin, target.id)


# --- Role and Plant ---------------------------------------------------------------------

def test_changing_requesters_plant_keeps_old_requests_plant(client, app_db):
    requester = account_for(app_db, "requester", plant="APM")
    factory, system, group, sub = central_ids(app_db)
    old = submit_request(app_db, requester, factory_id=factory.id, code_system_id=system.id,
                         group_id=group.id, subgroup_id=sub.id, item_name="Ball Bearing")

    client.post(f"/admin/accounts/{requester.id}/access",
                data={"role": "requester", "factory_id": _plant(app_db, "CBD")})
    app_db.refresh(requester)
    app_db.refresh(old)
    assert requester.factory.code == "CBD"
    assert old.factory.code == "APM"
    assert app_db.get(ItemRequest, old.id).factory.code == "APM"


def test_changing_to_requester_needs_a_plant(app_db, admin):
    target = account_for(app_db, "procurement")
    with pytest.raises(AuthError, match="โรงงาน"):
        auth.change_access(app_db, admin, target.id, role="requester", factory_id=None)
    assert target.role == "procurement"


def test_changing_away_from_requester_clears_plant_and_ends_sessions(app_db, admin):
    target = account_for(app_db, "requester", plant="APM")
    version = target.session_version
    auth.change_access(app_db, admin, target.id, role="procurement",
                       factory_id=_plant(app_db, "APM"))
    assert target.role == "procurement" and target.factory_id is None
    assert target.session_version == version + 1


def test_plant_only_change_keeps_sessions(app_db, admin):
    target = account_for(app_db, "requester", plant="APM")
    version = target.session_version
    auth.change_access(app_db, admin, target.id, role="requester",
                       factory_id=_plant(app_db, "CBD"))
    assert target.session_version == version


def test_last_active_administrator_cannot_be_demoted(client, app_db):
    only_admin = _by_email(app_db, "administrator0@test.local")
    r = client.post(f"/admin/accounts/{only_admin.id}/access", data={"role": "procurement"})
    assert r.status_code == 422 and "คนสุดท้าย" in r.text
    app_db.refresh(only_admin)
    assert only_admin.role == "administrator"


# --- Application log (until STORY-011) ---------------------------------------------------

def test_account_admin_is_logged_without_passwords(client, app_db, caplog):
    caplog.set_level(logging.INFO, logger="app.accounts")
    r = client.post("/admin/accounts", data={"email": "log@test.local", "display_name": "L",
                                             "role": "procurement"})
    created_password = _temp_password(r.text)
    target = _by_email(app_db, "log@test.local")
    r = client.post(f"/admin/accounts/{target.id}/reset-password")
    reset_password = _temp_password(r.text)
    client.post(f"/admin/accounts/{target.id}/deactivate")

    records = [rec.getMessage() for rec in caplog.records if rec.name == "app.accounts"]
    assert any("action=create" in m and "by=administrator0@test.local" in m
               and "target=log@test.local" in m for m in records)
    assert any("action=reset_password" in m for m in records)
    assert any("action=deactivate" in m for m in records)
    everything = caplog.text
    for secret in (created_password, reset_password, TEST_PASSWORD, target.password_hash):
        assert secret not in everything


def test_old_session_stays_dead_after_reactivation(client, client_as, app_db):
    # Deactivation bumps the session version, so reactivating does not revive
    # a cookie issued before (e.g. on a lost laptop).
    procurement = client_as("procurement")
    target = _by_email(app_db, "procurement1@test.local")
    client.post(f"/admin/accounts/{target.id}/deactivate")
    client.post(f"/admin/accounts/{target.id}/reactivate")
    assert procurement.get("/queue", follow_redirects=False).status_code == 303
    assert login(procurement, target.email).status_code == 303  # fresh login works
    assert procurement.get("/queue", follow_redirects=False).status_code == 200



# --- Review fixes: log injection and the last-Administrator race ---------------------

@pytest.mark.parametrize("email", [
    "x@y.com\nINFO app.accounts account_admin by=peter@test.local action=deactivate",
    "x@y.com\r\nforged", "a b@test.local", "no-at-sign.test.local", "x@nodot", "x@y.com\x00",
])
def test_malformed_email_is_refused(app_db, admin, email):
    with pytest.raises(AuthError, match="อีเมล"):
        auth.admin_create_account(app_db, admin, email=email, display_name="X",
                                  role="procurement")
    assert app_db.scalar(select(Account).where(Account.email.like("x@%"))) is None


def test_newline_in_a_name_cannot_forge_a_log_line(client, app_db, caplog):
    caplog.set_level(logging.INFO, logger="app.accounts")
    forged = "ok\nINFO app.accounts account_admin by=peter@test.local action=deactivate target=boss"
    r = client.post("/admin/accounts", data={"email": "n@test.local", "display_name": forged,
                                             "role": "procurement"})
    assert r.status_code == 200

    lines = [line for rec in caplog.records if rec.name == "app.accounts"
             for line in rec.getMessage().splitlines()]
    assert len(lines) == 1  # one record, one line: the name did not break it
    assert lines[0].startswith("account_admin by=administrator0@test.local action=create")
    assert "name=ok\\nINFO" in lines[0]


def test_last_administrator_check_locks_admin_rows_in_id_order(app_db, admin):
    # SQLite drops FOR UPDATE, so the race itself runs on Postgres (STORY-006
    # AC4); here we prove the lock is requested, in a fixed order.
    from sqlalchemy import event
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.orm import Session

    seen: list[str] = []

    def _capture(state):
        if state.is_select:
            sql = str(state.statement.compile(dialect=postgresql.dialect()))
            if "FROM accounts" in sql and "FOR UPDATE" in sql:
                seen.append(sql)

    second = auth.create_account(app_db, "second@test.local", "Second", "administrator",
                                 TEST_PASSWORD)
    event.listen(Session, "do_orm_execute", _capture)
    try:
        auth.deactivate_account(app_db, admin, second.id)
    finally:
        event.remove(Session, "do_orm_execute", _capture)
    assert seen and "ORDER BY accounts.id" in seen[0]
