"""What the queue shows about requests that came back from Needs Info (STORY-009 ticket 05).

Read-only: everything here is worked out from a request's events, so the
display never disagrees with the history below it.
"""

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ItemRequest, RequestEvent
from app.services.naming import prefix_as_written, starts_with_prefix
from app.services.requests import CHANGE_ARROW, NAME_CHANGE_LABEL, name_prefix_of, named_on

NAME_LINE_PREFIX = f"{NAME_CHANGE_LABEL}: "


@dataclass
class ResubmitSummary:
    """The latest way out of Needs Info: a resubmit, or Procurement's requeue."""

    actor: str
    at: datetime
    by_owner: bool  # the Requester or Originator, not Procurement's requeue button
    reply: str
    changes: list[str] = field(default_factory=list)
    # (the name Procurement typed, the name that replaced it), if one was replaced.
    replaced_name: tuple[str, str] | None = None


def name_prefix_warning(req: ItemRequest) -> str | None:
    """The Name Prefix the Item Name should start with, when it does not
    (STORY-013): a Name Override without it, or a prefix edited in the
    taxonomy since. None when it fits, or the category has no prefix.
    Display only: nothing is blocked."""
    prefix = name_prefix_of(req.group, req.subgroup)
    if not prefix_as_written(prefix) or starts_with_prefix(req.item_name, prefix):
        return None
    # As it appears in a name: typing exactly this clears the warning.
    return prefix_as_written(prefix)


def resubmitted_ids(db: Session, request_ids: list[int]) -> set[int]:
    """Of these requests, the ones that have been in Needs Info. One query for
    the whole queue page, not one per row."""
    if not request_ids:
        return set()
    return set(db.scalars(
        select(RequestEvent.request_id).distinct()
        .where(RequestEvent.request_id.in_(request_ids), RequestEvent.action == "needs_info")
    ))


def _name_line(event: RequestEvent) -> str | None:
    """The Item Name change line of a `request_edited`, if it changed the name."""
    if event.action != "request_edited":
        return None
    return next((ln for ln in (event.detail or "").splitlines()
                 if ln.startswith(NAME_LINE_PREFIX) and CHANGE_ARROW in ln), None)


def _replaced_name(events: list[RequestEvent], edited_at: int,
                   submitted_at: int) -> tuple[str, str] | None:
    """(typed, new) if this resubmit replaced a name Procurement typed.

    The replaced name is Procurement's if the last event that set the name
    before this resubmit is a `name_edited`, however many Needs Info rounds
    ago (Peter, 2026-10-19: a time window missed a typed name that a requeue
    or an edit-free resubmit had kept). Only `name_edited` and a
    `request_edited` with a name line count as setting the name. A name
    Procurement typed again after the resubmit makes the warning stale, so it
    is not shown then.
    """
    line = _name_line(events[edited_at])
    if line is None:
        return None
    setter = next((e for e in reversed(events[:edited_at])
                   if e.action == "name_edited" or _name_line(e)), None)
    if setter is None or setter.action != "name_edited":
        return None
    if any(e.action == "name_edited" for e in events[submitted_at + 1:]):
        return None
    old, _, new = line[len(NAME_LINE_PREFIX):].partition(CHANGE_ARROW)
    return old, new


def _summary_at(req: ItemRequest, events: list[RequestEvent], found: int) -> ResubmitSummary:
    """The way out of Needs Info at events[found] (a `submitted`), with the
    `request_edited` written just before it in the same transaction."""
    submitted = events[found]
    edited_at = found - 1
    edited = edited_at >= 0 and events[edited_at].action == "request_edited" \
        and events[edited_at].actor == submitted.actor
    return ResubmitSummary(
        actor=submitted.actor,
        at=submitted.at,
        by_owner=named_on(req, submitted.actor),
        # The reply is the first line; a Duplicate Check line may follow.
        reply=(submitted.detail or "").split("\n", 1)[0],
        changes=(events[edited_at].detail or "").splitlines() if edited else [],
        replaced_name=_replaced_name(events, edited_at, found) if edited else None,
    )


def latest_resubmit(req: ItemRequest) -> ResubmitSummary | None:
    """The latest `submitted` event that followed a `needs_info`. Reads
    `req.events` (ordered by id), which the detail page loads for the history
    anyway."""
    events = req.events
    waiting, found = False, None
    for i, e in enumerate(events):
        if e.action == "needs_info":
            waiting = True
        elif e.action == "submitted" and waiting:
            waiting, found = False, i
    return _summary_at(req, events, found) if found is not None else None


def resubmit_summary(req: ItemRequest, event_id: int) -> ResubmitSummary | None:
    """The resubmit whose `submitted` event is `event_id` (the Procurement
    email names the exact event, so a later change cannot alter its content)."""
    events = req.events
    found = next((i for i, e in enumerate(events) if e.id == event_id), None)
    if found is None or events[found].action != "submitted":
        return None
    return _summary_at(req, events, found)
