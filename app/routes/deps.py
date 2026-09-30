"""Who is asking: the current Account and Role checks.

`session_account` / `current_account` are the only pieces an SSO provider
would replace; every route reaches the Account through them.
"""

from collections.abc import Callable
from urllib.parse import quote

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ROLES, Account
from app.services.auth import has_role
from app.services.clock import Clock, get_clock
from app.services.sessions import COOKIE_NAME, read_session

CHANGE_PASSWORD_PATH = "/account/password"
MY_REQUESTS_PATH = "/my-requests"


class RoleForbidden(HTTPException):
    """The Account's Role may not use this page; main.py renders it as a Thai page."""

    def __init__(self) -> None:
        super().__init__(status_code=403, detail="บัญชีนี้ไม่มีสิทธิ์ใช้งานหน้านี้")


class LoginRequired(Exception):
    """Raised for an anonymous visitor; main.py turns it into a redirect to login."""

    def __init__(self, next_path: str, stale: bool = False) -> None:
        self.next_path = next_path
        self.stale = stale  # a cookie was sent but no longer counts


class PasswordChangeRequired(Exception):
    """The Account must change its password first; main.py redirects there."""


def login_url(next_path: str | None = None, relogin: bool = False) -> str:
    params = []
    if relogin:
        params.append("relogin=1")
    if next_path and next_path != "/":
        params.append(f"next={quote(next_path, safe='/')}")
    return "/login" + (f"?{'&'.join(params)}" if params else "")


def session_account(
    request: Request,
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> Account:
    """The logged-in Account, even one that must still change its password.

    Only the change-password page uses this directly; everything else goes
    through `current_account`.
    """
    check = read_session(db, request.cookies.get(COOKIE_NAME), clock())
    if check.account is None:
        raise LoginRequired(request.url.path, stale=check.stale)
    # Templates read it for the header; the password page re-issues the cookie
    # with the original login time.
    request.state.account = check.account
    request.state.login_at = check.login_at
    return check.account


def current_account(account: Account = Depends(session_account)) -> Account:
    """The logged-in Account, once it no longer has to change its password."""
    if account.must_change_password:
        raise PasswordChangeRequired()
    return account


def require_role(minimum: str) -> Callable[..., Account]:
    """Dependency allowing `minimum` and every higher Role (ROLES is lowest → highest)."""
    if minimum not in ROLES:
        raise ValueError(f"unknown role: {minimum}")

    def _check(account: Account = Depends(current_account)) -> Account:
        if not has_role(account, minimum):
            raise RoleForbidden()
        return account

    return _check
