"""STORY-001 pre-merge hardening (whole-branch review)."""

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.config import Settings
from app.models import Account, RequestEvent
from app.services import auth
from app.services.auth import AuthError
from app.services.requests import change_category, change_status, override_code, submit_request
from tests.conftest import TEST_PASSWORD, account_for, central_ids


# --- 1. APP_ENV fails closed ------------------------------------------------------------------

def test_unset_app_env_means_production(monkeypatch):
    monkeypatch.delenv("APP_ENV", raising=False)
    s = Settings(_env_file=None, secret_key="x" * 40)
    assert s.app_env == "production" and s.cookie_secure


def test_unset_app_env_refuses_the_placeholder_secret(monkeypatch):
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("SECRET_KEY", raising=False)
    with pytest.raises(ValidationError, match="SECRET_KEY"):
        Settings(_env_file=None)


def test_docs_are_hidden_when_app_env_is_unset():
    # main.py decides at import time, so import it fresh in a clean process.
    import os
    import subprocess
    import sys

    env = {k: v for k, v in os.environ.items() if k != "APP_ENV"}
    env["SECRET_KEY"] = "x" * 40
    out = subprocess.run(
        [sys.executable, "-c",
         "import app.main as m; print(m.app.docs_url, m.app.redoc_url, m.app.openapi_url)"],
        capture_output=True, text=True, env=env, check=True,
    ).stdout.split()
    assert out == ["None", "None", "None"]


# --- 2. Where to return after logging in again --------------------------------------------------

def test_expired_htmx_click_returns_to_the_page_not_the_endpoint(anon_client):
    r = anon_client.post("/queue/5/status", data={"new_status": "approved"},
                         headers={"HX-Request": "true",
                                  "HX-Current-URL": "http://testserver/queue/5?tab=history"},
                         follow_redirects=False)
    assert r.status_code == 401
    assert r.headers["HX-Redirect"] == "/login?next=/queue/5%3Ftab%3Dhistory"


@pytest.mark.parametrize("current", [
    "https://evil.com/queue", "//evil.com/queue", "http://evil.com/", "https://testserver.evil.com/x",
])
def test_hx_current_url_on_another_site_is_ignored(anon_client, current):
    r = anon_client.get("/fragments/systems?factory_id=1",
                        headers={"HX-Request": "true", "HX-Current-URL": current},
                        follow_redirects=False)
    assert r.headers["HX-Redirect"] == "/login"


def test_backslash_trick_in_hx_current_url_is_ignored(anon_client):
    r = anon_client.get("/fragments/systems?factory_id=1",
                        headers={"HX-Request": "true",
                                 "HX-Current-URL": "http://testserver/\\evil.com"},
                        follow_redirects=False)
    assert r.headers["HX-Redirect"] == "/login"


def test_plain_post_has_no_page_to_return_to(anon_client):
    r = anon_client.post("/queue/5/status", data={"new_status": "approved"},
                         follow_redirects=False)
    assert r.headers["location"] == "/login"


def test_get_keeps_its_query_string(anon_client):
    r = anon_client.get("/queue?status=submitted", follow_redirects=False)
    assert r.headers["location"] == "/login?next=/queue%3Fstatus%3Dsubmitted"


def test_login_returns_to_the_page_with_its_query(anon_client, app_db):
    email = account_for(app_db, "procurement").email
    r = anon_client.post("/login", data={"email": email, "password": TEST_PASSWORD,
                                         "next": "/queue?status=submitted"},
                         follow_redirects=False)
    assert r.headers["location"] == "/queue?status=submitted"


# --- 4. Length limits ---------------------------------------------------------------------------

def test_display_name_over_100_is_refused_in_thai(db_session):
    with pytest.raises(AuthError, match="ชื่อยาวเกิน 100"):
        auth.create_account(db_session, "n@test.local", "ก" * 101, "procurement", TEST_PASSWORD)
    assert auth.create_account(db_session, "n@test.local", "ก" * 100, "procurement",
                               TEST_PASSWORD).display_name == "ก" * 100


def test_email_over_254_is_refused_in_thai(db_session):
    long_email = "a" * 245 + "@test.local"  # 256 characters
    with pytest.raises(AuthError, match="อีเมลยาวเกิน 254"):
        auth.create_account(db_session, long_email, "N", "procurement", TEST_PASSWORD)
    assert db_session.scalar(select(Account)) is None


def test_long_name_on_account_page_is_a_422_not_a_500(client):
    r = client.post("/admin/accounts", data={"email": "n@test.local", "display_name": "x" * 101,
                                             "role": "procurement"})
    assert r.status_code == 422 and "ชื่อยาวเกิน" in r.text


# --- AC4: every event action records the acting Account ------------------------------------------

def test_every_remaining_event_action_records_the_acting_email(db_session):
    procurement = account_for(db_session, "procurement")
    admin = account_for(db_session, "administrator")
    factory, system, group, sub = central_ids(db_session)
    other_sub = central_ids(db_session, "APM", "900", "02")[3]
    third_sub = central_ids(db_session, "APM", "900", "03")[3]

    def new_request():
        return submit_request(db_session, procurement, factory_id=factory.id,
                              code_system_id=system.id, group_id=group.id,
                              subgroup_id=sub.id, item_name="Ball Bearing")

    a = new_request()
    change_category(db_session, a.id, subgroup_id=other_sub.id, account=procurement)
    change_status(db_session, a.id, new_status="needs_info", account=procurement, note="?")
    change_status(db_session, a.id, new_status="rejected", account=procurement)

    b = new_request()
    change_status(db_session, b.id, new_status="approved", account=admin)
    change_category(db_session, b.id, subgroup_id=third_sub.id, account=admin)  # reissue
    override_code(db_session, b.id, new_code="90003009999", account=admin)
    change_status(db_session, b.id, new_status="rejected", account=admin, note="ผิด")

    actors = {}
    for e in db_session.scalars(select(RequestEvent)):
        actors.setdefault((e.request_id, e.action), e.actor)
    expected = {
        (a.id, "category_changed"): procurement.email,
        (a.id, "needs_info"): procurement.email,
        (a.id, "rejected"): procurement.email,
        (b.id, "category_changed"): admin.email,
        (b.id, "code_reissued"): admin.email,
        (b.id, "code_overridden"): admin.email,
        (b.id, "code_burned"): admin.email,
        (b.id, "rejected"): admin.email,
    }
    for key, email in expected.items():
        assert actors.get(key) == email, key
    # No event anywhere carries a placeholder actor.
    assert not [e for e in db_session.scalars(select(RequestEvent))
                if "@" not in e.actor]
