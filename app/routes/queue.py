from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ItemRequest
from app.services.requests import (
    RequestError,
    change_category,
    change_status,
    edit_name,
    list_queue,
    originator_of,
    override_code,
)
from app.templating import templates

router = APIRouter(prefix="/queue")


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
):
    # Actor is hardcoded until auth (slice 6); every change still lands in the audit trail.
    try:
        req = change_status(
            db, request_id, new_status=new_status, actor="procurement", note=note or None
        )
    except RequestError as e:
        return templates.TemplateResponse(
            request, "partials/form_error.html", {"message": str(e)}, status_code=422
        )
    return templates.TemplateResponse(
        request, "partials/status_panel.html", {"req": req}
    )


@router.post("/{request_id}/name", response_class=HTMLResponse)
def rename_item(
    request: Request,
    request_id: int,
    new_name: str = Form(...),
    db: Session = Depends(get_db),
):
    try:
        req = edit_name(db, request_id, new_name=new_name, actor="procurement")
    except RequestError as e:
        return templates.TemplateResponse(
            request, "partials/form_error.html", {"message": str(e)}, status_code=422
        )
    return templates.TemplateResponse(
        request, "partials/name_panel.html", {"req": req}
    )


@router.post("/{request_id}/category", response_class=HTMLResponse)
def recategorise(
    request: Request,
    request_id: int,
    subgroup_id: int = Form(...),
    db: Session = Depends(get_db),
):
    try:
        req = change_category(
            db, request_id, subgroup_id=subgroup_id, actor="procurement"
        )
    except RequestError as e:
        return templates.TemplateResponse(
            request, "partials/form_error.html", {"message": str(e)}, status_code=422
        )
    return templates.TemplateResponse(
        request, "partials/category_panel.html", {"req": req, "taxonomy": _taxonomy(db)}
    )


@router.post("/{request_id}/code", response_class=HTMLResponse)
def edit_code(
    request: Request,
    request_id: int,
    new_code: str = Form(...),
    db: Session = Depends(get_db),
):
    try:
        req = override_code(db, request_id, new_code=new_code, actor="procurement")
    except RequestError as e:
        return templates.TemplateResponse(
            request, "partials/form_error.html", {"message": str(e)}, status_code=422
        )
    return templates.TemplateResponse(
        request, "partials/status_panel.html", {"req": req}
    )
