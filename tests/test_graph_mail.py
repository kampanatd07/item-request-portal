"""STORY-002 ticket 02: the Microsoft Graph sender, against a fake transport (no network)."""

import json
import logging
from urllib.parse import parse_qs

import httpx
import pytest
from pydantic import SecretStr

from app.services import mail
from app.services.graph_mail import (
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


def test_a_revoked_token_fails_now_and_the_next_send_gets_a_fresh_one(graph, fake_time):
    # Review 2026-10-14: no retry while the notifier holds the row lock.
    sender = _sender(graph, fake_time)
    sender.prepare()
    graph.send_responses = [httpx.Response(401, json={"error": {"code": "InvalidAuthenticationToken"}})]
    with pytest.raises(MailError, match="HTTP 401"):
        sender.send(_message())
    assert len(graph.token_requests()) == 1 and len(graph.sends()) == 1
    sender.prepare()  # before the next claim: a new token
    sender.send(_message())
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


def test_429_and_5xx_fail_at_once_without_waiting_or_retrying(graph, fake_time):
    # Review 2026-10-14: a Retry-After sleep and a re-post held the row lock;
    # now the failure goes to notify_failed and the resend list does the retry.
    reason = _failure(graph, fake_time, httpx.Response(429, headers={"Retry-After": "4"}))
    assert "HTTP 429" in reason and fake_time.sleeps == [] and len(graph.sends()) == 1
    graph = FakeGraph()
    reason = _failure(graph, fake_time, httpx.Response(503))
    assert "HTTP 503" in reason and fake_time.sleeps == [] and len(graph.sends()) == 1


def test_sendmail_uses_the_short_timeout(graph, fake_time):
    _sender(graph, fake_time).send(_message())
    [send], [token] = graph.sends(), graph.token_requests()
    assert send.extensions["timeout"] == {"connect": 5.0, "read": 10.0, "write": 10.0,
                                          "pool": 10.0}
    assert token.extensions["timeout"]["read"] == 15.0  # before the lock: may take longer


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

def test_sends_are_spaced_by_60_over_the_rate(fake_time: FakeTime) -> None:
    # Spacing limiter (Peter, 2026-10-15): one send every 60/rate seconds.
    limiter = RateLimiter(25, fake_time.clock, fake_time.sleep)
    starts = [limiter.wait() for _ in range(4)]
    gaps = [b - a for a, b in zip(starts, starts[1:])]
    assert gaps == [pytest.approx(60 / 25)] * 3 and len(fake_time.sleeps) == 3


def test_concurrent_waits_get_starts_at_least_an_interval_apart() -> None:
    # Review 2026-10-15: wait() only read the next start, so threads calling
    # prepare() together all passed at once. Each wait() now books its start.
    import threading

    lock, clock = threading.Lock(), [1000.0]

    def now() -> float:
        with lock:
            return clock[0]

    def sleep(seconds: float) -> None:  # fake: moves the shared clock, no real wait
        with lock:
            clock[0] += seconds

    limiter = RateLimiter(25, now, sleep)
    gate, starts = threading.Barrier(8), []

    def notifier() -> None:
        gate.wait()
        starts.append(limiter.wait())

    threads = [threading.Thread(target=notifier) for _ in range(8)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    starts.sort()
    assert len(starts) == 8
    assert all(b - a >= limiter.interval - 1e-9 for a, b in zip(starts, starts[1:]))


def test_send_never_waits_never_fails_and_books_nothing(graph: FakeGraph,
                                                        fake_time: FakeTime) -> None:
    # send() runs under the row lock: it neither sleeps nor refuses, and the
    # spacing is booked by prepare() alone.
    sender = _sender(graph, fake_time, rate=1)
    for _ in range(3):
        sender.send(_message())  # back to back, no prepare in between
    assert fake_time.sleeps == [] and len(graph.sends()) == 3
    sender.prepare()
    assert fake_time.sleeps == []  # the sends booked no time
    sender.prepare()  # the second booking waits for the first
    assert fake_time.sleeps == [60.0]


def test_the_wait_holds_no_lock_while_sleeping(fake_time: FakeTime) -> None:
    limiter = RateLimiter(1, fake_time.clock, fake_time.sleep)
    held: list[bool] = []
    real_sleep = fake_time.sleep

    def sleep(seconds: float) -> None:
        held.append(limiter._lock.locked())
        real_sleep(seconds)

    limiter._sleep = sleep
    limiter.wait()
    limiter.wait()
    assert held == [False]


def test_a_429_during_a_wait_pushes_that_wait_later_without_failing_it(
        fake_time: FakeTime) -> None:
    # A send waiting in prepare() while another thread gets a 429: it waits on.
    limiter = RateLimiter(60, fake_time.clock, fake_time.sleep)  # 1 s apart
    limiter.wait()
    real_sleep = fake_time.sleep
    backed_off = False

    def sleep(seconds: float) -> None:
        nonlocal backed_off
        real_sleep(seconds)
        if not backed_off:
            backed_off = True
            limiter.back_off(30)  # another thread's 429, mid-wait

    limiter._sleep = sleep
    start = fake_time.now
    limiter.wait()  # no exception
    assert fake_time.now - start == pytest.approx(31.0)


@pytest.mark.parametrize("value", ["nan", "inf", "-inf"])
def test_a_non_finite_retry_after_backs_off_one_second(graph: FakeGraph, fake_time: FakeTime,
                                                       value: str) -> None:
    # Review 2026-10-15: "nan" turned the back-off into no back-off at all.
    sender = _sender(graph, fake_time)
    graph.send_responses = [httpx.Response(429, headers={"Retry-After": value})]
    with pytest.raises(MailError, match="HTTP 429"):
        sender.send(_message())
    sender.prepare()
    assert fake_time.sleeps == [1.0]


def test_a_retry_after_date_without_a_zone_is_read_as_utc(graph: FakeGraph, fake_time: FakeTime,
                                                          monkeypatch: pytest.MonkeyPatch) -> None:
    # Review 2026-10-15: "-0000" gave a naive datetime and fell back to 1 s.
    from datetime import datetime, timedelta, timezone

    from app.services import graph_mail

    now = datetime(2026, 10, 21, 7, 28, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(graph_mail, "_utc_now", lambda: now)
    later = (now + timedelta(seconds=30)).strftime("%a, %d %b %Y %H:%M:%S -0000")
    sender = _sender(graph, fake_time)
    graph.send_responses = [httpx.Response(429, headers={"Retry-After": later})]
    with pytest.raises(MailError, match="HTTP 429"):
        sender.send(_message())
    sender.prepare()
    assert fake_time.sleeps == [pytest.approx(30.0)]


def test_retry_after_as_an_http_date_is_honoured(graph, fake_time, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from email.utils import format_datetime

    from app.services import graph_mail

    now = datetime.now(timezone.utc)
    monkeypatch.setattr(graph_mail, "_utc_now", lambda: now)
    sender = _sender(graph, fake_time)
    graph.send_responses = [httpx.Response(429, headers={
        "Retry-After": format_datetime(now + timedelta(seconds=20), usegmt=True)})]
    with pytest.raises(MailError, match="HTTP 429"):
        sender.send(_message())
    sender.prepare()
    assert fake_time.sleeps == [pytest.approx(20.0, abs=1.0)]


def test_a_successful_send_is_logged(graph, fake_time, caplog):
    # Review 2026-10-14 round 4: the log line had become unreachable.
    with caplog.at_level(logging.INFO, logger="app.mail"):
        _sender(graph, fake_time).send(_message(cc=["proc@carabao.co.th"]))
    assert ("mail sent via Graph to=somchai@apm.co.th cc=proc@carabao.co.th "
            "subject=[Item Portal] รหัส 90001000001") in caplog.text


def test_a_429_makes_the_next_prepare_wait_the_retry_after(graph, fake_time):
    # Review of 2026-10-14 round 3: with the retry gone, a 429 was honoured
    # nowhere, so "send all" burned every remaining group into notify_failed.
    sender = _sender(graph, fake_time)
    graph.send_responses = [httpx.Response(429, headers={"Retry-After": "30"})]
    sender.prepare()
    with pytest.raises(MailError, match="HTTP 429"):
        sender.send(_message())
    sender.prepare()  # outside the lock: wait out what Graph asked
    assert fake_time.sleeps == [30.0]
    sender.send(_message())
    assert len(graph.sends()) == 2


def test_a_huge_retry_after_is_capped(graph, fake_time):
    from app.services.graph_mail import BACK_OFF_CAP_SECONDS

    sender = _sender(graph, fake_time)
    graph.send_responses = [httpx.Response(429, headers={"Retry-After": "3600"})]
    with pytest.raises(MailError):
        sender.send(_message())
    sender.prepare()
    assert fake_time.sleeps == [float(BACK_OFF_CAP_SECONDS)]


def test_prepare_fetches_the_token_before_the_claim(graph, fake_time):
    sender = _sender(graph, fake_time)
    sender.prepare()
    assert len(graph.token_requests()) == 1 and graph.sends() == []
    sender.send(_message())
    assert len(graph.token_requests()) == 1  # nothing fetched under the lock


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
def test_any_missing_setting_gives_the_log_sender(graph_settings, monkeypatch, name):
    monkeypatch.setattr(graph_settings, name,
                        SecretStr("") if name == "ms_client_secret" else "  ")
    assert isinstance(mail.get_mail_sender(), LogMailSender)


def test_no_settings_at_all_is_quietly_the_log_sender(graph_settings, monkeypatch, caplog):
    for name in ("ms_tenant_id", "ms_client_id", "mail_sender"):
        monkeypatch.setattr(graph_settings, name, "")
    monkeypatch.setattr(graph_settings, "ms_client_secret", SecretStr(""))
    with caplog.at_level(logging.WARNING, logger="app.mail"):
        assert isinstance(mail.get_mail_sender(), LogMailSender)
    assert caplog.text == ""


GRAPH_ENV = {"ms_tenant_id": "tenant-1", "ms_client_id": "client-1",
             "ms_client_secret": SECRET, "mail_sender": "item-portal@carabao.co.th"}


@pytest.mark.parametrize("missing", [None, "ms_tenant_id", "ms_client_id",
                                     "ms_client_secret", "mail_sender"])
def test_outside_dev_the_app_refuses_to_start_without_all_graph_settings(missing):
    # Review 2026-10-14: production fell back to the log sender and marked
    # every request notified with no email sent.
    from pydantic import ValidationError

    from app.config import Settings

    values = {k: v for k, v in GRAPH_ENV.items() if k != missing}
    if missing is None:
        Settings(_env_file=None, app_env="production", secret_key="x" * 40, **values)
        return
    with pytest.raises(ValidationError, match=missing.upper()):
        Settings(_env_file=None, app_env="production", secret_key="x" * 40, **values)


def test_dev_without_graph_settings_starts_with_the_log_sender():
    from app.config import Settings

    Settings(_env_file=None, app_env="dev")  # no error


def test_a_half_configured_dev_warns_once_at_start_not_per_request(graph_settings, monkeypatch,
                                                                   caplog):
    from app.config import Settings

    with caplog.at_level(logging.WARNING, logger="app.mail"):
        Settings(_env_file=None, app_env="dev", ms_tenant_id="tenant-1")
    assert "MS_CLIENT_ID" in caplog.text
    caplog.clear()
    monkeypatch.setattr(graph_settings, "mail_sender", "")
    with caplog.at_level(logging.WARNING, logger="app.mail"):
        for _ in range(3):
            assert isinstance(mail.get_mail_sender(), LogMailSender)
    assert caplog.text == ""


def test_the_secret_does_not_show_in_settings_repr(graph_settings):
    assert SECRET not in repr(graph_settings)


# --- Code review fixes ----------------------------------------------------------------------------

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
        def prepare(self):
            order.append("prepare")

        def send(self, message):
            order.append("send")

    monkeypatch.setattr(notify, "_claim", claim)
    change = latest_status_event(app_db, req.id)
    notify_status(sessionmaker(bind=app_db.get_bind(), expire_on_commit=False), req.id,
                  change.id, Limited(), "a@test.local")
    assert order == ["prepare", "claim", "send"]


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
        def prepare(self):
            order.append("prepare")

        def send(self, message):
            order.append("send")

    monkeypatch.setattr(notify, "_claim", claim)
    notify_created(sessionmaker(bind=app_db.get_bind(), expire_on_commit=False), [req.id],
                   Limited(), "a@test.local")
    assert order == ["prepare", "claim", "send"]


def test_a_bad_rate_setting_stops_the_app_at_start(monkeypatch):
    from pydantic import ValidationError

    from app.config import Settings

    monkeypatch.setenv("MAIL_RATE_PER_MINUTE", "0")
    with pytest.raises(ValidationError):
        Settings()


# --- AC10 end to end: a Graph error through the notifier to notify_failed ---------------------

def _graph_app(graph, fake_time):
    """The app's mail dependency → a real GraphMailSender on the fake transport."""
    from app.main import app

    app.dependency_overrides[mail.get_mail_sender] = lambda: _sender(graph, fake_time)


def _failures(db, req):
    from sqlalchemy import select

    from app.models import RequestEvent

    db.expire_all()
    return list(db.scalars(select(RequestEvent.detail).where(
        RequestEvent.request_id == req.id, RequestEvent.action == "notify_failed")))


def _submitted(db):
    from app.services.requests import submit_request
    from tests.conftest import account_for, central_ids

    factory, system, group, sub = central_ids(db)
    return submit_request(db, account_for(db, "requester", plant="APM"), factory_id=factory.id,
                          code_system_id=system.id, group_id=group.id, subgroup_id=sub.id,
                          item_name="Ball Bearing", uom="EA")


def test_graph_throttling_on_mark_created_becomes_notify_failed(client, app_db, graph, fake_time):
    from app.models import ItemRequest
    from app.services.exporter import export_pending
    from app.services.requests import change_status
    from tests.conftest import account_for

    req = _submitted(app_db)
    change_status(app_db, req.id, new_status="approved", account=account_for(app_db, "administrator"))
    batch = export_pending(app_db, req.factory_id, account=account_for(app_db))
    _graph_app(graph, fake_time)
    graph.send_responses = [httpx.Response(429, headers={"Retry-After": "2"})] * 3

    assert client.post(f"/exports/{batch.id}/mark-created").status_code == 200
    [detail] = _failures(app_db, req)
    assert "HTTP 429" in detail
    assert SECRET not in detail and TOKEN not in detail
    assert app_db.get(ItemRequest, req.id).status == "created"  # left for resend
    assert len(graph.sends()) == 1 and fake_time.sleeps == []


def test_graph_server_error_on_needs_info_becomes_notify_failed(client, app_db, graph, fake_time):
    from app.models import ItemRequest

    req = _submitted(app_db)
    _graph_app(graph, fake_time)
    graph.send_responses = [httpx.Response(500, json={"error": {
        "code": "ErrorInternalServerError", "message": f"boom {SECRET}"}})] * 3

    r = client.post(f"/queue/{req.id}/status", data={"new_status": "needs_info", "note": "ขอสเปค"})
    assert r.status_code == 200
    [detail] = _failures(app_db, req)
    assert detail.startswith("needs_info:") and "HTTP 500" in detail
    assert SECRET not in detail and TOKEN not in detail and "boom" not in detail
    assert app_db.get(ItemRequest, req.id).status == "needs_info"  # the change stands
