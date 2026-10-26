"""Telling requesters what happened to their request (STORY-002).

Runs after the status change has committed (BackgroundTasks), in its own DB
session, so a slow or failed send never blocks Procurement.

Each send is claimed atomically: an UPDATE that matches only while the
request is still in the state being announced takes the row's write lock
(a row lock on PostgreSQL, the database write lock on SQLite) and holds it
through the send and the status change. Everything slow happens before the
claim (`prepare`: rate-limit wait, token); under the lock there is one short
sendMail call and no retry (decisions.md, 2026-10-14). A second, concurrent send for the
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
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import exists, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, aliased

from app.config import settings
from app.database import SessionFactory
from app.services.auth import normalize_email
from app.models import ROLES, Account, ItemRequest, RequestEvent
from app.services.mail import MailError, MailMessage, MailSender, prepare
from app.services.queue_view import ResubmitSummary, resubmit_summary
from app.templating import templates

log = logging.getLogger("app.notify")


def _url(path: str) -> str | None:
    """An absolute portal link, or None when PUBLIC_BASE_URL is not set."""
    base = settings.public_base_url.rstrip("/")
    return f"{base}{path}" if base else None


def _link(req: ItemRequest) -> str | None:
    return _url(f"/my-requests#request-{req.id}")


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
    # Older requests may hold an address with odd case or surrounding spaces
    # (see list_my_requests): it is sent, grouped and compared normalised.
    submitter = normalize_email(req.requester_email)
    email = None if switched_off_domain(req) else normalize_email(req.originator_email or "")
    if not email:
        return [submitter], []
    return [email], [] if submitter == email else [submitter]


def switched_off_domain(req: ItemRequest) -> str | None:
    """The originator's email domain if an Administrator has switched it off
    since the request was submitted, else None."""
    from sqlalchemy.orm import object_session

    from app.services.config_admin import active_mail_domains

    if not req.originator_email:
        return None
    db = object_session(req)
    if db is None:
        # Fail closed: without a session the domain cannot be checked, and
        # passing would send internal data to a domain that was switched off.
        raise RuntimeError(f"request {req.id} is not attached to a session; "
                           "cannot check its originator's email domain")
    domain = normalize_email(req.originator_email).rsplit("@", 1)[1]
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
# PostgreSQL's SQLSTATE when lock_timeout runs out.
LOCK_NOT_AVAILABLE = "55P03"
SUBJECT_CODES = 3


def group_key(req: ItemRequest) -> GroupKey:
    """(To, CC set), case-insensitive: requests share an email only when they
    go to the same To *and* the same CC, so nobody is copied on items they did
    not submit (Peter, ticket 03)."""
    to, cc = recipients(req)
    return to[0].lower(), tuple(sorted(c.lower() for c in cc))


def _greeting(req: ItemRequest) -> str:
    to, _ = recipients(req)
    return (req.originator_name if to == [normalize_email(req.originator_email or "")]
            else req.requester_name)


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


def _prepare(sender: MailSender) -> str | None:
    """Run the sender's slow part before any claim; the reason if it failed.

    The failure is recorded after the claim, like a failed send, so it is
    only written for requests that still owe the email."""
    try:
        prepare(sender)
    except MailError as e:
        return str(e)
    except Exception as e:  # noqa: BLE001 - recorded like any other send failure
        return f"เตรียมส่งอีเมลไม่สำเร็จ ({type(e).__name__}: {e})"
    return None


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
    not_ready = _prepare(sender)  # the slow part, before any row lock is held
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
    failures: list[tuple[list[ItemRequest], str]] = []
    for req in claimed:
        try:
            parts[group_key(req)].append(req)
        except Exception as e:  # noqa: BLE001 - one bad request never stops the rest
            failures.append(([req], f"หาผู้รับไม่ได้ ({type(e).__name__}: {e})"))
    sent_ids: set[int] = set()
    reasons: dict[int, str] = {}  # request id -> why its part failed
    try:
        for key in sorted(parts):
            part = parts[key]
            try:
                if not_ready is not None:
                    raise MailError(not_ready)
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


# --- needs_info / rejected: one email per status change (ticket 04) ---------------

# Request statuses as event actions; 'notified' is left out because the same
# word is also the action of a notification event.
STATUS_ACTIONS = ("submitted", "in_review", "needs_info", "approved", "rejected",
                  "exported", "created")
ANNOUNCED = ("needs_info", "rejected")
# Events that settle "is an email owed?": a sent email, or the migration's
# honest note that the change predates email (e52ce808c5d5) — never a fake
# `notified`. Both point at the change through ref_event_id.
NOT_APPLICABLE = "notify_not_applicable"
CLOSING = ("notified", NOT_APPLICABLE)


def latest_status_event(db: Session, request_id: int) -> RequestEvent | None:
    return db.scalar(select(RequestEvent).where(
        RequestEvent.request_id == request_id,
        RequestEvent.action.in_(STATUS_ACTIONS),
    ).order_by(RequestEvent.id.desc()).limit(1))


def build_status_email(req: ItemRequest, status: str, reason: str | None = None) -> MailMessage:
    """needs_info, or rejected (before or after a code), in Thai, with the reason
    given for *this* change (the event's note — review_note keeps an older one
    when a change comes without a note)."""
    to, cc = recipients(req)
    if status == "needs_info":
        subject = f"[Item Portal] คำขอ #{req.id} ต้องการข้อมูลเพิ่ม — {req.item_name}"
        template = "needs_info"
    elif req.generated_code:
        subject = (f"[Item Portal] รหัส {req.generated_code} ยกเลิกแล้ว ห้ามใช้ — "
                   f"คำขอ #{req.id} ไม่อนุมัติ")
        template = "rejected"
    else:
        subject = f"[Item Portal] คำขอ #{req.id} ไม่อนุมัติ — {req.item_name}"
        template = "rejected"
    # Needs Info: straight to the form that answers it (STORY-009).
    link = _url(f"/my-requests/{req.id}/resubmit") if status == "needs_info" else _link(req)
    message = _message(to, subject[:250], template, req=req, link=link,
                       greeting=_greeting(req), reason=(reason or "").strip() or "-")
    message.cc = cc
    return message


def notify_status(session_factory: SessionFactory, request_id: int, event_id: int,
                  sender: MailSender, actor: str) -> str:
    """Announce one status change (event E = `event_id`) to the requester, once.

    Under the request's row lock: the request must still be in E's status, E
    must still be its latest status change, and no `notified` event may point
    at E yet (ref_event_id). Otherwise nothing is sent — a stale announcement
    is skipped quietly (logged), it is not a failure. Returns sent / failed /
    skipped.
    """
    db = session_factory()
    try:
        event = db.get(RequestEvent, event_id)
        if event is None or event.request_id != request_id or event.action not in ANNOUNCED:
            log.warning("notify: event %s is not an announceable change of request %s",
                        event_id, request_id)
            return "skipped"
        status, reason_text = event.action, event.detail
        db.rollback()
        not_ready = _prepare(sender)  # the slow part, before the row lock is held
        req = None
        for attempt in (1, 2):
            try:
                _set_lock_timeout(db)
                req = _claim(db, request_id, status)
                break
            except OperationalError:
                db.rollback()
                if attempt == 2:
                    # Unlike 'created', a needs_info/rejected request has no state
                    # left to find it by — record it so the resend button shows.
                    _record_failure(db, request_id, actor,
                                    f"{status}: ระบบไม่ว่าง (ล็อกค้าง) — ส่งอีกครั้งได้",
                                    ref_event_id=event_id)
                    return "failed"
        if req is None:
            db.rollback()
            log.info("notify: request %s no longer %s, not announced", request_id, status)
            return "skipped"
        sent = False
        try:
            latest = latest_status_event(db, request_id)
            already = db.scalar(select(RequestEvent.id).where(
                RequestEvent.ref_event_id == event_id, RequestEvent.action.in_(CLOSING)))
            if latest is None or latest.id != event_id or already is not None:
                db.rollback()
                log.info("notify: event %s superseded or already announced", event_id)
                return "skipped"
            if not_ready is not None:
                raise MailError(not_ready)
            message = build_status_email(req, status, reason_text)
            sender.send(message)
            sent = True
            note = recipient_note(req)
            db.add(RequestEvent(request_id=req.id, actor=actor, action="notified",
                                ref_event_id=event_id,
                                detail=f"{status} → {', '.join(message.to)}"
                                       + (f" · {note}" if note else "")))
            db.commit()
            return "sent"
        except Exception as e:  # noqa: BLE001 - record any failure
            db.rollback()
            if isinstance(e, MailError):
                reason = str(e)
            elif sent:
                reason = (f"ส่งอีเมลแล้วแต่บันทึกผลไม่สำเร็จ ({type(e).__name__}) "
                          "— ผู้รับอาจได้ซ้ำถ้าส่งอีกครั้ง")
            else:
                reason = f"สร้างหรือส่งอีเมลไม่สำเร็จ ({type(e).__name__}: {e})"
            _record_failure(db, request_id, actor, f"{status}: {reason}", ref_event_id=event_id)
            return "failed"
    finally:
        db.close()


def _record_failure(db: Session, request_id: int, actor: str, detail: str,
                    ref_event_id: int | None = None) -> None:
    """notify_failed in its own transaction; never raises (logged instead).

    Bounded like every notifier transaction that takes a lock (decisions.md
    2026-10-26): the INSERT's foreign key needs a KEY SHARE lock on the request
    row, which a FOR UPDATE holder (an Approval, an export) blocks. If it times
    out, the email is still owed: it shows on the resend list once older than
    LOST_AFTER, with the generic reason.
    """
    try:
        _set_lock_timeout(db)  # SET LOCAL: this transaction only
        db.add(RequestEvent(request_id=request_id, actor=actor, action="notify_failed",
                            ref_event_id=ref_event_id, detail=detail[:1000]))
        db.commit()
    except Exception as e:  # noqa: BLE001
        db.rollback()
        if getattr(getattr(e, "orig", None), "sqlstate", None) == LOCK_NOT_AVAILABLE:
            # Expected while another transaction holds the row: a warning.
            log.warning("notify: could not record notify_failed for request %s "
                        "(row busy, lock_timeout)", request_id, exc_info=True)
        else:
            log.exception("notify: could not record notify_failed for request %s",
                          request_id)


# --- Resend: what is still waiting to be sent (ticket 06) -------------------------

# A 'created' request or a needs_info/rejected change with neither `notified`
# nor `notify_failed` is normally a send still running in the background; past this it was lost (a
# restart killed the task) and goes on the resend list (Peter, ticket 06).
LOST_AFTER = timedelta(minutes=10)
NOT_SENT_YET = "ยังไม่ได้ส่ง — อาจค้างจากการ restart"


@dataclass
class PendingNotification:
    req: ItemRequest
    kind: str               # 'created', 'needs_info' or 'rejected'
    event_id: int | None    # the status change E to announce; None for 'created'
    reason: str             # the latest notify_failed detail, or NOT_SENT_YET
    since: datetime         # when the change happened


def pending_notifications(db: Session, now: datetime,
                          request_id: int | None = None) -> list[PendingNotification]:
    """Emails still owed, oldest change first; read-only.

    - every request still `created` whose "created in AX" email failed, or
      that has been `created` longer than LOST_AFTER (lost before it ran), unless a `notify_not_applicable` follows its latest
      'created' (it was created before email existed);
    - every needs_info/rejected change E that is still current — the request
      is still in E's status and E is its latest status change — with no
      `notified` or `notify_not_applicable` pointing at E, and either a `notify_failed` pointing at E or
      older than LOST_AFTER. A stale E is never listed, so never resent.
    """
    pending: list[PendingNotification] = []

    created_q = select(ItemRequest).where(ItemRequest.status == "created")
    if request_id is not None:
        created_q = created_q.where(ItemRequest.id == request_id)
    created = list(db.scalars(created_q))
    events: dict[int, list[RequestEvent]] = defaultdict(list)
    if created:
        for e in db.scalars(select(RequestEvent).where(
                RequestEvent.request_id.in_([r.id for r in created]),
                RequestEvent.action.in_(("created", "notify_failed", NOT_APPLICABLE)),
        ).order_by(RequestEvent.id)):
            events[e.request_id].append(e)
    for req in created:
        change, failure, closed = None, None, False
        for e in events[req.id]:
            if e.action == "created":
                # only what happened since the latest 'created' counts
                change, failure, closed = e, None, False
            elif e.action == NOT_APPLICABLE:
                closed = True  # by event order: an old request may have no 'created' to ref
            else:
                failure = e
        since = change.at if change is not None else req.updated_at
        if closed or (failure is None and since > now - LOST_AFTER):
            continue  # closed, or probably still being sent
        pending.append(PendingNotification(
            req=req, kind="created", event_id=None,
            reason=failure.detail if failure is not None else NOT_SENT_YET, since=since))

    change, later, done = aliased(RequestEvent), aliased(RequestEvent), aliased(RequestEvent)
    changes_q = (
        select(change, ItemRequest)
        .join(ItemRequest, ItemRequest.id == change.request_id)
        .where(
            change.action.in_(ANNOUNCED),
            ItemRequest.status == change.action,
            ~exists().where(later.request_id == change.request_id,
                            later.action.in_(STATUS_ACTIONS), later.id > change.id),
            ~exists().where(done.ref_event_id == change.id, done.action.in_(CLOSING)),
        )
    )
    if request_id is not None:
        changes_q = changes_q.where(change.request_id == request_id)
    current = list(db.execute(changes_q))
    failures: dict[int, RequestEvent] = {}
    if current:
        for e in db.scalars(select(RequestEvent).where(
                RequestEvent.ref_event_id.in_([c.id for c, _ in current]),
                RequestEvent.action == "notify_failed",
        ).order_by(RequestEvent.id)):
            failures[e.ref_event_id] = e  # the last one wins
    for c, req in current:
        failure = failures.get(c.id)
        if failure is None and c.at > now - LOST_AFTER:
            continue  # probably still being sent
        pending.append(PendingNotification(
            req=req, kind=c.action, event_id=c.id,
            reason=failure.detail if failure is not None else NOT_SENT_YET, since=c.at))

    return sorted(pending, key=lambda p: (p.since, p.req.id))


def resend(session_factory: SessionFactory, created_ids: list[int],
           changes: list[tuple[int, int]], sender: MailSender, actor: str) -> dict[str, int]:
    """Send again what `pending_notifications` listed, through the same claims
    as the first send — pressing twice sends once. `created_ids` go out grouped
    per (To, CC); `changes` are (request id, status change id). Counts per request."""
    counts = notify_created(session_factory, created_ids, sender, actor)
    for request_id, event_id in changes:
        counts[notify_status(session_factory, request_id, event_id, sender, actor)] += 1
    return counts



# --- Procurement hears about a resubmit (STORY-009 ticket 06) -----------------------------------------

def procurement_recipients(db: Session) -> list[str]:
    """Every active Account with Role Procurement or higher: the same rule as
    `requests.notifies_procurement` (has_role over ROLES)."""
    staff = ROLES[ROLES.index("procurement"):]
    return list(db.scalars(
        select(Account.email)
        .where(Account.active, Account.role.in_(staff))
        .order_by(Account.email)
    ))


def build_resubmitted_email(req: ItemRequest, summary: ResubmitSummary, actor_name: str,
                            to: list[str]) -> MailMessage:
    """One email to all of Procurement; replies go to whoever resubmitted."""
    subject = f"[Item Portal] คำขอ #{req.id} ส่งกลับแล้ว — {req.item_name}"
    message = _message(to, subject[:250], "resubmitted", req=req, summary=summary,
                       actor_name=actor_name, link=_url(f"/queue/{req.id}"))
    message.reply_to = summary.actor
    return message


def notify_resubmitted(session_factory: SessionFactory, request_id: int, event_id: int,
                       sender: MailSender) -> None:
    """Email Procurement about the resubmit whose `submitted` event is `event_id`.

    Best-effort (decisions.md 2026-10-16): any failure is logged with its
    traceback and nothing else happens. No event, no resend list, no retry;
    the request is in the queue whether or not this arrives.
    """
    try:
        with session_factory() as db:
            req = db.get(ItemRequest, request_id)
            summary = resubmit_summary(req, event_id) if req is not None else None
            to = procurement_recipients(db)
            if summary is None or not to:
                return
            actor = db.scalar(select(Account).where(Account.email == summary.actor))
            message = build_resubmitted_email(
                req, summary, actor.display_name if actor else summary.actor, to)
        prepare(sender)
        sender.send(message)
    except Exception:  # noqa: BLE001 - best-effort: logged, never raised
        log.exception("resubmit email for request %s not sent (best-effort, no retry)",
                      request_id)
