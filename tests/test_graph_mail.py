"""STORY-002 ticket 02: the Microsoft Graph sender, against a fake transport (no network)."""

import json
import logging
from urllib.parse import parse_qs

import httpx
import pytest
from pydantic import SecretStr

from app.services import mail
from app.services.graph_mail import (
    RETRY_AFTER_CAP_SECONDS,
    TOKEN_MARGIN_SECONDS,
    GraphMailSender,
    RateLimiter,
)
from app.services.mail import LogMailSender, MailError, MailMessage

SECRET = "s3cr3t-Value~xyz"
TOKEN = "eyJ0eXAi.fake-access-token"


class FakeTime:
    """Clock and sleep seam: sleeping moves the clock, nothing waits."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class FakeGraph:
    """Answers the token endpoint and sendMail; records every request."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.token_responses: list[httpx.Response] = []
        self.send_responses: list[httpx.Response] = []
        self.tokens_issued = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.host == "login.microsoftonline.com":
            if self.token_responses:
                return self.token_responses.pop(0)
            self.tokens_issued += 1
            return httpx.Response(200, json={"token_type": "Bearer", "expires_in": 3599,
                                             "access_token": f"{TOKEN}-{self.tokens_issued}"})
        if self.send_responses:
            return self.send_responses.pop(0)
        return httpx.Response(202)

    def sends(self) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.host == "graph.microsoft.com"]

    def token_requests(self) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.host == "login.microsoftonline.com"]


@pytest.fixture()
def graph():
    return FakeGraph()


@pytest.fixture()
def fake_time():
    return FakeTime()


def _sender(graph, fake_time, rate=25):
    return GraphMailSender("tenant-1", "client-1", SECRET, "item-portal@carabao.co.th",
                           rate_per_minute=rate,
                           client=httpx.Client(transport=httpx.MockTransport(graph)),
                           clock=fake_time.clock, sleep=fake_time.sleep)


def _message(**kw):
    base = dict(to=["somchai@apm.co.th"], subject="[Item Portal] รหัส 90001000001 สร้างใน AX แล้ว",
                html="<p>ใช้สั่งซื้อได้</p>", text="ใช้สั่งซื้อได้")
    base.update(kw)
    return MailMessage(**base)


def _failure(graph, fake_time, response, **kw) -> str:
    graph.send_responses = [response] * 3
    with pytest.raises(MailError) as e:
        _sender(graph, fake_time, **kw).send(_message())
    return str(e.value)


# --- Request shapes ---------------------------------------------------------------------------------

def test_token_request_is_client_credentials(graph, fake_time):
    _sender(graph, fake_time).send(_message())
    [token] = graph.token_requests()
    assert token.method == "POST"
    assert str(token.url) == "https://login.microsoftonline.com/tenant-1/oauth2/v2.0/token"
    assert token.headers["content-type"] == "application/x-www-form-urlencoded"
    form = {k: v[0] for k, v in parse_qs(token.content.decode()).items()}
    assert form == {"client_id": "client-1", "client_secret": SECRET,
                    "scope": "https://graph.microsoft.com/.default",
                    "grant_type": "client_credentials"}


def test_send_mail_request_matches_graph(graph, fake_time):
    _sender(graph, fake_time).send(_message(cc=["proc@carabao.co.th"],
                                            reply_to="procurement@carabao.co.th"))
    [send] = graph.sends()
    assert send.method == "POST"
    assert str(send.url) == ("https://graph.microsoft.com/v1.0/users/"
                             "item-portal@carabao.co.th/sendMail")
    assert send.headers["authorization"] == f"Bearer {TOKEN}-1"
    body = json.loads(send.content)
    assert body == {
        "message": {
            "subject": "[Item Portal] รหัส 90001000001 สร้างใน AX แล้ว",
            "body": {"contentType": "HTML", "content": "<p>ใช้สั่งซื้อได้</p>"},
            "toRecipients": [{"emailAddress": {"address": "somchai@apm.co.th"}}],
            "ccRecipients": [{"emailAddress": {"address": "proc@carabao.co.th"}}],
            "replyTo": [{"emailAddress": {"address": "procurement@carabao.co.th"}}],
        },
        "saveToSentItems": True,
    }


