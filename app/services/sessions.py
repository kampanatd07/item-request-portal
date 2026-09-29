"""Signed session cookie: which Account, which session version, when it logged in.

The cookie only proves what we issued; whether it still counts is decided
against the DB on every request, so deactivation or a password change
(bumping session_version) logs the Account out everywhere at once.
"""

from datetime import datetime, timezone

from itsdangerous import BadSignature, URLSafeSerializer
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Account

COOKIE_NAME = "session"
_SALT = "session-cookie"


def _serializer() -> URLSafeSerializer:
    return URLSafeSerializer(settings.secret_key, salt=_SALT)


def issue_session(account: Account, now: datetime) -> str:
    return _serializer().dumps(
        {"aid": account.id, "ver": account.session_version, "at": int(now.replace(tzinfo=timezone.utc).timestamp())}
    )


def account_for_session(db: Session, cookie: str | None) -> Account | None:
    """The Account a cookie belongs to, or None when it no longer counts."""
    if not cookie:
        return None
    try:
        data = _serializer().loads(cookie)
        account_id, version = int(data["aid"]), int(data["ver"])
    except (BadSignature, KeyError, TypeError, ValueError):
        return None
    account = db.get(Account, account_id)
    if account is None or not account.active or account.session_version != version:
        return None
    return account
