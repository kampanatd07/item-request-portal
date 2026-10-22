"""Client IP behind a proxy, and FORWARDED_ALLOW_IPS required outside dev
(STORY-006 ticket 06). The login limit per IP (ticket 07) counts this IP, so a
forged X-Forwarded-For must never change it."""

from pathlib import Path

import pytest
from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.config import Settings

PRODUCTION = dict(_env_file=None, app_env="production", secret_key="x" * 40,
                  ms_tenant_id="t", ms_client_id="c", ms_client_secret="s",
                  mail_sender="item-portal@carabao.co.th")


def _settings(value: str, **kw: object) -> Settings:
    return Settings(**{**PRODUCTION, **kw, "forwarded_allow_ips": value})


def _client_ip_seen(value: str, peer: str, forwarded_for: str | None) -> str:
    """The client address the app sees, configured as app/main.py does."""
    async def echo(request: Request) -> PlainTextResponse:
        return PlainTextResponse(request.client.host)

    app = Starlette(routes=[Route("/", echo)])
    proxies = _settings(value).trusted_proxies()
    if proxies is not None:
        app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=proxies)
    headers = {"X-Forwarded-For": forwarded_for} if forwarded_for else {}
    with TestClient(app, client=(peer, 50000)) as c:
        return c.get("/", headers=headers).text


# --- who the client is ---------------------------------------------------------------

def test_header_from_a_trusted_proxy_gives_the_client():
    assert _client_ip_seen("10.0.0.5", "10.0.0.5", "203.0.113.7") == "203.0.113.7"


def test_header_from_an_untrusted_peer_is_ignored():
    assert _client_ip_seen("10.0.0.5", "198.51.100.9", "203.0.113.7") == "198.51.100.9"


def test_none_ignores_the_header_from_every_peer():
    assert _client_ip_seen("none", "10.0.0.5", "203.0.113.7") == "10.0.0.5"


def test_a_cidr_range_is_trusted():
    assert _client_ip_seen("10.0.0.0/8", "10.20.30.40", "203.0.113.7") == "203.0.113.7"


def test_a_forged_entry_in_front_does_not_win():
    # The client sends its own X-Forwarded-For; the trusted proxy appends the
    # real address. The rightmost entry that is not a trusted proxy counts.
    assert _client_ip_seen("10.0.0.5", "10.0.0.5", "1.2.3.4, 203.0.113.7") == "203.0.113.7"


@pytest.mark.parametrize("value, expected", [
    ("10.0.0.0/8, 192.0.2.1", "['10.0.0.0/8', '192.0.2.1'] True"),
    ("none", "None False"),
])
def test_the_real_app_reads_the_header_from_the_configured_proxies(value, expected):
    # main.py decides at import time, so import it fresh in a clean process.
    import os
    import subprocess
    import sys

    env = {**os.environ, "APP_ENV": "dev", "FORWARDED_ALLOW_IPS": value}
    out = subprocess.run(
        [sys.executable, "-c",
         "from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware as P; "
         "import app.main as m; "
         "found = [x for x in m.app.user_middleware if x.cls is P]; "
         "print(found[0].kwargs['trusted_hosts'] if found else None,"
         " bool(found) and m.app.user_middleware[0] is found[0])"],
        capture_output=True, text=True, env=env, check=True,
    ).stdout.strip()
    assert out == expected  # the configured list, as the outermost layer; nothing for none


# --- the start-up rule -----------------------------------------------------------------

def test_outside_dev_an_empty_value_refuses_to_start():
    with pytest.raises(ValidationError, match="FORWARDED_ALLOW_IPS must be set") as e:
        _settings("")
    assert "CIDR" in str(e.value) and "'none'" in str(e.value)


@pytest.mark.parametrize("app_env", ["production", "dev"])
@pytest.mark.parametrize("value", ["*", "10.0.0.5, *"])
def test_a_star_refuses_to_start_everywhere_and_says_why(app_env, value):
    with pytest.raises(ValidationError, match=r"must not contain '\*'.*leftmost"):
        _settings(value, app_env=app_env)


@pytest.mark.parametrize("value", ["10.0.0.300", "proxy.example.com", "10.0.0.1/8",
                                   "10.0.0.5,", "none, 10.0.0.5"])
def test_a_value_that_is_not_an_ip_or_cidr_refuses_to_start(value):
    with pytest.raises(ValidationError, match="FORWARDED_ALLOW_IPS: .* is not an IP"):
        _settings(value)


@pytest.mark.parametrize("value, proxies", [
    ("none", None), ("NONE", None), ("10.0.0.5", ["10.0.0.5"]),
    ("10.0.0.5, 10.1.0.0/16, ::1", ["10.0.0.5", "10.1.0.0/16", "::1"]),
])
def test_accepted_values(value, proxies):
    assert _settings(value).trusted_proxies() == proxies


def test_in_dev_an_empty_value_means_localhost():
    assert _settings("", app_env="dev").trusted_proxies() == ["127.0.0.1"]


# --- one worker (AC 7) -----------------------------------------------------------------

def test_the_container_runs_one_worker_and_leaves_the_header_to_the_app():
    dockerfile = (Path(__file__).parent.parent / "Dockerfile").read_text(encoding="utf-8")
    cmd = next(line for line in dockerfile.splitlines() if line.startswith("CMD"))
    assert "uvicorn app.main:app" in cmd
    assert "--workers 1" in cmd and "--no-proxy-headers" in cmd
