"""The real sender: Microsoft Graph `sendMail` with client credentials (STORY-002 ticket 02).

One instance per process (see `mail.get_mail_sender`), so the app token and
the rate limiter are shared by every send in that process. Every failure is a
`MailError` with a short reason that ends up in a notify_failed event and on
the resend list — so it names the HTTP status and Graph's error code, never
the client secret, the token or the email body.
"""

import logging
import math
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx

from app.services.mail import MailError, MailMessage

log = logging.getLogger("app.mail")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)

TOKEN_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
SEND_URL = "https://graph.microsoft.com/v1.0/users/{sender}/sendMail"
SCOPE = "https://graph.microsoft.com/.default"

# A token is renewed this long before Graph says it expires, so a send never
# starts with a token that runs out on the way.
TOKEN_MARGIN_SECONDS = 300
# Token requests run in prepare(), before any row lock: they may take longer.
TIMEOUT = httpx.Timeout(15.0, connect=5.0)
# sendMail runs while the notifier holds the request rows: one short try,
# no retry and no Retry-After wait; a failure goes on the resend list.
SEND_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
# A 429's Retry-After holds back the next sends (in prepare, outside any
# lock) for at most this long; past it they try again and may fail again.
BACK_OFF_CAP_SECONDS = 60

BAD_CREDENTIALS = ("Graph: ใช้ credentials ไม่ได้ ({detail}) — client secret อาจหมดอายุ "
                   "ตรวจ MS_CLIENT_SECRET / Graph credentials do not work, the client "
                   "secret may have expired — check MS_CLIENT_SECRET")

Clock = Callable[[], float]
Sleep = Callable[[float], None]


class RateLimiter:
    """Spaces sends at least 60/`per_minute` seconds apart (Peter, 2026-10-15).

    One value, `_next_at`: when the next send may start. `wait` (called in
    `prepare`, after the token and before any row is locked) books a start:
    when `_next_at` has come it moves it one interval on and returns, in one
    short critical section, so concurrent bookings are at least an interval
    apart (the bookings, not the POSTs: a claim wait in between can bunch
    POSTs; see decisions.md 2026-10-15);
    otherwise it sleeps *outside* the lock and checks again. `back_off` (a
    429's Retry-After) moves `_next_at` later, which also lengthens a wait
    already running. The lock is only held to read or write `_next_at`. The
    limiter never fails a send and `send` books nothing (a split "created"
    group's extra parts go out unspaced; rare). One app worker; several
    workers would each space their own sends.
    """

    def __init__(self, per_minute: int, clock: Clock = time.monotonic,
                 sleep: Sleep = time.sleep) -> None:
        if per_minute < 1:
            raise ValueError("MAIL_RATE_PER_MINUTE must be at least 1")
        self.interval = 60.0 / per_minute
        self._clock, self._sleep = clock, sleep
        self._next_at = float("-inf")
        self._lock = threading.Lock()

    def wait(self) -> float:
        """Book the next send start, sleeping (lock released) until it comes;
        returns the booked start on the limiter's clock. Re-checks after each
        sleep, so a 429 seen meanwhile makes it wait longer, never fail."""
        while True:
            with self._lock:
                now = self._clock()
                delay = self._next_at - now
                if delay <= 0:
                    self._next_at = now + self.interval
                    return now
            self._sleep(delay)

    def back_off(self, seconds: float) -> None:
        """Graph throttled us: no send for this long (capped)."""
        delay = min(max(seconds, 0.0), BACK_OFF_CAP_SECONDS)
        with self._lock:
            self._next_at = max(self._next_at, self._clock() + delay)


@dataclass
class _Token:
    value: str
    expires_at: float  # on the sender's clock

    def __repr__(self) -> str:  # never print the token itself
        return f"_Token(expires_at={self.expires_at})"


def _graph_error_code(response: httpx.Response) -> str | None:
    """Graph's error code (e.g. ErrorInvalidRecipients), never its free text."""
    try:
        code = response.json().get("error", {}).get("code")
    except Exception:  # noqa: BLE001 - not JSON
        return None
    return code if isinstance(code, str) and re.fullmatch(r"[A-Za-z0-9_.]{1,80}", code) else None


def _token_error_detail(response: httpx.Response) -> str:
    """HTTP status, OAuth error code and the AADSTS number, e.g.
    'HTTP 401, invalid_client, AADSTS7000215' — enough to look up, nothing secret."""
    parts = [f"HTTP {response.status_code}"]
    try:
        body = response.json()
    except Exception:  # noqa: BLE001 - not JSON
        body = {}
    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, str) and re.fullmatch(r"[a-z_]{1,50}", error):
        parts.append(error)
    description = body.get("error_description") if isinstance(body, dict) else None
    if isinstance(description, str):
        match = re.search(r"AADSTS\d{4,8}", description)
        if match:
            parts.append(match.group(0))
    return ", ".join(parts)


def _recipients(addresses: list[str]) -> list[dict]:
    return [{"emailAddress": {"address": a}} for a in addresses]


