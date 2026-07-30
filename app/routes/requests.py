from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.services import catalog, snapshots
from app.services.requests import RequestError, submit_request
from app.templating import templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def request_form(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        request, "request_form.html",
        {"factories": catalog.list_factories(db), "uoms": catalog.list_uoms(db)},
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


@router.get("/fragments/categories", response_class=HTMLResponse)
def categories_fragment(request: Request, factory_id: int, db: Session = Depends(get_db)):
    from app.services import config_admin, snapshots

    source = snapshots.source_for_factory(db, factory_id)
    return templates.TemplateResponse(
        request, "partials/category_select.html",
        {"categories": config_admin.active_categories(db, source)},
    )


@router.get("/fragments/subgroups", response_class=HTMLResponse)
def subgroups_fragment(request: Request, group_id: int, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        request, "partials/subgroup_select.html",
        {"subgroups": catalog.subgroups_for_group(db, group_id)},
    )


@router.post("/fragments/duplicates", response_class=HTMLResponse)
def duplicates_fragment(
    request: Request,
    factory_id: int = Form(...),
    item_name: str = Form(""),
    brand: str = Form(""),
    model: str = Form(""),
    db: Session = Depends(get_db),
):
    query = " ".join(p for p in [item_name, brand, model] if p).strip()
    source = snapshots.source_for_factory(db, factory_id)
    if len(query) < 3:
        return templates.TemplateResponse(
            request, "partials/duplicate_list.html",
            {"items": [], "query_too_short": True, "no_snapshot": False, "suggest": None},
        )
    no_snapshot = snapshots.latest_import(db, source) is None
    items = [] if no_snapshot else snapshots.search_similar(db, source=source, query=query)

    # Piggyback the search-name suggestion on this same request and deliver it
    # via an out-of-band swap — one round-trip, and it can't fail to trigger.
    # Classify from the BASE name only: brand/model would poison the category.
    from app.services.classifier import classify
    from app.services.llm_backend import get_llm

    suggest = classify(
        db,
        item_name,
        llm=get_llm(),
        snapshot_source=None if no_snapshot else source,
    )
    return templates.TemplateResponse(
        request, "partials/duplicate_list.html",
        {
            "items": items,
            "query_too_short": False,
            "no_snapshot": no_snapshot,
            "suggest": suggest,
        },
    )


@router.post("/fragments/searchname", response_class=HTMLResponse)
def searchname_fragment(
    request: Request,
    item_name: str = Form(""),
    brand: str = Form(""),
    model: str = Form(""),
    db: Session = Depends(get_db),
):
    text = " ".join(p for p in [item_name, brand, model] if p).strip()
    if len(text) < 3:
        return HTMLResponse("")
    from app.services.classifier import classify
    from app.services.llm_backend import get_llm

    result = classify(db, text, llm=get_llm())
    return templates.TemplateResponse(
        request, "partials/searchname_suggest.html", result
    )


@router.post("/fragments/size", response_class=HTMLResponse)
def size_fragment(request: Request, size: str = Form("")):
    from app.services.units import normalize_size

    canonical = normalize_size(size)
    changed = bool(canonical) and canonical != " ".join((size or "").split())
    return templates.TemplateResponse(
        request, "partials/size_hint.html",
        {"canonical": canonical, "changed": changed},
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
    variant: str = Form(""),
    spec_note: str = Form(""),
    uom: str = Form(""),
    search_name: str = Form(""),
    purchase_price: str = Form(""),
    procurement_category: str = Form(""),
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
            variant=variant,
            spec_note=spec_note,
            uom=uom,
            search_name=search_name,
            purchase_price=purchase_price,
            procurement_category=procurement_category,
        )
    except RequestError as e:
        return templates.TemplateResponse(
            request, "partials/form_error.html", {"message": str(e)}, status_code=422
        )
    return templates.TemplateResponse(
        request, "partials/form_success.html", {"req": req}
    )
