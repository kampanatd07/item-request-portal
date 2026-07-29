from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ExportBatch, Factory, ItemRequest
from app.services import catalog
from app.services.exporter import ExportError, build_workbook_bytes, export_pending
from app.services.requests import RequestError, change_status
from app.templating import templates

router = APIRouter(prefix="/exports")

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("", response_class=HTMLResponse)
def exports_page(request: Request, db: Session = Depends(get_db)):
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
    return templates.TemplateResponse(
        request, "exports.html",
        {"factories": factories, "pending": pending, "batches": batches},
    )


@router.post("/{factory_id}", response_class=HTMLResponse)
def create_export(request: Request, factory_id: int, db: Session = Depends(get_db)):
    try:
        batch = export_pending(db, factory_id)
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
def mark_created(request: Request, batch_id: int, db: Session = Depends(get_db)):
    reqs = list(
        db.scalars(
            select(ItemRequest).where(
                ItemRequest.export_batch_id == batch_id,
                ItemRequest.status == "exported",
            )
        )
    )
    try:
        for req in reqs:
            change_status(db, req.id, new_status="created", actor="procurement")
    except RequestError as e:
        return templates.TemplateResponse(
            request, "partials/form_error.html", {"message": str(e)}, status_code=422
        )
    batch = db.get(ExportBatch, batch_id)
    return templates.TemplateResponse(
        request, "partials/export_result.html", {"batch": batch, "created": True}
    )
