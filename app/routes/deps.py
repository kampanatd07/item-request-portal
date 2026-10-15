"""Who is asking: the current Account and Role checks.

`session_account` / `current_account` are the only pieces an SSO provider
would replace; every route reaches the Account through them.
"""

from collections.abc import Callable
from urllib.parse import quote, urlsplit

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

    def __init__(self, next_path: str | None, stale: bool = False) -> None:
        self.next_path = next_path
        self.stale = stale  # a cookie was sent but no longer counts


class PasswordChangeRequired(Exception):
    """The Account must change its password first; main.py redirects there."""


def safe_next(next_path: str | None) -> str:
    """A same-site path to return to after login, else "/".

    "//evil.com", "https://..." or a backslash trick would be an open redirect.
    """
    if next_path and next_path.startswith("/") and not next_path.startswith("//") \
            and "\\" not in next_path:
        return next_path
    return "/"


def _return_path(request: Request) -> str | None:
    """The page to come back to after logging in again.

    An HTMX request targets a fragment or a POST-only endpoint, so use the page
    the person was on (HX-Current-URL), and only if it is on this site. A plain
    POST has no page to return to. Query strings are kept.
    """
    if request.headers.get("HX-Request"):
        current = urlsplit(request.headers.get("HX-Current-URL", ""))
        if current.netloc and current.netloc != request.url.netloc:
            return None
        path = current.path + (f"?{current.query}" if current.query else "")
    elif request.method == "GET":
        path = request.url.path + (f"?{request.url.query}" if request.url.query else "")
    else:
        return None
    safe = safe_next(path)
    return safe if safe != "/" else None


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
        raise LoginRequired(_return_path(request), stale=check.stale)
    # Templates read it for the header; the password page re-issues the cookie
    # with the original login time.
    request.state.account = check.account
    request.state.login_at = check.login_at
    _count_pending_mail(request, db, check.account, clock)
    return check.account


def _count_pending_mail(request: Request, db: Session, account: Account, clock: Clock) -> None:
    """The menu's "Export (อีเมลค้าง N)" (STORY-002 ticket 06), counted here while
    the request's session is open; templates only read the number.

    Procurement and above only, and only for full pages: an HTMX fragment has
    no menu, so it does not pay for the query.
    """
    from app.services.notify import pending_notifications

    if request.headers.get("HX-Request") or account.must_change_password \
            or not has_role(account, "procurement"):
        return
    request.state.pending_mail_count = len(pending_notifications(db, clock()))


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
