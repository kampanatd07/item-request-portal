from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ItemRequest
from app.services.requests import RequestError, change_status, list_queue
from app.templating import templates

router = APIRouter(prefix="/queue")


@router.get("", response_class=HTMLResponse)
def queue_page(request: Request, status: str | None = None, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        request, "queue.html", {"requests": list_queue(db, status), "current": status}
    )


@router.get("/{request_id}", response_class=HTMLResponse)
def request_detail(request: Request, request_id: int, db: Session = Depends(get_db)):
    req = db.get(ItemRequest, request_id)
    return templates.TemplateResponse(
        request, "request_detail.html", {"req": req}
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
