"""Sending email, behind one small interface (STORY-002).

The first real sender is Microsoft Graph (ticket 02); dev and tests use the
log sender and a fake. Another transport (e.g. SMTP) can be added later
without touching the callers.
"""

import logging
import threading
from dataclasses import dataclass, field
from typing import Protocol

log = logging.getLogger("app.mail")


@dataclass
class MailMessage:
    to: list[str]
    subject: str
    html: str
    text: str
    cc: list[str] = field(default_factory=list)
    reply_to: str | None = None


class MailError(Exception):
    """Sending failed; the message is a readable reason for notify_failed."""


class MailSender(Protocol):
    def send(self, message: MailMessage) -> None: ...


def wait_for_slot(sender: MailSender) -> None:
    """Let a rate-limited sender make us wait now, before any row is locked
    (senders without a limit — log, fake — have nothing to wait for)."""
    wait = getattr(sender, "wait_for_slot", None)
    if wait is not None:
        wait()


class LogMailSender:
    """Dev mode, no mail settings: record that an email would have gone out.

    Logs recipients and subject only — the body can hold item details that
    have no business in application logs.
    """

    def send(self, message: MailMessage) -> None:
        log.info("mail (not sent, no sender configured) to=%s cc=%s subject=%s",
                 ",".join(message.to), ",".join(message.cc) or "-", message.subject)


GRAPH_SETTINGS = ("MS_TENANT_ID", "MS_CLIENT_ID", "MS_CLIENT_SECRET", "MAIL_SENDER")

_graph: MailSender | None = None
_graph_lock = threading.Lock()


def _graph_values() -> dict[str, str]:
    from app.config import settings

    return {"MS_TENANT_ID": settings.ms_tenant_id.strip(),
            "MS_CLIENT_ID": settings.ms_client_id.strip(),
            "MS_CLIENT_SECRET": settings.ms_client_secret.get_secret_value().strip(),
            "MAIL_SENDER": settings.mail_sender.strip()}


def get_mail_sender() -> MailSender:
    """FastAPI dependency: the Graph sender when all four Graph settings are
    set, else the log sender (AC2). One Graph sender per process, so its token
    cache and rate limiter cover every send. Tests override this dependency."""
    global _graph
    values = _graph_values()
    missing = [name for name in GRAPH_SETTINGS if not values[name]]
    if missing:
        if len(missing) < len(GRAPH_SETTINGS):
            # Half-configured is a mistake worth seeing; names only, never values.
            log.warning("mail: Graph settings incomplete (missing %s) — emails are only "
                        "logged", ", ".join(missing))
        return LogMailSender()
    with _graph_lock:
        if _graph is None:
            from app.config import settings
            from app.services.graph_mail import GraphMailSender

            _graph = GraphMailSender(
                values["MS_TENANT_ID"], values["MS_CLIENT_ID"], values["MS_CLIENT_SECRET"],
                values["MAIL_SENDER"], rate_per_minute=settings.mail_rate_per_minute)
        return _graph
