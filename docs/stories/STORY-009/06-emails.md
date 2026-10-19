# 06: Emails: Procurement hears about resubmits; Needs Info links to the form

Status: done
Triage: ready-for-agent
Parent: STORY-009
Blocked by: 02

**What to build:**
- **Procurement email:** after a resubmit commits, a background task emails
  every active Account with the Procurement or Administrator Role. It goes out
  only when the actor holds neither Role.
  - Content: request number, new Item Name, Plant, who resubmitted, the reply,
    the changed-field lines and a link to the request in the queue. No
    Duplicate Check results. A txt and an html template.
  - Best-effort: a `MailError` is logged and nothing else happens. No
    `notified`/`notify_failed` event, never on the resend list (decisions.md
    2026-10-16).
- **Needs Info email:** the link now points to the resubmit page, and the text
  reads "แก้ไขและส่งกลับในระบบ (สำหรับผู้มีบัญชี)"; "กรุณาตอบกลับอีเมลนี้…" stays.

- [x] A Requester resubmits → one email to each active Procurement/Administrator
      Account, content as above
- [x] Procurement/Administrator resubmits, or uses the queue button → no email
- [x] Inactive Procurement Accounts get nothing
- [x] A failing sender: resubmit still succeeds; a log line; no event; the
      request is not on the resend list
- [x] The Needs Info email (txt and html) links to the resubmit page with the
      new wording

## Notes (2026-10-19)

- **Procurement email** (`notify.notify_resubmitted`, background task after
  the resubmit commits). `resubmit_request` returns `Resubmitted(req,
  notify_event_id)`: the id of the `submitted` event it wrote itself, set
  only when Procurement must be told (`requests.notifies_procurement`). The
  route only schedules the task (review fix 1+2: a lookup after the commit
  could be overtaken by a status change).
  - **One message, every recipient in To** (Peter, 2026-10-19): active
    Procurement and Administrator Accounts. Each gets one email; one send
    against the rate limit.
  - **Reply-To = whoever resubmitted** (Peter, 2026-10-19), not
    `MAIL_REPLY_TO`, which is Procurement's own mailbox.
  - **Any exception is caught and logged with `log.exception`** (traceback),
    not only `MailError` (Peter, 2026-10-19). No event, no resend list, no
    retry.
  - Sent only when `notifies_procurement(account)` (requests.py): the actor holds neither
    Procurement nor Administrator. The requeue button sends nothing (ticket 03).
  - Content comes from `queue_view.resubmit_summary(req, event_id)`, the same
    summary as the queue card, so the email and the card cannot disagree.
    Template pair `email/resubmitted.{txt,html}`; queue link only when
    `PUBLIC_BASE_URL` is set (one `_url(path)` helper for every link).
  - Known limit: the Item Name and subject are read when the email is built,
    seconds after the resubmit. If Procurement renames the request in that
    gap, the email shows the newer name; the reply and change lines are
    always this resubmit's.
- **Needs Info email:** links to `/my-requests/{id}/resubmit`, "แก้ไขและส่ง
  กลับในระบบ (สำหรับผู้มีบัญชี)"; "กรุณาตอบกลับอีเมลนี้…" kept. Created and
  rejected emails keep the My requests link. Followed after the request has
  left Needs Info, the page answers 409 with a link "ดูคำขอนี้ในคำขอของฉัน"
  to `/my-requests#request-N` (review fix 3).
- **An Originator in another Plant who follows that link** gets 403 (ticket
  04 rule) with "… — ตอบกลับทางอีเมลที่ได้รับแทนได้" (Peter, 2026-10-19).
  Other 403s keep the plain text, including an inactive Originator in the
  request's Plant (review fix 4).
- **Tests:** `tests/test_notify_resubmit.py`, 17 tests. The two race tests
  change the status right after the resubmit commits, inside the route
  (in_review; and a second Needs Info + resubmit): the email still goes out,
  about the first resubmit. Old tests: none changed. Suite: 711 passed.
- **Mutation check:** each made at least one test fail: always notify,
  inactive Accounts included, no Reply-To, catching `MailError` only,
  `log.error` instead of `log.exception`, the old Needs Info link, the plain
  403 for an Originator. After the review fixes: the route's old
  "latest submitted event" lookup (both race tests fail), the plant text for
  an inactive Originator, no link on the 409 page.

## Code review (2026-10-19)

Ran `/code-review` on the uncommitted diff. 7 findings. Peter's decisions:
fixed 1, 2, 3, 4, 6; 5 and 7 not changed.

1. **Race between the commit and the event lookup** (`routes/requests.py`).
   The route finds the `submitted` event with `latest_status_event` *after*
   `resubmit_request` committed. If Procurement changes the status in that
   gap, the email is silently dropped (in_review) or, after a second
   Needs Info + resubmit, tied to the wrong event (two emails about the
   second resubmit, none about the first).
   **Recommend: fix**, with 2: `resubmit_request` returns the id of the
   `submitted` event it wrote.
2. **Business logic in the route** (CLAUDE.md: routes → services → models).
   The "notify or not" rule and the event lookup sit in the route.
   **Recommend: fix**: `resubmit_request` returns a small result
   (`req`, `notify_event_id`: the `submitted` event id when Procurement must
   be told, else None); `notifies_procurement` moves to requests.py; the
   route only schedules the task. No existing test uses the return value.
3. **An old Needs Info link ends on an error page.** Once the request has
   left Needs Info, `/my-requests/{id}/resubmit` answers 409 with only the
   message; the old link (`my-requests#request-N`) always showed the
   request. **Recommend: fix without changing the 409**: the 409 page for
   the request's own Requester/Originator gets a link "ดูคำขอนี้ในคำขอของฉัน"
   to `/my-requests#request-N`. (A redirect instead would change ticket 02's
   `test_own_request_not_in_needs_info_gets_409`, an old test.)
4. **The "another Plant" 403 text also fires for an inactive Originator.**
   Not reachable over HTTP today (deactivating ends every session), only
   through the service. **Recommend: fix** (cheap): give that text only when
   the Account is active and the Plant differs.
5. **Actor display-name lookup is case-sensitive.** Account emails are stored
   lowercased and the event actor is `account.email`, so they always match.
   **Recommend: no change.**
6. **Three near-identical link helpers** (`_link`, `_resubmit_link`,
   `_queue_link`). **Recommend: fix**: one `_url(path)` helper.
7. **No email when a Procurement member resubmits, even if another member
   asked for the info.** This is the rule in decisions.md 2026-10-16 ("No
   email goes out when Procurement or an Administrator resubmits
   themselves"). **Recommend: no change**; revisit if Procurement grows
   beyond 1–2 people.

### Review of the fix diff only (2026-10-19)

No correctness defects. Checked: `submitted.id` after the commit
(`expire_on_commit=False`), every caller of `resubmit_request`, no
references left to the removed helpers, `message.html` without `link`, and
that the race tests hit the gap between the commit and the route going on
(the old lookup fails both). One trivial nit, not changed: ticket 05's
`tests/test_queue_resubmit.py` helper `_resubmit` is still annotated
`-> ItemRequest` but now returns `Resubmitted` (no caller uses it). Fixed,
annotation only (Peter, 2026-10-19).