class GraphMailSender:
    def __init__(self, tenant_id: str, client_id: str, client_secret: str, sender: str,
                 rate_per_minute: int = 25, client: httpx.Client | None = None,
                 clock: Clock = time.monotonic, sleep: Sleep = time.sleep) -> None:
        self._tenant_id, self._client_id = tenant_id, client_id
        self._client_secret = client_secret
        self.sender = sender
        self._client = client or httpx.Client(timeout=TIMEOUT)
        self._clock = clock
        self.limiter = RateLimiter(rate_per_minute, clock, sleep)
        self._token: _Token | None = None
        self._token_lock = threading.Lock()

    # --- token --------------------------------------------------------------

    def _access_token(self) -> str:
        with self._token_lock:
            if self._token is None or self._clock() >= self._token.expires_at - TOKEN_MARGIN_SECONDS:
                self._token = self._fetch_token()
            return self._token.value

    def _fetch_token(self) -> _Token:
        try:
            response = self._client.post(
                TOKEN_URL.format(tenant=self._tenant_id), timeout=TIMEOUT,
                data={"client_id": self._client_id, "client_secret": self._client_secret,
                      "scope": SCOPE, "grant_type": "client_credentials"})
        except httpx.TimeoutException:
            raise MailError("Graph: ขอ token ไม่ทันเวลา (timeout) — ส่งอีกครั้งได้") from None
        except httpx.HTTPError as e:
            raise MailError(f"Graph: ติดต่อระบบ login ของ Microsoft ไม่ได้ "
                            f"({type(e).__name__})") from None
        if response.status_code in (400, 401):
            raise MailError(BAD_CREDENTIALS.format(detail=_token_error_detail(response)))
        if response.status_code != 200:
            raise MailError(f"Graph: ขอ token ไม่สำเร็จ ({_token_error_detail(response)})")
        try:
            body = response.json()
            value, expires_in = body["access_token"], float(body["expires_in"])
        except Exception:  # noqa: BLE001
            raise MailError("Graph: คำตอบของระบบ login อ่านไม่ได้") from None
        return _Token(value=value, expires_at=self._clock() + expires_in)

    # --- send ---------------------------------------------------------------

    def _payload(self, message: MailMessage) -> dict:
        # Graph takes one body; HTML is what people read. The plain-text part
        # stays for the log/fake senders and a future SMTP transport.
        payload: dict = {
            "subject": message.subject,
            "body": {"contentType": "HTML", "content": message.html},
            "toRecipients": _recipients(message.to),
        }
        if message.cc:
            payload["ccRecipients"] = _recipients(message.cc)
        if message.reply_to:
            payload["replyTo"] = _recipients([message.reply_to])
        # Kept in the sender mailbox's Sent Items: an audit copy IT can look up.
        return {"message": payload, "saveToSentItems": True}

    def _post(self, payload: dict) -> httpx.Response:
        try:
            return self._client.post(
                SEND_URL.format(sender=self.sender), json=payload, timeout=SEND_TIMEOUT,
                headers={"Authorization": f"Bearer {self._access_token()}"})
        except httpx.TimeoutException:
            # Graph may have accepted it before the reply was lost: a resend can
            # deliver a second copy (at-least-once, accepted by Peter).
            raise MailError("Graph: หมดเวลารอคำตอบ (timeout) — อีเมลอาจส่งไปแล้ว "
                            "ส่งซ้ำอาจได้สองฉบับ") from None
        except httpx.HTTPError as e:
            raise MailError(f"Graph: ติดต่อ Microsoft Graph ไม่ได้ ({type(e).__name__})") from None

    def prepare(self) -> None:
        """Before the notifier locks any row: make sure a token is cached, then
        book a send slot (waiting out the spacing and any Retry-After), so
        `send` has nothing slow left to do. Token first: a token failure means
        no send, so it must not use up a slot."""
        self._access_token()
        self.limiter.wait()

    def send(self, message: MailMessage) -> None:
        """One sendMail call: no waiting, no retry (it runs under row locks).
        Any failure is a MailError; the resend list does the retrying."""
        response = self._post(self._payload(message))
        if response.status_code == 401:
            # The token may have been revoked before its expiry: the next
            # prepare() fetches a fresh one.
            with self._token_lock:
                self._token = None
        if response.status_code == 429:
            # Honoured by the next prepare(), outside any lock.
            self.limiter.back_off(self._retry_after(response))
        self._raise_for(response)
        log.info("mail sent via Graph to=%s cc=%s subject=%s", ",".join(message.to),
                 ",".join(message.cc) or "-", message.subject)

    @staticmethod
    def _retry_after(response: httpx.Response) -> float:
        """Retry-After in seconds: delta-seconds or an HTTP-date (RFC 9110);
        1 s when missing, unreadable or not finite ("nan", "inf")."""
        value = response.headers.get("Retry-After", "").strip()
        try:
            seconds = float(value)
        except ValueError:
            try:
                when = parsedate_to_datetime(value)
            except (TypeError, ValueError, IndexError):
                return 1.0
            if when.tzinfo is None:  # "-0000": no zone given, HTTP dates are UTC
                when = when.replace(tzinfo=timezone.utc)
            seconds = (when - _utc_now()).total_seconds()
        return seconds if math.isfinite(seconds) else 1.0

    @staticmethod
    def _raise_for(response: httpx.Response) -> None:
        status = response.status_code
        if 200 <= status < 300:
            return
        code = _graph_error_code(response)
        detail = f"HTTP {status}" + (f", {code}" if code else "")
        if status == 401:
            raise MailError(f"Graph: ไม่ผ่านการยืนยันตัวตน ({detail}) — ตรวจ MS_CLIENT_ID / "
                            "MS_CLIENT_SECRET")
        if status == 403:
            raise MailError(f"Graph: ไม่มีสิทธิ์ส่งจาก mailbox นี้ ({detail}) — ตรวจสิทธิ์ "
                            "Mail.Send, admin consent และ Application Access Policy ของ MAIL_SENDER")
        if status == 429:
            raise MailError(f"Graph: ถูกจำกัดอัตราการส่ง ({detail}) — ส่งอีกครั้งภายหลัง")
        if status >= 500:
            raise MailError(f"Graph: ระบบ Microsoft ขัดข้อง ({detail}) — ส่งอีกครั้งภายหลัง")
        raise MailError(f"Graph: ส่งไม่สำเร็จ ({detail})")
