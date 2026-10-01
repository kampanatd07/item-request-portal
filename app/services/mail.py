"""Sending email, behind one small interface (STORY-002).

The first real sender is Microsoft Graph (ticket 02); dev and tests use the
log sender and a fake. Another transport (e.g. SMTP) can be added later
without touching the callers.
"""

import logging
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


class LogMailSender:
    """Dev mode, no mail settings: record that an email would have gone out.

    Logs recipients and subject only — the body can hold item details that
    have no business in application logs.
    """

    def send(self, message: MailMessage) -> None:
        log.info("mail (not sent, no sender configured) to=%s cc=%s subject=%s",
                 ",".join(message.to), ",".join(message.cc) or "-", message.subject)


def get_mail_sender() -> MailSender:
    """FastAPI dependency; tests override it with a fake sender."""
    return LogMailSender()
