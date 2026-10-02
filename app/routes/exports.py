from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db, get_session_factory
from app.models import Account, ExportBatch, Factory, ItemRequest
from app.routes.deps import current_account
from app.services import catalog
from app.services.exporter import ExportError, build_workbook_bytes, export_pending
from app.services.clock import Clock, get_clock
from app.services.mail import MailSender, get_mail_sender
from app.services.notify import notify_created, pending_notifications, recipients, resend
from app.services.requests import RequestError, change_status
from app.templating import templates

router = APIRouter(prefix="/exports")

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _to(req: ItemRequest) -> str:
    try:
        return ", ".join(recipients(req)[0])
    except Exception:  # noqa: BLE001 - the list must show even if one row is odd
        return "-"


@router.get("", response_class=HTMLResponse)
def exports_page(request: Request, db: Session = Depends(get_db),
                 clock: Clock = Depends(get_clock)):
    factories = catalog.list_factories(db)
    pending = {
        f.id: db.scalar(
            select(ItemRequest)
            .where(
                ItemRequest.factory_id == f.id,
                ItemRequest.status == "approved",
                ItemRequest.export_batch_id.is_(None),
            )
            .limit(1)
        )
        is not None
        for f in factories
    }
    batches = list(
        db.scalars(select(ExportBatch).order_by(ExportBatch.at.desc()).limit(20))
    )
    unsent = [(p, _to(p.req)) for p in pending_notifications(db, clock())]
    return templates.TemplateResponse(
        request, "exports.html",
        {"factories": factories, "pending": pending, "batches": batches, "unsent": unsent},
    )


@router.post("/notifications/resend", response_class=HTMLResponse)
def resend_all(
    request: Request,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
    account: Account = Depends(current_account),
    sender: MailSender = Depends(get_mail_sender),
    session_factory=Depends(get_session_factory),
):
    """"ส่งซ้ำทั้งหมด": everything still owed, in the background (the Graph sender
    paces sends, so a long list takes a while). 'created' ones are grouped per
    (To, CC) as in the first send."""
    pending = pending_notifications(db, clock())
    if pending:
        background.add_task(
            resend, session_factory,
            [p.req.id for p in pending if p.kind == "created"],
            [(p.req.id, p.event_id) for p in pending if p.event_id is not None],
            sender, account.email)
    return templates.TemplateResponse(
        request, "partials/resend_result.html", {"count": len(pending)})


@router.post("/{factory_id}", response_class=HTMLResponse)
def create_export(
    request: Request,
    factory_id: int,
    db: Session = Depends(get_db),
    account: Account = Depends(current_account),
):
    try:
        batch = export_pending(db, factory_id, account=account)
    except ExportError as e:
        return templates.TemplateResponse(
            request, "partials/form_error.html", {"message": str(e)}, status_code=422
        )
    return templates.TemplateResponse(
        request, "partials/export_result.html", {"batch": batch}
    )


@router.get("/{batch_id}/download")
def download_export(batch_id: int, db: Session = Depends(get_db)):
    batch = db.get(ExportBatch, batch_id)
    if batch is None:
        return HTMLResponse("ไม่พบไฟล์", status_code=404)
    reqs = list(
        db.scalars(select(ItemRequest).where(ItemRequest.export_batch_id == batch_id))
    )
    factory = db.get(Factory, batch.factory_id)
    data = build_workbook_bytes(db, factory.code, reqs)
    return StreamingResponse(
        iter([data]),
        media_type=XLSX_MIME,
        headers={"Content-Disposition": f'attachment; filename="{batch.filename}"'},
    )


@router.post("/{batch_id}/mark-created", response_class=HTMLResponse)
def mark_created(
    request: Request,
    batch_id: int,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    account: Account = Depends(current_account),
    sender: MailSender = Depends(get_mail_sender),
    session_factory=Depends(get_session_factory),
):
    reqs = list(
        db.scalars(
            select(ItemRequest).where(
                ItemRequest.export_batch_id == batch_id,
                ItemRequest.status == "exported",
            ).order_by(ItemRequest.id)
        )
    )
    # Email after the response, in its own session: a slow or failed send
    # never blocks marking the batch created (STORY-002 AC1). Each request
    # commits on its own, so the ones already 'created' are emailed even if a
    # later one fails.
    done: list[int] = []
    try:
        for req in reqs:
            change_status(db, req.id, new_status="created", account=account)
            done.append(req.id)
    except RequestError as e:
        if done:
            background.add_task(notify_created, session_factory, done, sender, account.email)
        return templates.TemplateResponse(
            request, "partials/form_error.html", {"message": str(e)}, status_code=422
        )
    background.add_task(notify_created, session_factory, done, sender, account.email)
    batch = db.get(ExportBatch, batch_id)
    return templates.TemplateResponse(
        request, "partials/export_result.html", {"batch": batch, "created": True}
    )
