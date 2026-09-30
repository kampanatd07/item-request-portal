from datetime import datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import Account
from app.routes.deps import (
    CHANGE_PASSWORD_PATH,
    MY_REQUESTS_PATH,
    safe_next,
    session_account,
)
from app.services.auth import AuthError, authenticate, change_own_password
from app.services.clock import Clock, get_clock
from app.services.sessions import COOKIE_NAME, account_for_session, issue_session, remaining
from app.templating import templates

router = APIRouter()


def _landing(account: Account, next_path: str | None) -> str:
    """Where a logged-in Account goes from the login page.

    A temporary password must be replaced before anything else (AC11). With no
    page to return to, a Requester lands on "My requests", everyone else on the
    request form.
    """
    if account.must_change_password:
        return CHANGE_PASSWORD_PATH
    target = safe_next(next_path)
    if target == "/" and account.role == "requester":
        return MY_REQUESTS_PATH
    return target


def _set_session_cookie(response: Response, account: Account, login_at: datetime,
                        now: datetime) -> None:
    """Cookie lives only as long as the session has left (server checks too)."""
    response.set_cookie(
        COOKIE_NAME,
        issue_session(account, login_at),
        max_age=int(remaining(login_at, now).total_seconds()),
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
    )


@router.get("/login", response_class=HTMLResponse)
def login_page(
    request: Request,
    next: str | None = None,
    relogin: str | None = None,
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
):
    account = account_for_session(db, request.cookies.get(COOKIE_NAME), clock())
    if account is not None:
        return RedirectResponse(_landing(account, next), status_code=303)
    return templates.TemplateResponse(
        request, "login.html",
        {"next": safe_next(next), "email": "", "error": None, "relogin": bool(relogin)},
    )


@router.post("/login", response_class=HTMLResponse)
def login(
    request: Request,
    email: str = Form(""),
    password: str = Form(""),
    next: str = Form("/"),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
):
    try:
        account = authenticate(db, email, password, now=clock())
    except AuthError as e:
        return templates.TemplateResponse(
            request, "login.html",
            {"next": safe_next(next), "email": email, "error": str(e), "relogin": False},
            status_code=401,
        )
    response = RedirectResponse(_landing(account, next), status_code=303)
    now = clock()
    _set_session_cookie(response, account, now, now)
    return response


@router.post("/logout")
def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(COOKIE_NAME, httponly=True, samesite="lax",
                           secure=settings.cookie_secure)
    return response


@router.get(CHANGE_PASSWORD_PATH, response_class=HTMLResponse)
def change_password_page(
    request: Request,
    done: str | None = None,
    account: Account = Depends(session_account),
):
    return templates.TemplateResponse(
        request, "change_password.html",
        {"forced": account.must_change_password,
         "done": bool(done) and not account.must_change_password},
    )


@router.post(CHANGE_PASSWORD_PATH, response_class=HTMLResponse)
def change_password(
    request: Request,
    current_password: str = Form(""),
    new_password: str = Form(""),
    confirm_password: str = Form(""),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
    account: Account = Depends(session_account),
):
    forced = account.must_change_password
    try:
        change_own_password(db, account, current=current_password, new=new_password,
                            confirm=confirm_password, now=clock())
    except AuthError as e:
        return templates.TemplateResponse(
            request, "change_password.html", {"forced": forced, "error": str(e)},
            status_code=422,
        )
    # Other sessions died with the version bump; this one carries on with a
    # fresh cookie that keeps the original login time and expiry. Redirect
    # (Post/Redirect/Get) so a refresh does not resend the old password.
    response = RedirectResponse(f"{CHANGE_PASSWORD_PATH}?done=1", status_code=303)
    _set_session_cookie(response, account, request.state.login_at, clock())
    return response
