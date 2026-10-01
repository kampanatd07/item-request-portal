from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Account, ItemRequest
from app.routes.deps import current_account, require_role
from app.services import override_preview
from app.services.clock import Clock, get_clock
from app.services.requests import (
    RequestError,
    RequestForbidden,
    SKIP_CONFIRM_LIMIT,
    check_override,
    change_category,
    change_status,
    edit_name,
    list_queue,
    originator_of,
    override_code,
)
from app.templating import templates

router = APIRouter(prefix="/queue")


def _error(request: Request, e: RequestError) -> HTMLResponse:
    # A Role refusal is 403 so it reads as "not allowed", not "bad input".
    status = 403 if isinstance(e, RequestForbidden) else 422
    return templates.TemplateResponse(
        request, "partials/form_error.html", {"message": str(e)}, status_code=status
    )


@router.get("", response_class=HTMLResponse)
def queue_page(request: Request, status: str | None = None, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        request, "queue.html", {"requests": list_queue(db, status), "current": status}
    )


def _taxonomy(db: Session):
    """[(group, [subs])] of the active central taxonomy, for the re-categorise picker."""
    from sqlalchemy import select

    from app.models import CodeGroup, CodeSystem

    system = db.scalar(select(CodeSystem).where(CodeSystem.code == "CENTRAL"))
    if system is None:
        return []
    groups = list(db.scalars(
        select(CodeGroup).where(
            CodeGroup.code_system_id == system.id,
            CodeGroup.parent_id.is_(None), CodeGroup.active,
        ).order_by(CodeGroup.code)
    ))
    return [
        (g, list(db.scalars(
            select(CodeGroup).where(
                CodeGroup.parent_id == g.id, CodeGroup.active
            ).order_by(CodeGroup.code)
        )))
        for g in groups
    ]


@router.get("/{request_id}", response_class=HTMLResponse)
def request_detail(request: Request, request_id: int, db: Session = Depends(get_db)):
    req = db.get(ItemRequest, request_id)
    return templates.TemplateResponse(
        request, "request_detail.html",
        {"req": req, "taxonomy": _taxonomy(db),
         "originator": originator_of(req) if req else None},
    )


@router.post("/{request_id}/status", response_class=HTMLResponse)
def update_status(
    request: Request,
    request_id: int,
    new_status: str = Form(...),
    note: str = Form(""),
    db: Session = Depends(get_db),
    account: Account = Depends(current_account),
):
    try:
        req = change_status(
            db, request_id, new_status=new_status, account=account, note=note or None
        )
    except RequestError as e:
        return _error(request, e)
    return templates.TemplateResponse(
        request, "partials/status_panel.html", {"req": req}
    )


@router.post("/{request_id}/name", response_class=HTMLResponse)
def rename_item(
    request: Request,
    request_id: int,
    new_name: str = Form(...),
    db: Session = Depends(get_db),
    account: Account = Depends(current_account),
):
    try:
        req = edit_name(db, request_id, new_name=new_name, account=account)
    except RequestError as e:
        return _error(request, e)
    return templates.TemplateResponse(
        request, "partials/name_panel.html", {"req": req}
    )


@router.post("/{request_id}/category", response_class=HTMLResponse)
def recategorise(
    request: Request,
    request_id: int,
    subgroup_id: int = Form(...),
    db: Session = Depends(get_db),
    account: Account = Depends(current_account),
):
    try:
        req = change_category(db, request_id, subgroup_id=subgroup_id, account=account)
    except RequestError as e:
        return _error(request, e)
    return templates.TemplateResponse(
        request, "partials/category_panel.html", {"req": req, "taxonomy": _taxonomy(db)}
    )


def _admin(account: Account = Depends(require_role("administrator"))) -> Account:
    return account


@router.post("/{request_id}/code/check", response_class=HTMLResponse)
def check_code(
    request: Request,
    request_id: int,
    new_code: str = Form(""),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
    account: Account = Depends(_admin),
):
    """Step 1 of an override: show what it would do. Writes nothing."""
    req = db.get(ItemRequest, request_id)
    if req is None:
        return _error(request, RequestError("ไม่พบคำขอนี้"))
    check = check_override(db, req, new_code)
    token = override_preview.issue(check, req, account, clock()) if check.ok else None
    return templates.TemplateResponse(
        request, "partials/override_preview.html",
        {"req": req, "check": check, "token": token,
         "confirm_limit": SKIP_CONFIRM_LIMIT},
    )


@router.post("/{request_id}/code", response_class=HTMLResponse)
def edit_code(
    request: Request,
    request_id: int,
    token: str = Form(""),
    reason: str = Form(""),
    confirm_skip: str = Form(""),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
    account: Account = Depends(_admin),
):
    """Step 2: save exactly what the preview showed, or refuse and ask to check again.
    The code comes only from the signed preview token."""
    req = db.get(ItemRequest, request_id)
    if req is None:
        return _error(request, RequestError("ไม่พบคำขอนี้"))
    try:
        plan = override_preview.read(token, req, account, clock())
        req = override_code(db, request_id, new_code=plan["code"], account=account,
                            reason=reason, confirm_skip=bool(confirm_skip), expected=plan)
    except RequestError as e:
        return _error(request, e)
    return templates.TemplateResponse(
        request, "partials/status_panel.html", {"req": req}
    )
