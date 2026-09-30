"""STORY-001 ticket 01: login, sessions, role checks, create_admin."""

import re
from pathlib import Path

import pytest
from fastapi import Depends, FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select

from app.config import Settings, settings
from app.create_admin import run as create_admin
from app.database import get_db
from app.main import app
from app.models import Account, Factory
from app.routes.deps import require_role
from app.services import auth
from app.services.auth import AuthError, authenticate, create_account, verify_password
from app.services.clock import utc_now
from app.services.sessions import COOKIE_NAME, issue_session
from tests.conftest import TEST_PASSWORD, login

PUBLIC_PATHS = {"/login", "/logout", "/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"}


def _admin(db, email: str = "admin@test.local") -> Account:
    return create_account(db, email, "Admin", "administrator", TEST_PASSWORD,
                          must_change_password=False)


def _plant_id(db, code: str = "APM") -> int:
    return db.scalar(select(Factory.id).where(Factory.code == code))


# --- Migration -----------------------------------------------------------------

def test_migrations_build_accounts_table_on_fresh_db(tmp_path, monkeypatch):
    # Tests otherwise use create_all, which cannot catch a broken migration (trap 8).
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, inspect

    url = f"sqlite:///{(tmp_path / 'fresh.db').as_posix()}"
    monkeypatch.setattr(settings, "database_url", url)
    root = Path(__file__).resolve().parent.parent
    command.upgrade(Config(str(root / "alembic.ini")), "head")

    engine = create_engine(url)
    try:
        columns = {c["name"] for c in inspect(engine).get_columns("accounts")}
    finally:
        engine.dispose()  # else an unclosed sqlite3 connection lingers until GC
    assert columns >= {
        "email", "display_name", "role", "factory_id", "password_hash",
        "must_change_password", "active", "session_version",
        "failed_login_count", "locked_until",
    }


# --- Anonymous access (AC1) ----------------------------------------------------

def test_every_page_except_login_redirects_anonymous_to_login(anon_client):
    checked = 0
    for route in app.routes:
        if not isinstance(route, APIRoute) or route.path in PUBLIC_PATHS:
            continue
        path = re.sub(r"\{[^}]+\}", "1", route.path)
        for method in route.methods:
            r = anon_client.request(method, path, follow_redirects=False)
            assert r.status_code == 303, f"{method} {route.path} -> {r.status_code}"
            assert r.headers["location"].startswith("/login"), route.path
            checked += 1
    assert checked > 20  # guards against the loop silently checking nothing


def test_redirect_remembers_the_page_and_login_returns_there(anon_client, app_db):
    _admin(app_db)
    r = anon_client.get("/queue", follow_redirects=False)
    assert r.headers["location"] == "/login?next=/queue"

    r = anon_client.post("/login", data={"email": "admin@test.local",
                                         "password": TEST_PASSWORD, "next": "/queue"},
                         follow_redirects=False)
    assert r.headers["location"] == "/queue"


@pytest.mark.parametrize("evil", ["//evil.example", "https://evil.example", "/\\evil.example"])
def test_login_never_redirects_off_site(anon_client, app_db, evil):
    _admin(app_db)
    r = anon_client.post("/login", data={"email": "admin@test.local",
                                         "password": TEST_PASSWORD, "next": evil},
                         follow_redirects=False)
    assert r.headers["location"] == "/"


def test_htmx_request_gets_hx_redirect_instead_of_swapping_login_page(anon_client):
    r = anon_client.get("/fragments/systems", headers={"HX-Request": "true"},
                        follow_redirects=False)
    assert r.status_code == 401
    assert r.headers["HX-Redirect"].startswith("/login")


def test_login_page_is_public_and_thai(anon_client):
    r = anon_client.get("/login")
    assert r.status_code == 200
    assert "เข้าสู่ระบบ" in r.text


# --- Passwords (AC5) -----------------------------------------------------------

def test_stored_password_is_a_hash_that_verifies(db_session):
    account = _admin(db_session)
    assert TEST_PASSWORD not in account.password_hash
    assert account.password_hash.startswith("$argon2id$")
    assert verify_password(account.password_hash, TEST_PASSWORD)
    assert not verify_password(account.password_hash, "wrong-password-123")


