from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.services import catalog
from app.services.requests import RequestError, submit_request
from app.templating import templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def request_form(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        request, "request_form.html", {"factories": catalog.list_factories(db)}
    )


@router.get("/fragments/systems", response_class=HTMLResponse)
def systems_fragment(request: Request, factory_id: int, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        request, "partials/system_select.html",
        {"systems": catalog.systems_for_factory(db, factory_id)},
    )


@router.get("/fragments/groups", response_class=HTMLResponse)
def groups_fragment(request: Request, code_system_id: int, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        request, "partials/group_select.html",
        {"groups": catalog.groups_for_system(db, code_system_id)},
    )


@router.get("/fragments/subgroups", response_class=HTMLResponse)
def subgroups_fragment(request: Request, group_id: int, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        request, "partials/subgroup_select.html",
        {"subgroups": catalog.subgroups_for_group(db, group_id)},
    )


@router.post("/requests", response_class=HTMLResponse)
def create_request(
    request: Request,
    requester_name: str = Form(...),
    requester_email: str = Form(...),
    factory_id: int = Form(...),
    code_system_id: int = Form(...),
    group_id: int = Form(...),
    subgroup_id: int | None = Form(None),
    item_name: str = Form(...),
    brand: str = Form(""),
    model: str = Form(""),
    size: str = Form(""),
    spec_note: str = Form(""),
    uom: str = Form(""),
    db: Session = Depends(get_db),
):
    try:
        req = submit_request(
            db,
            requester_name=requester_name,
            requester_email=requester_email,
            factory_id=factory_id,
            code_system_id=code_system_id,
            group_id=group_id,
            subgroup_id=subgroup_id,
            item_name=item_name,
            brand=brand,
            model=model,
            size=size,
            spec_note=spec_note,
            uom=uom,
        )
    except RequestError as e:
        return templates.TemplateResponse(
            request, "partials/form_error.html", {"message": str(e)}, status_code=422
        )
    return templates.TemplateResponse(
        request, "partials/form_success.html", {"req": req}
    )
