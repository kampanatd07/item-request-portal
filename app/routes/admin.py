from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.services import snapshots
from app.services.snapshots import SnapshotError
from app.templating import templates

router = APIRouter(prefix="/admin")


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
