"""STORY-006 part B prep: `python -m app.reset_password <email> --by NAME`, for an
Administrator who cannot log in and has no other Administrator to reset them.
Same reset as the Account admin page; the temporary password is printed once
and never logged; the log says who reset whom."""

import os
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.database import Base
from app.models import Account
from app.services import auth
from app.services.clock import utc_now
from tests.conftest import TEST_PASSWORD

REPO = Path(__file__).resolve().parent.parent
EMAIL = "locked.admin@test.local"
SHOWN = "Temporary password (shown once, write it down now): "


def _locked_admin(db: Session) -> Account:
    """An Administrator locked out after 10 failures, with a session version
    above the start, so the test sees each field change."""
    account = auth.create_account(db, EMAIL, "Locked Admin", "administrator", TEST_PASSWORD,
                                  must_change_password=False)
    account.failed_login_count = auth.MAX_FAILED_LOGINS
    account.locked_until = utc_now() + timedelta(minutes=15)
    account.session_version = 3
    db.commit()
    return account


def test_the_real_command_resets_shows_the_password_once_and_logs_who(tmp_path: Path) -> None:
    # Run it as a person would: its own process, its own database file, and
    # only the environment it needs.
    url = f"sqlite:///{(tmp_path / 'cli.db').as_posix()}"
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        _locked_admin(db)
    env = {k: v for k, v in os.environ.items()
           if k in ("PATH", "SYSTEMROOT", "TEMP", "TMP", "HOME", "USERPROFILE")}
    env.update(APP_ENV="dev", DATABASE_URL=url, PYTHONIOENCODING="utf-8")

    done = subprocess.run(
        [sys.executable, "-m", "app.reset_password", EMAIL.upper(), "--by", "Peter"],
        capture_output=True, text=True, env=env, cwd=REPO, timeout=60)

    assert done.returncode == 0, done.stdout + done.stderr
    shown = [line for line in done.stdout.splitlines() if line.startswith(SHOWN)]
    assert len(shown) == 1
    temporary = shown[0].removeprefix(SHOWN)
    assert len(temporary) >= 12
    assert f"account_admin by=cli:Peter action=reset_password target={EMAIL}" in done.stderr
    assert temporary not in done.stderr

    with Session(engine) as db:
        account = db.scalar(select(Account).where(Account.email == EMAIL))
        assert auth.verify_password(account.password_hash, temporary)
        assert account.must_change_password
        assert account.session_version == 4
        assert account.failed_login_count == 0 and account.locked_until is None
    engine.dispose()


# --- in-process: the refusals -----------------------------------------------------------

def _cli(db: Session, *argv: str) -> tuple[int, str]:
    from app.reset_password import run

    lines: list[str] = []
    code = run(db, list(argv), out=lines.append)
    return code, "\n".join(lines)


def _unchanged(db: Session, before: str) -> bool:
    db.expire_all()
    return db.scalar(select(Account.password_hash).where(Account.email == EMAIL)) == before


@pytest.fixture()
def admin(app_db: Session) -> Account:
    return _locked_admin(app_db)


def test_without_by_is_an_error_and_changes_nothing(app_db: Session, admin: Account) -> None:
    before = admin.password_hash
    for argv in ([EMAIL], [EMAIL, "--by", "   "]):
        code, out = _cli(app_db, *argv)
        assert code == 1 and "--by" in out
        assert SHOWN not in out
    assert _unchanged(app_db, before)


def test_an_unknown_email_is_an_error(app_db: Session, admin: Account) -> None:
    code, out = _cli(app_db, "nobody@test.local", "--by", "Peter")
    assert code == 1 and "nobody@test.local" in out and SHOWN not in out


def test_a_deactivated_account_is_refused_and_unchanged(app_db: Session, admin: Account) -> None:
    admin.active = False
    app_db.commit()
    before = admin.password_hash
    code, out = _cli(app_db, EMAIL, "--by", "Peter")
    assert code == 1 and "reactivate" in out and SHOWN not in out
    assert _unchanged(app_db, before)


def _state(db: Session, account_id: int) -> tuple:
    db.expire_all()
    a = db.get(Account, account_id)
    return (a.password_hash, a.session_version, a.must_change_password,
            a.failed_login_count, a.locked_until)


def test_an_account_that_is_not_an_administrator_is_refused_and_unchanged(
        app_db: Session) -> None:
    account = auth.create_account(app_db, "buyer@test.local", "Buyer", "procurement",
                                  TEST_PASSWORD, must_change_password=False)
    account.failed_login_count = auth.MAX_FAILED_LOGINS
    account.locked_until = utc_now() + timedelta(minutes=15)
    account.session_version = 3
    app_db.commit()
    before = _state(app_db, account.id)
    code, out = _cli(app_db, "buyer@test.local", "--by", "Peter")
    assert code == 1 and "Account admin page" in out and SHOWN not in out
    assert _state(app_db, account.id) == before


@pytest.mark.parametrize("by", ["x action=deactivate target=boss@test.local",
                                "x action＝deactivate"])  # fullwidth ＝ too
def test_by_with_an_equals_sign_is_refused_and_unchanged(
        app_db: Session, admin: Account, by: str) -> None:
    # The audit line is key=value; a name must not add a fake field to it.
    before = admin.password_hash
    code, out = _cli(app_db, EMAIL, "--by", by)
    assert code == 1 and "must not contain" in out and SHOWN not in out
    assert _unchanged(app_db, before)


def test_each_reset_gives_a_new_password(app_db: Session, admin: Account) -> None:
    first = _cli(app_db, EMAIL, "--by", "Peter")
    second = _cli(app_db, EMAIL, "--by", "Peter")
    assert first[0] == second[0] == 0
    assert first[1] != second[1]
