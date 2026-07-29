from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.services import config_admin, snapshots
from app.services.config_admin import ConfigError
from app.services.snapshots import SnapshotError
from app.templating import templates

router = APIRouter(prefix="/admin")


def _config_ctx(db: Session) -> dict:
    return {
        "uoms": config_admin.list_uoms(db),
        "categories": config_admin.list_categories(db),
        "terms": config_admin.list_terms(db),
        "group_maps": config_admin.list_group_maps(db),
    }


@router.get("/config", response_class=HTMLResponse)
def config_page(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(request, "admin_config.html", _config_ctx(db))


@router.post("/config/uom", response_class=HTMLResponse)
def add_uom(request: Request, code: str = Form(...), name: str = Form(""),
            db: Session = Depends(get_db)):
    try:
        config_admin.add_uom(db, code, name)
    except ConfigError as e:
        return templates.TemplateResponse(
            request, "partials/form_error.html", {"message": str(e)}, status_code=422
        )
    return templates.TemplateResponse(request, "partials/config_tables.html", _config_ctx(db))


@router.post("/config/uom/{uom_id}/toggle", response_class=HTMLResponse)
def toggle_uom(request: Request, uom_id: int, db: Session = Depends(get_db)):
    config_admin.toggle_uom(db, uom_id)
    return templates.TemplateResponse(request, "partials/config_tables.html", _config_ctx(db))


@router.post("/config/category", response_class=HTMLResponse)
def add_category(request: Request, source: str = Form(...), label: str = Form(...),
                 db: Session = Depends(get_db)):
    try:
        config_admin.add_category(db, source, label)
    except ConfigError as e:
        return templates.TemplateResponse(
            request, "partials/form_error.html", {"message": str(e)}, status_code=422
        )
    return templates.TemplateResponse(request, "partials/config_tables.html", _config_ctx(db))


@router.post("/config/category/{category_id}/toggle", response_class=HTMLResponse)
def toggle_category(request: Request, category_id: int, db: Session = Depends(get_db)):
    config_admin.toggle_category(db, category_id)
    return templates.TemplateResponse(request, "partials/config_tables.html", _config_ctx(db))


@router.post("/config/term/{term_id}/toggle", response_class=HTMLResponse)
def toggle_term(request: Request, term_id: int, db: Session = Depends(get_db)):
    config_admin.toggle_term(db, term_id)
    return templates.TemplateResponse(request, "partials/config_tables.html", _config_ctx(db))


@router.post("/config/groupmap/{group_id}", response_class=HTMLResponse)
def set_group_map(
    request: Request, group_id: int,
    item_group_id: str = Form(""), model_group_id: str = Form(""),
    group_type_code: str = Form(""), db: Session = Depends(get_db),
):
    try:
        config_admin.set_group_map(
            db, group_id, item_group_id=item_group_id,
            model_group_id=model_group_id, group_type_code=group_type_code,
        )
    except ConfigError as e:
        return templates.TemplateResponse(
            request, "partials/form_error.html", {"message": str(e)}, status_code=422
        )
    return templates.TemplateResponse(request, "partials/config_tables.html", _config_ctx(db))


@router.get("/snapshots", response_class=HTMLResponse)
def snapshots_page(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        request, "snapshots.html",
        {
            "cbd": snapshots.latest_import(db, "CBD"),
            "d365": snapshots.latest_import(db, "D365"),
        },
    )


@router.post("/snapshots", response_class=HTMLResponse)
async def upload_snapshot(
    request: Request,
    source: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    data = await file.read()
    try:
        imp = snapshots.import_snapshot(
            db, source=source, filename=file.filename or "upload", data=data
        )
    except SnapshotError as e:
        return templates.TemplateResponse(
            request, "partials/form_error.html", {"message": str(e)}, status_code=422
        )
    return templates.TemplateResponse(
        request, "partials/snapshot_result.html", {"imp": imp}
    )
