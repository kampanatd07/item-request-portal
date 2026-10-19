from fastapi import APIRouter, BackgroundTasks, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import SessionFactory, get_db, get_session_factory
from app.models import Account, ItemRequest
from app.routes.deps import current_account
from app.services import catalog, snapshots
from app.services.mail import MailSender, get_mail_sender
from app.services.notify import notify_resubmitted
from app.services.requests import (
    RequestConflict,
    RequestError,
    RequestForbidden,
    RequestNotFound,
    is_originator,
    list_my_requests,
    may_resubmit,
    needs_info_reason,
    originator_editable,
    resubmit_request,
    resubmittable,
    submit_request,
)
from app.templating import templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def request_form(
    request: Request,
    db: Session = Depends(get_db),
    account: Account = Depends(current_account),
):
    # A Requester's Plant is fixed, so they are offered only that one.
    if account.role == "requester":
        factories = [account.factory]
    else:
        factories = catalog.list_factories(db)
    return templates.TemplateResponse(
        request, "request_form.html",
        {"factories": factories, "uoms": catalog.list_uoms(db),
         "plant_locked": account.role == "requester"},
    )


@router.get("/my-requests", response_class=HTMLResponse)
def my_requests(
    request: Request,
    db: Session = Depends(get_db),
    account: Account = Depends(current_account),
) -> HTMLResponse:
    def can_resubmit(req: ItemRequest) -> bool:
        return may_resubmit(req, account)

    def made_for_me(req: ItemRequest) -> bool:
        return is_originator(req, account)

    return templates.TemplateResponse(
        request, "my_requests.html",
        {"requests": list_my_requests(db, account),
         "may_resubmit": can_resubmit, "is_originator": made_for_me},
    )


def _error_status(e: RequestError) -> int:
    if isinstance(e, RequestNotFound):
        return 404
    if isinstance(e, RequestForbidden):
        return 403
    if isinstance(e, RequestConflict):
        return 409
    return 422


@router.get("/my-requests/{request_id}/resubmit", response_class=HTMLResponse)
def resubmit_form(
    request: Request,
    request_id: int,
    db: Session = Depends(get_db),
    account: Account = Depends(current_account),
) -> HTMLResponse:
    from app.services import config_admin

    try:
        req = resubmittable(db, request_id, account)
    except RequestError as e:
        page = "forbidden.html" if isinstance(e, RequestForbidden) else "message.html"
        # 409 = the request is theirs but no longer waiting, e.g. an old Needs
        # Info email: point at where it can still be seen.
        link = f"/my-requests#request-{request_id}" if isinstance(e, RequestConflict) else None
        return templates.TemplateResponse(request, page, {"message": str(e), "link": link},
                                          status_code=_error_status(e))
    def with_current(options: list, current: object) -> list:
        # A system/group/sub-category switched off since is still the
        # request's value: keep it selectable, or the browser would post the
        # first option and an untouched form would look edited.
        return options if current is None or current in options else [*options, current]

    return templates.TemplateResponse(
        request, "request_form.html",
        {
            "r": req,
            "reason": needs_info_reason(db, req),
            "uoms": catalog.list_uoms(db),
            "plant_locked": True,
            "originator_editable": originator_editable(req, account),
            "systems": with_current(catalog.systems_for_factory(db, req.factory_id),
                                    req.code_system),
            "groups": with_current(catalog.groups_for_system(db, req.code_system_id),
                                   req.group),
            "subgroups": with_current(catalog.subgroups_for_group(db, req.group_id),
                                      req.subgroup),
            "categories": config_admin.active_categories(
                db, snapshots.source_for_factory(db, req.factory_id)),
        },
    )


