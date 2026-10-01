"""Telling requesters what happened to their request (STORY-002).

Runs after the status change has committed (BackgroundTasks), in its own DB
session, so a slow or failed send never blocks Procurement.

Each send is claimed atomically: an UPDATE that matches only while the
request is still in the state being announced takes the row's write lock
(a row lock on PostgreSQL, the database write lock on SQLite) and holds it
through the send and the status change. A second, concurrent send for the
same request waits, then matches nothing and sends nothing.

Delivery is at-least-once: if Graph accepts an email but its reply is lost
(timeout), or the email went out but recording it failed, the attempt is
recorded as notify_failed and a resend can deliver a second copy. Accepted
behaviour (Peter, 2026-10-01), not a bug.

One request's problem never stops the others: any error is rolled back,
recorded as notify_failed in a fresh transaction, and the loop goes on.
"""

import logging

from collections.abc import Callable

from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.config import settings
from app.models import ItemRequest, RequestEvent
from app.services.mail import MailError, MailMessage, MailSender
from app.templating import templates

SessionFactory = Callable[[], Session]
log = logging.getLogger("app.notify")


def _link(req: ItemRequest) -> str | None:
    base = settings.public_base_url.rstrip("/")
    return f"{base}/my-requests#request-{req.id}" if base else None


def _message(to: list[str], subject: str, template: str, **ctx) -> MailMessage:
    html = templates.env.get_template(f"email/{template}.html").render(**ctx)
    body = templates.env.get_template(f"email/{template}.txt").render(**ctx)
    return MailMessage(to=to, subject=subject, html=html, text=body,
                       reply_to=settings.mail_reply_to or None)


def build_created_email(req: ItemRequest) -> MailMessage:
    """'Created in AX — ready to order', in Thai, the code up front."""
    subject = (f"[Item Portal] รหัส {req.generated_code} สร้างใน AX แล้ว — ใช้สั่งซื้อได้ "
               f"— {req.item_name}")
    return _message([req.requester_email], subject[:250], "created",
                    req=req, link=_link(req))


def _claim(db: Session, request_id: int, status: str) -> ItemRequest | None:
    """Lock the request row if it is still `status`; None if someone else got there."""
    claimed = db.execute(
        text("UPDATE item_requests SET status = status WHERE id = :id AND status = :status"),
        {"id": request_id, "status": status},
    ).rowcount
    return db.get(ItemRequest, request_id) if claimed == 1 else None


def notify_created(session_factory: SessionFactory, request_ids: list[int],
                   sender: MailSender, actor: str) -> dict[str, int]:
    """Email each request that is still `created`; move it to `notified`.

    One transaction per request: claim, send, record, commit. Returns counts
    for logging and tests.
    """
    counts = {"sent": 0, "failed": 0, "skipped": 0}
    db = session_factory()
    try:
        for request_id in sorted(set(request_ids)):
            counts[_notify_one_created(db, request_id, sender, actor)] += 1
    finally:
        db.close()
    return counts


def _notify_one_created(db: Session, request_id: int, sender: MailSender, actor: str) -> str:
    """Claim, send, record, commit for one request; returns which count to bump."""
    try:
        req = _claim(db, request_id, "created")
    except OperationalError:
        # Another notifier (or a long write) holds the lock past the busy
        # timeout. Leave it: the request stays 'created' and shows up in the
        # "not yet notified" list for a resend.
        db.rollback()
        log.warning("notify: request %s busy, skipped", request_id)
        return "skipped"
    if req is None:
        db.rollback()
        return "skipped"
    sent = False
    try:
        message = build_created_email(req)
        sender.send(message)
        sent = True
        req.status = "notified"
        db.add(RequestEvent(request_id=req.id, actor=actor, action="notified",
                            detail=f"created → {', '.join(message.to)}"))
        db.commit()
        return "sent"
    except Exception as e:  # noqa: BLE001 - record any failure, then carry on
        db.rollback()
        if isinstance(e, MailError):
            reason = str(e)
        elif sent:
            reason = (f"ส่งอีเมลแล้วแต่บันทึกผลไม่สำเร็จ ({type(e).__name__}) "
                      "— ผู้รับอาจได้ซ้ำถ้าส่งอีกครั้ง")
        else:
            reason = f"สร้างหรือส่งอีเมลไม่สำเร็จ ({type(e).__name__}: {e})"
        _record_failure(db, request_id, actor, f"created: {reason}")
        return "failed"


def _record_failure(db: Session, request_id: int, actor: str, detail: str) -> None:
    """notify_failed in its own transaction; never raises (logged instead)."""
    try:
        db.add(RequestEvent(request_id=request_id, actor=actor, action="notify_failed",
                            detail=detail[:1000]))
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
        log.exception("notify: could not record notify_failed for request %s", request_id)
