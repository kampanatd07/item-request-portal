"""Signed session cookie: which Account, which session version, when it logged in.

The cookie only proves what we issued; whether it still counts is decided
against the DB and the clock on every request, so deactivation or a password
change (bumping session_version) logs the Account out everywhere at once, and
every session ends a fixed time after login.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from itsdangerous import BadSignature, URLSafeSerializer
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Account

COOKIE_NAME = "session"
_SALT = "session-cookie"


@dataclass
class SessionCheck:
    """Outcome of reading a cookie.

    `stale` means a cookie was sent but no longer counts (expired, version
    bumped, Account deactivated, tampered), so the login page can ask the
    person to log in again. The browser drops the cookie itself at expiry
    (Max-Age), so "expired" alone cannot be told apart from "never logged in".
    """

    account: Account | None
    login_at: datetime | None = None
    stale: bool = False


def _serializer() -> URLSafeSerializer:
    return URLSafeSerializer(settings.secret_key, salt=_SALT)


def max_age() -> timedelta:
    return timedelta(hours=settings.session_max_hours)


def remaining(login_at: datetime, now: datetime) -> timedelta:
    """How long a session that started at `login_at` still has to live."""
    return max(login_at + max_age() - now, timedelta(0))


def issue_session(account: Account, login_at: datetime) -> str:
    """Cookie value for `account`. `login_at` is kept across a re-issue, so a
    password change never extends the session beyond its original expiry."""
    return _serializer().dumps({
        "aid": account.id,
        "ver": account.session_version,
        "at": int(login_at.replace(tzinfo=timezone.utc).timestamp()),
    })


def read_session(db: Session, cookie: str | None, now: datetime) -> SessionCheck:
    """Whether a cookie still counts at `now` (naive UTC, from the clock seam)."""
    if not cookie:
        return SessionCheck(None)
    try:
        data = _serializer().loads(cookie)
        account_id, version = int(data["aid"]), int(data["ver"])
        login_at = datetime.fromtimestamp(int(data["at"]), timezone.utc).replace(tzinfo=None)
    except (BadSignature, KeyError, TypeError, ValueError, OverflowError, OSError):
        return SessionCheck(None, stale=True)
    if now - login_at >= max_age():
        return SessionCheck(None, stale=True)
    account = db.get(Account, account_id)
    if account is None or not account.active or account.session_version != version:
        return SessionCheck(None, stale=True)
    return SessionCheck(account, login_at=login_at)


def account_for_session(db: Session, cookie: str | None, now: datetime) -> Account | None:
    """The Account a cookie belongs to, or None when it no longer counts."""
    return read_session(db, cookie, now).account
