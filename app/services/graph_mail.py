"""The real sender: Microsoft Graph `sendMail` with client credentials (STORY-002 ticket 02).

One instance per process (see `mail.get_mail_sender`), so the app token and
the rate limiter are shared by every send in that process. Every failure is a
`MailError` with a short reason that ends up in a notify_failed event and on
the resend list — so it names the HTTP status and Graph's error code, never
the client secret, the token or the email body.
"""

import logging
import re
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

import httpx

from app.services.mail import MailError, MailMessage

log = logging.getLogger("app.mail")

TOKEN_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
SEND_URL = "https://graph.microsoft.com/v1.0/users/{sender}/sendMail"
SCOPE = "https://graph.microsoft.com/.default"

# A token is renewed this long before Graph says it expires, so a send never
# starts with a token that runs out on the way.
TOKEN_MARGIN_SECONDS = 300
# Throttled (429): wait what Graph asks, but never longer than this inside a
# background task; past it the send fails and goes on the resend list.
RETRY_AFTER_CAP_SECONDS = 10
TIMEOUT = httpx.Timeout(15.0, connect=5.0)
WINDOW_SECONDS = 60.0

BAD_CREDENTIALS = ("Graph: ใช้ credentials ไม่ได้ ({detail}) — client secret อาจหมดอายุ "
                   "ตรวจ MS_CLIENT_SECRET / Graph credentials do not work, the client "
                   "secret may have expired — check MS_CLIENT_SECRET")

Clock = Callable[[], float]
Sleep = Callable[[float], None]


class RateLimiter:
    """At most `per_minute` sends *start* in any 60-second window (sliding).

    A send that would exceed it waits for the oldest start to leave the window.
    Exchange Online allows about 30 messages a minute per mailbox; the default
    25 leaves room. Per process: two app processes would need a shared limiter.
    """

    def __init__(self, per_minute: int, clock: Clock = time.monotonic,
                 sleep: Sleep = time.sleep) -> None:
        if per_minute < 1:
            raise ValueError("MAIL_RATE_PER_MINUTE must be at least 1")
        self.per_minute = per_minute
        self._clock, self._sleep = clock, sleep
        self._starts: deque[float] = deque()
        self._lock = threading.Lock()

    def _free_in(self) -> float:
        """Seconds until a send may start (0 = now). Call with the lock held."""
        now = self._clock()
        while self._starts and self._starts[0] <= now - WINDOW_SECONDS:
            self._starts.popleft()
        if len(self._starts) < self.per_minute:
            return 0.0
        return self._starts[0] + WINDOW_SECONDS - now

    def acquire(self) -> None:
        """Wait for a slot and take it (records this send's start)."""
        with self._lock:  # held while waiting: sends queue up in order
            while (wait := self._free_in()) > 0:
                self._sleep(wait)
            self._starts.append(self._clock())

    def wait_for_slot(self) -> None:
        """Wait until a send could start, without taking the slot.

        The notifier calls this *before* it locks request rows, so the minute-
        long wait happens with no lock held; `acquire` in `send` then almost
        always passes at once. If another send took the slot in between, the
        wait inside `send` is the rare, bounded fallback.
        """
        while True:
            with self._lock:
                wait = self._free_in()
            if wait <= 0:
                return
            self._sleep(wait)


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
        self._clock, self._sleep = clock, sleep
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
                TOKEN_URL.format(tenant=self._tenant_id),
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
                SEND_URL.format(sender=self.sender), json=payload,
                headers={"Authorization": f"Bearer {self._access_token()}"})
        except httpx.TimeoutException:
            # Graph may have accepted it before the reply was lost: a resend can
            # deliver a second copy (at-least-once, accepted by Peter).
            raise MailError("Graph: หมดเวลารอคำตอบ (timeout) — อีเมลอาจส่งไปแล้ว "
                            "ส่งซ้ำอาจได้สองฉบับ") from None
        except httpx.HTTPError as e:
            raise MailError(f"Graph: ติดต่อ Microsoft Graph ไม่ได้ ({type(e).__name__})") from None

    def wait_for_slot(self) -> None:
        self.limiter.wait_for_slot()

    def send(self, message: MailMessage) -> None:
        self.limiter.acquire()
        payload = self._payload(message)
        response = self._post(payload)
        if response.status_code == 401:
            # The token may have been revoked before its expiry: one fresh try.
            with self._token_lock:
                self._token = None
            response = self._post(payload)
        if response.status_code == 429:
            wait = self._retry_after(response)
            if wait is not None:
                self._sleep(wait)
                response = self._post(payload)
        self._raise_for(response)
        log.info("mail sent via Graph to=%s cc=%s subject=%s", ",".join(message.to),
                 ",".join(message.cc) or "-", message.subject)

    def _retry_after(self, response: httpx.Response) -> float | None:
        """Seconds to wait before the one retry, or None when Graph asks for
        longer than the cap (then fail now and leave it for a resend)."""
        try:
            seconds = float(response.headers.get("Retry-After", "1"))
        except ValueError:
            seconds = 1.0
        seconds = max(seconds, 0.0)
        return seconds if seconds <= RETRY_AFTER_CAP_SECONDS else None

    @staticmethod
    def _raise_for(response: httpx.Response) -> None:
        status = response.status_code
        if status == 202 or 200 <= status < 300:
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
