"""Telling requesters what happened to their request (STORY-002).

Runs after the status change has committed (BackgroundTasks), in its own DB
session, so a slow or failed send never blocks Procurement.

Each send is claimed atomically: an UPDATE that matches only while the
request is still in the state being announced takes the row's write lock
(a row lock on PostgreSQL, the database write lock on SQLite) and holds it
through the send and the status change. A second, concurrent send for the
same request waits, then matches nothing and sends nothing. "Created" emails
are grouped: one email per (To, CC) per click, listing every code.

Delivery is at-least-once: if Graph accepts an email but its reply is lost
(timeout), or the email went out but recording it failed, the attempt is
recorded as notify_failed and a resend can deliver a second copy. Accepted
behaviour (Peter, 2026-10-01), not a bug.

One request's problem never stops the others: any error is rolled back,
recorded as notify_failed in a fresh transaction, and the loop goes on.
"""

import logging

from collections import defaultdict
from collections.abc import Callable

from sqlalchemy import select, text
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


def recipients(req: ItemRequest) -> tuple[list[str], list[str]]:
    """(to, cc) for a request's emails: the originator when Procurement gave
    their email, with the submitting Account copied; otherwise the submitter.

    The originator's domain is checked again at send time: if an Administrator
    has switched it off since (e.g. a company left the group), internal item
    data no longer goes there — the submitter gets the email instead. The same
    address is never in both To and CC.
    """
    email = None if switched_off_domain(req) else req.originator_email
    if not email:
        return [req.requester_email], []
    cc = [] if req.requester_email.lower() == email.lower() else [req.requester_email]
    return [email], cc


def switched_off_domain(req: ItemRequest) -> str | None:
    """The originator's email domain if an Administrator has switched it off
    since the request was submitted, else None."""
    from sqlalchemy.orm import object_session

    from app.services.config_admin import active_mail_domains

    db = object_session(req)
    if not req.originator_email or db is None:
        return None
    domain = req.originator_email.rsplit("@", 1)[1]
    return None if domain in active_mail_domains(db) else domain


def recipient_note(req: ItemRequest) -> str | None:
    """Why the email did not go where the request says, for the event detail."""
    domain = switched_off_domain(req)
    return f"โดเมน {domain} ถูกปิด — ส่งให้ผู้ส่งคำขอแทน" if domain else None


GroupKey = tuple[str, tuple[str, ...]]
# How long a notifier waits for a request row another transaction holds. On
# PostgreSQL row-lock waits have no timeout by default, so without this a
# background task could hang for good; SQLite's busy timeout (30 s) plays the
# same role there. Past it the group stays 'created' for the resend list.
NOTIFY_LOCK_TIMEOUT_SECONDS = 30
SUBJECT_CODES = 3


def group_key(req: ItemRequest) -> GroupKey:
    """(To, CC set), case-insensitive: requests share an email only when they
    go to the same To *and* the same CC, so nobody is copied on items they did
    not submit (Peter, ticket 03)."""
    to, cc = recipients(req)
    return to[0].lower(), tuple(sorted(c.lower() for c in cc))


def _greeting(req: ItemRequest) -> str:
    to, _ = recipients(req)
    return req.originator_name if to == [req.originator_email] else req.requester_name


def build_created_group_email(reqs: list[ItemRequest]) -> MailMessage:
    """One 'created in AX' email for requests sharing (To, CC), all codes listed."""
    reqs = sorted(reqs, key=lambda r: r.id)
    to, cc = recipients(reqs[0])
    if len(reqs) == 1:
        subject = (f"[Item Portal] รหัส {reqs[0].generated_code} สร้างใน AX แล้ว — ใช้สั่งซื้อได้ "
                   f"— {reqs[0].item_name}")
    else:
        codes = ", ".join(r.generated_code for r in reqs[:SUBJECT_CODES])
        more = ", …" if len(reqs) > SUBJECT_CODES else ""
        subject = (f"[Item Portal] สร้างใน AX แล้ว {len(reqs)} รายการ — ใช้สั่งซื้อได้ "
                   f"({codes}{more})")
    names = {_greeting(r) for r in reqs}
    greeting = names.pop() if len(names) == 1 else "ผู้ขอ"
    message = _message(to, subject[:250], "created", greeting=greeting,
                       items=[{"req": r, "link": _link(r)} for r in reqs])
    message.cc = cc
    return message


def build_created_email(req: ItemRequest) -> MailMessage:
    """'Created in AX — ready to order' for one request."""
    return build_created_group_email([req])


def _set_lock_timeout(db: Session) -> None:
    """Bound row-lock waits for this transaction (PostgreSQL; SQLite has its own)."""
    bind = db.get_bind()
    if bind is not None and bind.dialect.name == "postgresql":
        db.execute(text(f"SET LOCAL lock_timeout = '{NOTIFY_LOCK_TIMEOUT_SECONDS}s'"))


def _claim(db: Session, request_id: int, status: str) -> ItemRequest | None:
    """Lock the request row if it is still `status`; None if someone else got there."""
    claimed = db.execute(
        text("UPDATE item_requests SET status = status WHERE id = :id AND status = :status"),
        {"id": request_id, "status": status},
    ).rowcount
    return db.get(ItemRequest, request_id) if claimed == 1 else None


