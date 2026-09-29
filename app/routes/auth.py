from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.services.auth import AuthError, authenticate
from app.services.clock import Clock, get_clock
from app.services.sessions import COOKIE_NAME, account_for_session, issue_session
from app.templating import templates

router = APIRouter()


def _safe_next(next_path: str | None) -> str:
    # Only same-site paths; "//evil.com" or "https://..." would be an open redirect.
    if next_path and next_path.startswith("/") and not next_path.startswith("//") \
            and "\\" not in next_path:
        return next_path
    return "/"


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: str | None = None, db: Session = Depends(get_db)):
    if account_for_session(db, request.cookies.get(COOKIE_NAME)) is not None:
        return RedirectResponse(_safe_next(next), status_code=303)
    return templates.TemplateResponse(
        request, "login.html", {"next": _safe_next(next), "email": "", "error": None}
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
        account = authenticate(db, email, password)
    except AuthError as e:
        return templates.TemplateResponse(
            request, "login.html",
            {"next": _safe_next(next), "email": email, "error": str(e)},
            status_code=401,
        )
    response = RedirectResponse(_safe_next(next), status_code=303)
    response.set_cookie(
        COOKIE_NAME,
        issue_session(account, clock()),
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
    )
    return response


@router.post("/logout")
def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(COOKIE_NAME, httponly=True, samesite="lax",
                           secure=settings.cookie_secure)
    return response
