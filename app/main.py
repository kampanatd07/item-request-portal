from fastapi import Depends, FastAPI, Request
from fastapi.responses import RedirectResponse, Response

from app.config import settings

from app.routes.admin import router as admin_router
from app.routes.auth import router as auth_router
from app.routes.deps import LoginRequired, current_account, login_url
from app.routes.exports import router as exports_router
from app.routes.queue import router as queue_router
from app.routes.requests import router as requests_router

# The API docs list every route; keep them to dev machines.
_dev = settings.app_env == "dev"
app = FastAPI(
    title="Item Request Portal",
    docs_url="/docs" if _dev else None,
    redoc_url="/redoc" if _dev else None,
    openapi_url="/openapi.json" if _dev else None,
)


@app.exception_handler(LoginRequired)
def _redirect_to_login(request: Request, exc: LoginRequired) -> Response:
    target = login_url(exc.next_path)
    if request.headers.get("HX-Request"):
        # A 303 inside an HTMX swap would paste the login page into a fragment;
        # HX-Redirect makes htmx navigate the whole page instead.
        return Response(status_code=401, headers={"HX-Redirect": target})
    return RedirectResponse(target, status_code=303)


# Login is required at router level, so a new route added to these routers is
# protected even if its author forgets. Only auth_router is public.
_login_required = [Depends(current_account)]
app.include_router(auth_router)
app.include_router(requests_router, dependencies=_login_required)
app.include_router(queue_router, dependencies=_login_required)
app.include_router(admin_router, dependencies=_login_required)
app.include_router(exports_router, dependencies=_login_required)