def notify_created(session_factory: SessionFactory, request_ids: list[int],
                   sender: MailSender, actor: str) -> dict[str, int]:
    """Email the requests still `created`, one email per (To, CC) group, and move
    each group to `notified` when its email went out.

    Groups are read without locks, then handled one transaction each in
    (To, CC) order — the same order in every process — claiming the group's
    rows in id order. Counts are per request.
    """
    counts = {"sent": 0, "failed": 0, "skipped": 0}
    ids = sorted(set(request_ids))
    if not ids:
        return counts
    db = session_factory()
    try:
        pending = list(db.scalars(select(ItemRequest).where(
            ItemRequest.id.in_(ids), ItemRequest.status == "created")))
        counts["skipped"] += len(ids) - len(pending)
        groups: dict[GroupKey, list[int]] = defaultdict(list)
        unreadable: list[tuple[int, str]] = []
        for req in pending:
            try:
                groups[group_key(req)].append(req.id)
            except Exception as e:  # noqa: BLE001 - one bad request never stops the rest
                unreadable.append((req.id, f"หาผู้รับไม่ได้ ({type(e).__name__}: {e})"))
        db.rollback()  # end the unlocked read
        for request_id, reason in unreadable:
            _record_failure(db, request_id, actor, f"created: {reason}")
            counts["failed"] += 1
        for key in sorted(groups):
            for outcome, n in _notify_created_group(db, sorted(groups[key]), sender,
                                                    actor).items():
                counts[outcome] += n
    finally:
        db.close()
    return counts


def _notify_created_group(db: Session, ids: list[int], sender: MailSender,
                          actor: str) -> dict[str, int]:
    """Claim, send, record and commit one (To, CC) group; counts per request."""
    claimed: list[ItemRequest] = []
    for attempt in (1, 2):
        try:
            claimed = []
            _set_lock_timeout(db)  # SET LOCAL: lasts until this group's commit/rollback
            for request_id in ids:
                req = _claim(db, request_id, "created")
                if req is not None:
                    claimed.append(req)
            break
        except OperationalError:
            # Another notifier (or a long write) held a lock past the timeout
            # (SQLite busy timeout / PostgreSQL lock_timeout, both raise
            # OperationalError). Try once more; then leave the group — it stays
            # 'created' and shows in the "not yet notified" list.
            db.rollback()
            if attempt == 2:
                log.warning("notify: requests %s busy twice, left for resend", ids)
                return {"skipped": len(ids)}
    outcome = {"sent": 0, "failed": 0, "skipped": len(ids) - len(claimed)}
    if not claimed:
        db.rollback()
        return outcome

    # Recipients are checked again under the locks (e.g. a domain switched off
    # since the read); requests that no longer belong together get their own email.
    parts: dict[GroupKey, list[ItemRequest]] = defaultdict(list)
    for req in claimed:
        parts[group_key(req)].append(req)
    sent_ids: set[int] = set()
    reasons: dict[int, str] = {}  # request id -> why its part failed
    try:
        failures: list[tuple[list[ItemRequest], str]] = []
        for key in sorted(parts):
            part = parts[key]
            try:
                message = build_created_group_email(part)
                sender.send(message)
            except MailError as e:
                failures.append((part, str(e)))
                continue
            except Exception as e:  # noqa: BLE001 - record any failure, carry on
                failures.append((part, f"สร้างหรือส่งอีเมลไม่สำเร็จ ({type(e).__name__}: {e})"))
                continue
            sent_ids.update(r.id for r in part)
            batch_note = f" (ฉบับรวม {len(part)} รายการ)" if len(part) > 1 else ""
            for req in part:
                req.status = "notified"
                note = recipient_note(req)
                db.add(RequestEvent(
                    request_id=req.id, actor=actor, action="notified",
                    detail=f"created → {', '.join(message.to)}{batch_note}"
                           + (f" · {note}" if note else "")))
            outcome["sent"] += len(part)
        for part, reason in failures:
            reasons.update((r.id, reason) for r in part)
            for req in part:
                db.add(RequestEvent(request_id=req.id, actor=actor, action="notify_failed",
                                    detail=f"created: {reason}"[:1000]))
            outcome["failed"] += len(part)
        db.commit()
    except Exception as e:  # noqa: BLE001 - recording failed: say so per request
        db.rollback()
        claimed_ids = [r.id for r in claimed]
        for request_id in claimed_ids:
            if request_id in sent_ids:
                reason = ("ส่งอีเมลแล้วแต่บันทึกผลไม่สำเร็จ "
                          f"({type(e).__name__}) — ผู้รับอาจได้ซ้ำถ้าส่งอีกครั้ง")
            else:
                reason = reasons.get(request_id) or \
                    f"สร้างหรือส่งอีเมลไม่สำเร็จ ({type(e).__name__}: {e})"
            _record_failure(db, request_id, actor, f"created: {reason}")
        return {"sent": 0, "failed": len(claimed_ids), "skipped": outcome["skipped"]}
    return outcome


def _record_failure(db: Session, request_id: int, actor: str, detail: str) -> None:
    """notify_failed in its own transaction; never raises (logged instead)."""
    try:
        db.add(RequestEvent(request_id=request_id, actor=actor, action="notify_failed",
                            detail=detail[:1000]))
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
        log.exception("notify: could not record notify_failed for request %s", request_id)
