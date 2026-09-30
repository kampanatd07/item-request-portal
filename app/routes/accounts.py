"""Administrator pages for Accounts. Guarded as Administrator-only in main.py."""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ROLES, Account
from app.routes.deps import current_account
from app.services import auth, catalog
from app.services.auth import AuthError
from app.services.clock import Clock, get_clock
from app.templating import templates

def _stamp_now(request: Request, clock: Clock = Depends(get_clock)) -> None:
    # The table shows "locked until"; it reads now from the clock seam.
    request.state.now = clock()


router = APIRouter(prefix="/admin/accounts", dependencies=[Depends(_stamp_now)])

ROLE_LABELS = {"requester": "ผู้ขอ", "procurement": "จัดซื้อ", "administrator": "ผู้ดูแลระบบ"}
# Responses that carry a temporary password must never be stored by a browser or proxy.
NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}


def _plant_id(raw: str) -> int | None:
    return int(raw) if raw.strip().isdigit() else None


def _ctx(db: Session, acting: Account, **extra) -> dict:
    return {
        "accounts": auth.list_accounts(db),
        "factories": catalog.list_factories(db),
        "roles": ROLES,
        "role_labels": ROLE_LABELS,
        "acting": acting,
        **extra,
    }


def _table(request: Request, db: Session, acting: Account) -> HTMLResponse:
    return templates.TemplateResponse(request, "partials/accounts_table.html", _ctx(db, acting))


def _error(request: Request, e: AuthError) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "partials/form_error.html", {"message": str(e)}, status_code=422
    )


def _temporary_password(request: Request, db: Session, acting: Account, target: Account,
                        password: str, created: bool) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "partials/temporary_password.html",
        _ctx(db, acting, target=target, password=password, created=created),
        headers=NO_STORE,
    )


@router.get("", response_class=HTMLResponse)
def accounts_page(request: Request, db: Session = Depends(get_db),
                  acting: Account = Depends(current_account)):
    return templates.TemplateResponse(request, "accounts.html", _ctx(db, acting))


@router.post("", response_class=HTMLResponse)
def create(
    request: Request,
    email: str = Form(""),
    display_name: str = Form(""),
    role: str = Form(""),
    factory_id: str = Form(""),
    db: Session = Depends(get_db),
    acting: Account = Depends(current_account),
):
    try:
        account, password = auth.admin_create_account(
            db, acting, email=email, display_name=display_name, role=role,
            factory_id=_plant_id(factory_id),
        )
    except AuthError as e:
        return _error(request, e)
    return _temporary_password(request, db, acting, account, password, created=True)


@router.post("/{account_id}/access", response_class=HTMLResponse)
def change_access(
    request: Request,
    account_id: int,
    role: str = Form(""),
    factory_id: str = Form(""),
    db: Session = Depends(get_db),
    acting: Account = Depends(current_account),
):
    try:
        auth.change_access(db, acting, account_id, role=role, factory_id=_plant_id(factory_id))
    except AuthError as e:
        return _error(request, e)
    return _table(request, db, acting)


@router.post("/{account_id}/deactivate", response_class=HTMLResponse)
def deactivate(request: Request, account_id: int, db: Session = Depends(get_db),
               acting: Account = Depends(current_account)):
    try:
        auth.deactivate_account(db, acting, account_id)
    except AuthError as e:
        return _error(request, e)
    return _table(request, db, acting)


@router.post("/{account_id}/reactivate", response_class=HTMLResponse)
def reactivate(request: Request, account_id: int, db: Session = Depends(get_db),
               acting: Account = Depends(current_account)):
    try:
        auth.reactivate_account(db, acting, account_id)
    except AuthError as e:
        return _error(request, e)
    return _table(request, db, acting)


@router.post("/{account_id}/reset-password", response_class=HTMLResponse)
def reset_password(request: Request, account_id: int, db: Session = Depends(get_db),
                   acting: Account = Depends(current_account)):
    try:
        password = auth.reset_password(db, acting, account_id)
    except AuthError as e:
        return _error(request, e)
    return _temporary_password(request, db, acting, db.get(Account, account_id), password,
                               created=False)