def test_no_cc_or_reply_to_leaves_them_out(graph, fake_time):
    _sender(graph, fake_time).send(_message())
    message = json.loads(graph.sends()[0].content)["message"]
    assert "ccRecipients" not in message and "replyTo" not in message


# --- Token cache ------------------------------------------------------------------------------------

def test_a_cached_token_is_reused(graph, fake_time):
    sender = _sender(graph, fake_time)
    sender.send(_message())
    fake_time.now += 3599 - TOKEN_MARGIN_SECONDS - 1
    sender.send(_message())
    assert len(graph.token_requests()) == 1
    assert {s.headers["authorization"] for s in graph.sends()} == {f"Bearer {TOKEN}-1"}


def test_an_expiring_token_is_refreshed(graph, fake_time):
    sender = _sender(graph, fake_time)
    sender.send(_message())
    fake_time.now += 3599 - TOKEN_MARGIN_SECONDS
    sender.send(_message())
    assert len(graph.token_requests()) == 2
    assert graph.sends()[1].headers["authorization"] == f"Bearer {TOKEN}-2"


def test_a_revoked_token_gets_one_fresh_try(graph, fake_time):
    graph.send_responses = [httpx.Response(401, json={"error": {"code": "InvalidAuthenticationToken"}})]
    _sender(graph, fake_time).send(_message())
    assert len(graph.token_requests()) == 2 and len(graph.sends()) == 2
    assert graph.sends()[1].headers["authorization"] == f"Bearer {TOKEN}-2"


# --- Errors -----------------------------------------------------------------------------------------

def test_401_403_and_5xx_become_mail_errors_naming_the_status(graph, fake_time):
    reason = _failure(graph, fake_time, httpx.Response(
        401, json={"error": {"code": "InvalidAuthenticationToken", "message": "x"}}))
    assert "HTTP 401" in reason and "InvalidAuthenticationToken" in reason
    reason = _failure(FakeGraph(), fake_time, httpx.Response(
        403, json={"error": {"code": "ErrorAccessDenied", "message": "Access is denied."}}))
    assert "HTTP 403" in reason and "Application Access Policy" in reason
    reason = _failure(FakeGraph(), fake_time, httpx.Response(503, text="<html>down</html>"))
    assert "HTTP 503" in reason and "<html>" not in reason
    reason = _failure(FakeGraph(), fake_time, httpx.Response(
        400, json={"error": {"code": "ErrorInvalidRecipients", "message": "bad"}}))
    assert "HTTP 400, ErrorInvalidRecipients" in reason


def test_429_waits_the_retry_after_then_retries_once(graph, fake_time):
    graph.send_responses = [httpx.Response(429, headers={"Retry-After": "4"})]
    _sender(graph, fake_time).send(_message())
    assert fake_time.sleeps == [4.0] and len(graph.sends()) == 2


def test_429_twice_fails_after_one_wait(graph, fake_time):
    reason = _failure(graph, fake_time, httpx.Response(429, headers={"Retry-After": "2"}))
    assert "HTTP 429" in reason and fake_time.sleeps == [2.0] and len(graph.sends()) == 2


def test_429_asking_longer_than_the_cap_fails_without_waiting(graph, fake_time):
    reason = _failure(graph, fake_time, httpx.Response(
        429, headers={"Retry-After": str(RETRY_AFTER_CAP_SECONDS + 1)}))
    assert "HTTP 429" in reason and fake_time.sleeps == [] and len(graph.sends()) == 1


def test_a_timeout_becomes_a_mail_error_that_warns_of_a_copy(fake_time):
    def slow(request):
        if request.url.host == "login.microsoftonline.com":
            return httpx.Response(200, json={"access_token": TOKEN, "expires_in": 3599})
        raise httpx.ReadTimeout("timed out", request=request)

    sender = GraphMailSender("t", "c", SECRET, "item-portal@carabao.co.th",
                             client=httpx.Client(transport=httpx.MockTransport(slow)),
                             clock=fake_time.clock, sleep=fake_time.sleep)
    with pytest.raises(MailError, match="timeout") as e:
        sender.send(_message())
    assert "อาจส่งไปแล้ว" in str(e.value)