def test_hash_is_upgraded_when_cost_is_raised(db_session, monkeypatch):
    account = _admin(db_session)
    old_hash = account.password_hash
    monkeypatch.setattr(settings, "argon2_time_cost", settings.argon2_time_cost + 1)
    authenticate(db_session, "admin@test.local", TEST_PASSWORD)
    assert account.password_hash != old_hash
    assert verify_password(account.password_hash, TEST_PASSWORD)


# --- Login failures (AC6) ------------------------------------------------------

def test_wrong_password_and_unknown_email_look_identical(anon_client, app_db):
    _admin(app_db)
    wrong = login(anon_client, "admin@test.local", "wrong-password-123")
    unknown = login(anon_client, "nobody@test.local")
    for r in (wrong, unknown):
        assert r.status_code == 401
        assert auth.LOGIN_FAILED in r.text
        assert COOKIE_NAME not in r.cookies


def test_unknown_email_still_verifies_a_hash(db_session, monkeypatch):
    # Same work either way, so response time does not reveal which emails exist.
    calls = []
    real_verify = auth.verify_password
    monkeypatch.setattr(auth, "verify_password",
                        lambda h, p: calls.append(h) or real_verify(h, p))
    with pytest.raises(AuthError):
        authenticate(db_session, "nobody@test.local", TEST_PASSWORD)
    assert len(calls) == 1 and calls[0].startswith("$argon2id$")


def test_email_is_case_and_space_insensitive(anon_client, app_db):
    _admin(app_db)
    assert login(anon_client, "  Admin@Test.Local ").status_code == 303


def test_deactivated_account_cannot_log_in(anon_client, app_db):
    account = _admin(app_db)
    account.active = False
    app_db.commit()
    r = login(anon_client, "admin@test.local")
    assert r.status_code == 401 and auth.LOGIN_FAILED in r.text


# --- Sessions ------------------------------------------------------------------

def test_session_cookie_is_httponly_and_samesite_lax(anon_client, app_db):
    _admin(app_db)
    cookie = login(anon_client, "admin@test.local").headers["set-cookie"]
    assert "HttpOnly" in cookie
    assert "samesite=lax" in cookie.lower()
    assert "Secure" not in cookie  # dev runs on plain http


def test_session_cookie_is_secure_outside_dev(anon_client, app_db, monkeypatch):
    _admin(app_db)
    monkeypatch.setattr(settings, "app_env", "production")
    assert "Secure" in login(anon_client, "admin@test.local").headers["set-cookie"]


def test_logged_in_account_reaches_pages(client):
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 200
    assert "ออกจากระบบ" in r.text


def test_deactivated_account_is_logged_out(client, app_db):
    account = app_db.scalar(select(Account))
    account.active = False
    app_db.commit()
    assert client.get("/", follow_redirects=False).status_code == 303


def test_session_version_mismatch_is_logged_out(client, app_db):
    account = app_db.scalar(select(Account))
    account.session_version += 1
    app_db.commit()
    assert client.get("/", follow_redirects=False).status_code == 303


def test_tampered_cookie_is_logged_out(anon_client, app_db):
    account = _admin(app_db)
    cookie = issue_session(account, utc_now())
    anon_client.cookies.set(COOKIE_NAME, cookie[:-2] + "xx")
    assert anon_client.get("/", follow_redirects=False).status_code == 303


def test_logout_is_post_only_and_ends_the_session(client):
    assert client.get("/logout", follow_redirects=False).status_code == 405
    r = client.post("/logout", follow_redirects=False)
    assert r.headers["location"] == "/login"
    assert client.get("/", follow_redirects=False).status_code == 303