@router.post("/my-requests/{request_id}/resubmit", response_class=HTMLResponse)
def resubmit(
    request: Request,
    request_id: int,
    background: BackgroundTasks,
    code_system_id: int = Form(...),
    group_id: int = Form(...),
    subgroup_id: int | None = Form(None),
    item_name: str = Form(""),
    brand: str = Form(""),
    model: str = Form(""),
    size: str = Form(""),
    variant: str = Form(""),
    spec_note: str = Form(""),
    uom: str = Form(""),
    search_name: str = Form(""),
    purchase_price: str = Form(""),
    procurement_category: str = Form(""),
    reply: str = Form(""),
    # None = not posted (keep the stored value); "" = cleared.
    on_behalf_of: str | None = Form(None),
    originator_email: str | None = Form(None),
    db: Session = Depends(get_db),
    account: Account = Depends(current_account),
    sender: MailSender = Depends(get_mail_sender),
    session_factory: SessionFactory = Depends(get_session_factory),
) -> HTMLResponse:
    # No factory_id: the Plant is never read from the form on a resubmit.
    try:
        result = resubmit_request(
            db, request_id, account, reply=reply, code_system_id=code_system_id,
            group_id=group_id, subgroup_id=subgroup_id, item_name=item_name, brand=brand,
            model=model, size=size, variant=variant, spec_note=spec_note, uom=uom,
            search_name=search_name, purchase_price=purchase_price,
            procurement_category=procurement_category, on_behalf_of=on_behalf_of,
            originator_email=originator_email,
        )
    except RequestError as e:
        return templates.TemplateResponse(
            request, "partials/form_error.html", {"message": str(e)},
            status_code=_error_status(e),
        )
    if result.notify_event_id is not None:
        # After the response, best-effort (decisions.md 2026-10-16).
        background.add_task(notify_resubmitted, session_factory, result.req.id,
                            result.notify_event_id, sender)
    return templates.TemplateResponse(
        request, "partials/resubmit_success.html", {"req": result.req}
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
    subgroup_id: str = Form(""),
    dup_only: str = Form(""),
    no_autopick: str = Form(""),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    query = " ".join(p for p in [item_name, brand, model] if p).strip()
    source = snapshots.source_for_factory(db, factory_id)
    if len(query) < 3:
        return templates.TemplateResponse(
            request, "partials/duplicate_list.html",
            {"items": [], "query_too_short": True, "no_snapshot": False, "suggest": None},
        )
    no_snapshot = snapshots.latest_import(db, source) is None
    items = [] if no_snapshot else snapshots.search_similar(db, source=source, query=query)
    if dup_only:
        # A resubmit form on load: its category and search name are already
        # chosen, so no suggestion (which could auto-pick another category,
        # and may ask the LLM) — only the duplicates.
        return templates.TemplateResponse(
            request, "partials/duplicate_list.html",
            {"items": items, "query_too_short": False, "no_snapshot": no_snapshot,
             "suggest": None},
        )

    # Piggyback the search-name suggestion on this same request and deliver it
    # via an out-of-band swap — one round-trip, and it can't fail to trigger.
    # Classify from the BASE name only: brand/model would poison the category.
    from app.services.classifier import classify
    from app.services.llm_backend import get_llm

    # If the user already picked a category, its product type steers the search
    # name: a Service must be named after the work, not an object in the phrase.
    from app.models import CodeGroup

    chosen = db.get(CodeGroup, int(subgroup_id)) if subgroup_id.isdigit() else None
    suggest = classify(
        db,
        item_name,
        llm=get_llm(),
        snapshot_source=None if no_snapshot else source,
        product_type=chosen.product_type if chosen else None,
    )

    # Category proposal rides along too: the user types the name once and gets
    # duplicates, a search name and a category without three separate waits.
    from app.services.categorizer import AUTO_SELECT_CONFIDENCE, suggest_category

    categories = suggest_category(db, item_name, llm=get_llm())
    return templates.TemplateResponse(
        request, "partials/duplicate_list.html",
        {
            "items": items,
            "query_too_short": False,
            "no_snapshot": no_snapshot,
            "suggest": suggest,
            "categories": categories,
            # A resubmit shows the suggestions but never picks one itself: the
            # stored category was chosen on purpose (review 2026-10-16).
            "auto_select": float("inf") if no_autopick else AUTO_SELECT_CONFIDENCE,
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
    factory_id: int | None = Form(None),
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
    on_behalf_of: str = Form(""),
    originator_email: str = Form(""),
    db: Session = Depends(get_db),
    account: Account = Depends(current_account),
):
    # Requester name/email are never read from the form: the request is always
    # in the logged-in Account's name.
    try:
        req = submit_request(
            db,
            account,
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
            on_behalf_of=on_behalf_of,
            originator_email=originator_email,
        )
    except RequestError as e:
        return templates.TemplateResponse(
            request, "partials/form_error.html", {"message": str(e)}, status_code=422
        )
    return templates.TemplateResponse(
        request, "partials/form_success.html", {"req": req}
    )