def test_a_rejected_secret_says_check_the_client_secret(graph, fake_time):
    graph.token_responses = [httpx.Response(401, json={
        "error": "invalid_client",
        "error_description": f"AADSTS7000215: Invalid client secret provided. {SECRET}",
    })]
    with pytest.raises(MailError) as e:
        _sender(graph, fake_time).send(_message())
    reason = str(e.value)
    assert "HTTP 401, invalid_client, AADSTS7000215" in reason
    assert "MS_CLIENT_SECRET" in reason and "หมดอายุ" in reason and "expired" in reason
    assert graph.sends() == []


def test_a_400_from_the_token_endpoint_also_says_check_the_secret(graph, fake_time):
    graph.token_responses = [httpx.Response(400, json={"error": "invalid_request"})]
    with pytest.raises(MailError, match="MS_CLIENT_SECRET"):
        _sender(graph, fake_time).send(_message())


def test_a_token_endpoint_outage_is_not_blamed_on_the_secret(graph, fake_time):
    graph.token_responses = [httpx.Response(503)]
    with pytest.raises(MailError) as e:
        _sender(graph, fake_time).send(_message())
    assert "HTTP 503" in str(e.value) and "MS_CLIENT_SECRET" not in str(e.value)


def test_secrets_never_reach_errors_or_logs(graph, fake_time, caplog):
    caplog.set_level(logging.DEBUG)
    sender = _sender(graph, fake_time)
    sender.send(_message())
    graph.send_responses = [httpx.Response(403, json={"error": {
        "code": "ErrorAccessDenied", "message": f"token {TOKEN}-1 secret {SECRET}"}})]
    with pytest.raises(MailError) as e:
        sender.send(_message())
    graph.token_responses = [httpx.Response(401, json={
        "error": "invalid_client", "error_description": f"bad {SECRET}"})]
    fake_time.now += 4000  # force a new token request
    with pytest.raises(MailError) as e2:
        sender.send(_message())
    sender.send(_message())  # a good token is cached again
    for text in (str(e.value), str(e2.value), caplog.text, repr(sender), repr(sender._token)):
        assert SECRET not in text and TOKEN not in text
    assert "ใช้สั่งซื้อได้" not in caplog.text  # body never logged


# --- Rate limit -------------------------------------------------------------------------------------

def test_the_limiter_never_lets_more_than_n_sends_start_in_a_minute(fake_time):
    limiter = RateLimiter(3, fake_time.clock, fake_time.sleep)
    starts = []
    for i in range(10):
        fake_time.now += 5 if i % 4 == 0 else 0.5
        limiter.acquire()
        starts.append(fake_time.now)
    for t in starts:
        assert sum(1 for s in starts if t <= s < t + 60) <= 3
    assert fake_time.sleeps  # it had to wait, without really sleeping


def test_the_sender_goes_through_the_limiter(graph, fake_time):
    sender = _sender(graph, fake_time, rate=2)
    for _ in range(3):
        sender.send(_message())
    assert fake_time.sleeps == [60.0]


def test_a_rate_below_one_is_refused():
    with pytest.raises(ValueError):
        RateLimiter(0)


# --- Choosing the sender (AC2) ---------------------------------------------------------------------