def test_login_page_sends_logged_in_account_home(client):
    r = client.get("/login", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/"


# --- require_role --------------------------------------------------------------

@pytest.fixture()
def role_app(db_session):
    """A tiny app with one page per minimum Role, sharing the test DB."""
    mini = FastAPI()

    @mini.get("/procurement")
    def procurement_page(account: Account = Depends(require_role("procurement"))):
        return {"role": account.role}

    @mini.get("/administrator")
    def administrator_page(account: Account = Depends(require_role("administrator"))):
        return {"role": account.role}

    def _override_db():
        yield db_session

    mini.dependency_overrides[get_db] = _override_db

    def _client_for(role: str) -> TestClient:
        plant = _plant_id(db_session) if role == "requester" else None
        account = create_account(db_session, f"{role}@test.local", role, role,
                                 TEST_PASSWORD, factory_id=plant, must_change_password=False)
        c = TestClient(mini)
        c.cookies.set(COOKIE_NAME, issue_session(account, utc_now()))
        return c

    return _client_for


def test_require_role_refuses_lower_role_with_403(role_app):
    requester = role_app("requester")
    assert requester.get("/procurement").status_code == 403
    procurement = role_app("procurement")
    assert procurement.get("/procurement").status_code == 200
    assert procurement.get("/administrator").status_code == 403


def test_administrator_passes_procurement_check(role_app):
    admin = role_app("administrator")
    assert admin.get("/procurement").json() == {"role": "administrator"}
    assert admin.get("/administrator").status_code == 200


def test_require_role_rejects_unknown_role():
    with pytest.raises(ValueError):
        require_role("superuser")


# --- create_account rules ------------------------------------------------------

def test_requester_needs_a_plant_and_others_must_not_have_one(db_session):
    with pytest.raises(AuthError):
        create_account(db_session, "r@test.local", "R", "requester", TEST_PASSWORD)
    with pytest.raises(AuthError):
        create_account(db_session, "p@test.local", "P", "procurement", TEST_PASSWORD,
                       factory_id=_plant_id(db_session))
    account = create_account(db_session, "r@test.local", "R", "requester", TEST_PASSWORD,
                             factory_id=_plant_id(db_session))
    assert account.factory.code == "APM"
    assert account.must_change_password  # temporary password by default


def test_duplicate_email_is_refused_case_insensitively(db_session):
    _admin(db_session)
    with pytest.raises(AuthError, match="มีบัญชีอยู่แล้ว"):
        _admin(db_session, "ADMIN@test.local")


def test_password_shorter_than_12_is_refused(db_session):
    with pytest.raises(AuthError, match="12"):
        create_account(db_session, "a@test.local", "A", "administrator", "short-pass1")


def test_unknown_role_is_refused(db_session):
    with pytest.raises(AuthError):
        create_account(db_session, "a@test.local", "A", "superuser", TEST_PASSWORD)


# --- Settings ------------------------------------------------------------------

@pytest.mark.parametrize("secret", ["change-me", "dev-only-change-me", ""])
def test_placeholder_secret_is_refused_outside_dev(secret):
    with pytest.raises(ValidationError):
        Settings(app_env="production", secret_key=secret)


def test_real_secret_is_accepted_outside_dev():
    assert Settings(app_env="production", secret_key="x" * 40).cookie_secure


# --- create_admin CLI ----------------------------------------------------------

def _prompts(*answers: str):
    it = iter(answers)
    return lambda _prompt: next(it)


def test_create_admin_creates_an_administrator_who_can_log_in(anon_client, app_db):
    out: list[str] = []
    code = create_admin(app_db, ask=_prompts("boss@test.local", "Boss"),
                        ask_secret=_prompts(TEST_PASSWORD, TEST_PASSWORD), out=out.append)
    assert code == 0
    account = app_db.scalar(select(Account).where(Account.email == "boss@test.local"))
    assert account.role == "administrator" and not account.must_change_password
    assert login(anon_client, "boss@test.local").status_code == 303


def test_create_admin_refuses_mismatched_confirmation(db_session):
    out: list[str] = []
    code = create_admin(db_session, ask=_prompts("boss@test.local", "Boss"),
                        ask_secret=_prompts(TEST_PASSWORD, TEST_PASSWORD + "x"),
                        out=out.append)
    assert code == 1 and "do not match" in out[0]
    assert db_session.scalar(select(Account)) is None


def test_create_admin_refuses_short_password(db_session):
    out: list[str] = []
    code = create_admin(db_session, ask=_prompts("boss@test.local", "Boss"),
                        ask_secret=_prompts("short", "short"), out=out.append)
    assert code == 1 and db_session.scalar(select(Account)) is None
