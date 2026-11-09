from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.config import settings
from app.logging_setup import setup_logging

from app.routes.accounts import router as accounts_router
from app.routes.admin import router as admin_router
from app.routes.auth import router as auth_router
from app.routes.deps import (
    LoginRequired,
    PasswordChangeRequired,
    RoleForbidden,
    CHANGE_PASSWORD_PATH,
    current_account,
    login_url,
    require_role,
)
from app.routes.exports import router as exports_router
from app.routes.queue import router as queue_router
from app.routes.requests import router as requests_router
from app.services.sessions import COOKIE_NAME
from app.templating import templates

setup_logging()

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
    target = login_url(exc.next_path, relogin=exc.stale)
    if request.headers.get("HX-Request"):
        # A 303 inside an HTMX swap would paste the login page into a fragment;
        # HX-Redirect makes htmx navigate the whole page instead.
        response: Response = Response(status_code=401, headers={"HX-Redirect": target})
    else:
        response = RedirectResponse(target, status_code=303)
    if exc.stale:
        # Drop the dead cookie so the "log in again" notice shows once, not forever.
        response.delete_cookie(COOKIE_NAME, httponly=True, samesite="lax",
                               secure=settings.cookie_secure)
    return response


@app.exception_handler(PasswordChangeRequired)
def _redirect_to_change_password(request: Request, exc: PasswordChangeRequired) -> Response:
    if request.headers.get("HX-Request"):
        return Response(status_code=401, headers={"HX-Redirect": CHANGE_PASSWORD_PATH})
    return RedirectResponse(CHANGE_PASSWORD_PATH, status_code=303)


@app.exception_handler(RoleForbidden)
def _forbidden_page(request: Request, exc: RoleForbidden) -> Response:
    return templates.TemplateResponse(
        request, "forbidden.html", {"message": exc.detail}, status_code=403
    )


# Guards sit at router level: each router is one row of the Authorisation
# matrix (STORY-001), so a new route inherits its router's guard even if its
# author forgets. Only auth_router is public.
app.include_router(auth_router)
# Public on purpose: the login page needs the font too. Holds only the
# self-hosted Thai font (STORY-018); never put data or templates here.
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
app.include_router(requests_router, dependencies=[Depends(current_account)])
app.include_router(queue_router, dependencies=[Depends(require_role("procurement"))])
app.include_router(exports_router, dependencies=[Depends(require_role("procurement"))])
app.include_router(admin_router, dependencies=[Depends(require_role("administrator"))])
app.include_router(accounts_router, dependencies=[Depends(require_role("administrator"))])

# Who the client is, behind a proxy (STORY-006 ticket 06). Added last, so it is
# the outermost layer and everything inside sees the real client address. The
# start command passes --no-proxy-headers: this is the one place the header is
# read, and it is under test. "none" adds nothing: the peer is the client.
_trusted_proxies = settings.trusted_proxies()
if _trusted_proxies is not None:
    app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=_trusted_proxies)
