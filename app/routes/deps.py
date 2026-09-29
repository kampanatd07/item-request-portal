"""Who is asking: the current Account and Role checks.

`current_account` is the only piece an SSO provider would replace; every
route reaches the Account through it.
"""

from collections.abc import Callable
from urllib.parse import quote

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ROLES, Account
from app.services.sessions import COOKIE_NAME, account_for_session


class LoginRequired(Exception):
    """Raised for an anonymous visitor; main.py turns it into a redirect to login."""

    def __init__(self, next_path: str) -> None:
        self.next_path = next_path


def login_url(next_path: str | None = None) -> str:
    if not next_path or next_path == "/":
        return "/login"
    return f"/login?next={quote(next_path, safe='/')}"


def current_account(request: Request, db: Session = Depends(get_db)) -> Account:
    account = account_for_session(db, request.cookies.get(COOKIE_NAME))
    if account is None:
        raise LoginRequired(request.url.path)
    # Templates read it for the header (name + logout).
    request.state.account = account
    return account


def require_role(minimum: str) -> Callable[..., Account]:
    """Dependency allowing `minimum` and every higher Role (ROLES is lowest → highest)."""
    if minimum not in ROLES:
        raise ValueError(f"unknown role: {minimum}")
    floor = ROLES.index(minimum)

    def _check(account: Account = Depends(current_account)) -> Account:
        if ROLES.index(account.role) < floor:
            raise HTTPException(status_code=403, detail="บัญชีนี้ไม่มีสิทธิ์ใช้งานหน้านี้")
        return account

    return _check