@pytest.fixture()
def graph_settings(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(mail, "_graph", None)
    values = {"ms_tenant_id": "tenant-1", "ms_client_id": "client-1",
              "ms_client_secret": SecretStr(SECRET), "mail_sender": "item-portal@carabao.co.th"}
    for name, value in values.items():
        monkeypatch.setattr(settings, name, value)
    return settings


def test_all_four_settings_give_one_graph_sender_per_process(graph_settings):
    first = mail.get_mail_sender()
    assert isinstance(first, GraphMailSender) and mail.get_mail_sender() is first


@pytest.mark.parametrize("name", ["ms_tenant_id", "ms_client_id", "ms_client_secret",
                                  "mail_sender"])
def test_any_missing_setting_gives_the_log_sender(graph_settings, monkeypatch, caplog, name):
    monkeypatch.setattr(graph_settings, name,
                        SecretStr("") if name == "ms_client_secret" else "  ")
    with caplog.at_level(logging.WARNING, logger="app.mail"):
        assert isinstance(mail.get_mail_sender(), LogMailSender)
    assert name.upper() in caplog.text and SECRET not in caplog.text


def test_no_settings_at_all_is_quietly_the_log_sender(graph_settings, monkeypatch, caplog):
    for name in ("ms_tenant_id", "ms_client_id", "mail_sender"):
        monkeypatch.setattr(graph_settings, name, "")
    monkeypatch.setattr(graph_settings, "ms_client_secret", SecretStr(""))
    with caplog.at_level(logging.WARNING, logger="app.mail"):
        assert isinstance(mail.get_mail_sender(), LogMailSender)
    assert caplog.text == ""


def test_the_secret_does_not_show_in_settings_repr(graph_settings):
    assert SECRET not in repr(graph_settings)


# --- Code review fixes ----------------------------------------------------------------------------

def test_wait_for_slot_waits_without_taking_the_slot(fake_time):
    limiter = RateLimiter(1, fake_time.clock, fake_time.sleep)
    limiter.acquire()
    limiter.wait_for_slot()
    assert fake_time.sleeps == [60.0]
    limiter.wait_for_slot()  # nothing taken: still free
    limiter.acquire()  # and the send itself does not wait again
    assert fake_time.sleeps == [60.0]


def test_the_notifier_waits_for_the_limiter_before_locking_rows(app_db, monkeypatch):
    """The rate-limit wait must not happen while the request row is locked."""
    from sqlalchemy.orm import sessionmaker

    from app.services import notify
    from app.services.notify import latest_status_event, notify_status
    from app.services.requests import change_status, submit_request
    from tests.conftest import account_for, central_ids

    factory, system, group, sub = central_ids(app_db)
    req = submit_request(app_db, account_for(app_db, "requester", plant="APM"),
                         factory_id=factory.id, code_system_id=system.id, group_id=group.id,
                         subgroup_id=sub.id, item_name="Ball Bearing")
    change_status(app_db, req.id, new_status="needs_info", note="?",
                  account=account_for(app_db, "administrator"))
    order: list[str] = []
    real_claim = notify._claim

    def claim(*args):
        order.append("claim")
        return real_claim(*args)

    class Limited:
        def wait_for_slot(self):
            order.append("wait")

        def send(self, message):
            order.append("send")

    monkeypatch.setattr(notify, "_claim", claim)
    change = latest_status_event(app_db, req.id)
    notify_status(sessionmaker(bind=app_db.get_bind(), expire_on_commit=False), req.id,
                  change.id, Limited(), "a@test.local")
    assert order == ["wait", "claim", "send"]


def test_the_created_notifier_also_waits_before_locking(app_db, monkeypatch):
    from sqlalchemy.orm import sessionmaker

    from app.services import notify
    from app.services.exporter import export_pending
    from app.services.notify import notify_created
    from app.services.requests import change_status, submit_request
    from tests.conftest import account_for, central_ids

    factory, system, group, sub = central_ids(app_db)
    admin = account_for(app_db, "administrator")
    req = submit_request(app_db, account_for(app_db, "requester", plant="APM"),
                         factory_id=factory.id, code_system_id=system.id, group_id=group.id,
                         subgroup_id=sub.id, item_name="Ball Bearing", uom="EA")
    change_status(app_db, req.id, new_status="approved", account=admin)
    export_pending(app_db, factory.id, account=account_for(app_db))
    change_status(app_db, req.id, new_status="created", account=admin)
    order: list[str] = []
    real_claim = notify._claim

    def claim(*args):
        order.append("claim")
        return real_claim(*args)

    class Limited:
        def wait_for_slot(self):
            order.append("wait")

        def send(self, message):
            order.append("send")

    monkeypatch.setattr(notify, "_claim", claim)
    notify_created(sessionmaker(bind=app_db.get_bind(), expire_on_commit=False), [req.id],
                   Limited(), "a@test.local")
    assert order == ["wait", "claim", "send"]


def test_a_bad_rate_setting_stops_the_app_at_start(monkeypatch):
    from pydantic import ValidationError

    from app.config import Settings

    monkeypatch.setenv("MAIL_RATE_PER_MINUTE", "0")
    with pytest.raises(ValidationError):
        Settings()
