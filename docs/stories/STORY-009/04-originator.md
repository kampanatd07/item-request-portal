# 04: The Originator sees and resubmits requests made for them

Status: done
Triage: ready-for-agent
Parent: STORY-009
Blocked by: 02

**What to build:** "My requests" also lists, in every status, the requests
where the Account is the Originator, labelled "ขอแทนโดย <Requester name>". An
Originator whose Account is active and in the request's Plant (if the Account
has a Plant) can resubmit a Needs Info request exactly like the Requester,
except that the originator fields are locked for them. The Requester can still
change the originator fields on resubmit; they are validated exactly as on a
new request. See decisions.md 2026-10-16.

- [x] An Originator sees their requests in "My requests" with the label
- [x] An Originator resubmits a Needs Info request; the actor on the events is
      their email
- [x] An Originator Account that is inactive, or in another Plant → 403
- [x] Originator fields posted by the Originator are ignored
- [x] The Requester changing the originator email to a domain that is not
      allowed → Thai error, nothing saved

## Notes (2026-10-19)

- **Who may resubmit** lives in `_may_own()` (Requester, or an active
  Originator in the request's Plant; an Account without a Plant in any Plant,
  Peter 2026-10-19). `resubmittable()` (GET and POST) and `may_resubmit()`
  (the button in "My requests") both use it.
- **Originator fields** are editable only by the Requester with Role
  Procurement or Administrator (`originator_editable()`); a Requester-role
  Account cannot name an originator on a new request either. The form
  prefills them, so an untouched form is not an edit. A change goes through
  `_check_originator()` and logs `ขอแทน:` / `อีเมลผู้ขอจริง:` lines in
  `request_edited`.
- **"My requests" lists by email only, no Plant or active rule** (Peter,
  2026-10-19): an Originator in another Plant sees the row, read-only, with
  no resubmit button (that still follows `may_resubmit`). Why: the
  Originator already gets the created/rejected emails carrying the same
  data; hiding the row would leave them with an email and no request to
  find.
- **A field that is not posted keeps its value** (`Form(None)`); only a
  posted `""` clears it. A stored email whose domain has been switched off
  since passes unchanged (`_check_originator(keep_email=…)`); a new email is
  still checked.
- **"ผู้ขอ" on the resubmit form** shows the request's Requester, not the
  logged-in Account (Peter, 2026-10-19).
- **Tests:** `tests/test_resubmit_originator.py`, 18 tests, including a
  two-thread race (Requester vs Originator) on file SQLite with the ticket 03
  helpers: one `submitted`, the loser gets 409, none of the loser's values or
  reply in the DB. Old tests: none changed. Suite: 676 passed.
- **Mutation check:** each of these made at least one new test fail:
  dropping the Plant check, dropping the active check, making the originator
  fields always editable, showing the logged-in Account as "ผู้ขอ", and
  removing `AND status='needs_info'` from the claim; after the review fixes,
  going back to `Form("")`, dropping `keep_email`, and putting the
  originator lines first.

## Code review (2026-10-19)

Ran `/code-review` on the uncommitted diff. 8 findings. Peter's decisions:
fixed 1, 3, 4, 5, 8; 2 decided as "show the row, no button" (see Notes);
6 and 7 not changed.

1. **A missing originator field clears the originator** —
   `app/routes/requests.py` (`on_behalf_of`/`originator_email` default to
   `Form("")`). A Procurement Requester whose post lacks the two fields (a
   script, an HTMX post, a form opened before a deploy) has `""` compared
   with the stored values, which counts as a change → the originator is set
   to NULL; the Originator loses access and emails stop going to them.
   **Recommend: fix.** Default to `None` and treat "not posted" as "keep".
2. **"My requests" shows Originator rows from another Plant** —
   `list_my_requests()` matches `originator_email` only, while `_may_own()`
   also requires the Plant. An ACM Account named on an APM request sees that
   row (item name, Procurement's note, the code) but gets 403 on resubmit.
   The spec says "lists, in every status, the requests where the Account is
   the Originator", with no Plant rule, so this is Peter's call.
   **Recommend: apply the same rule as resubmit** (active + same Plant, or
   no Plant), so one definition decides "my request".
3. **A name-only change re-checks the unchanged email** — any change to the
   originator fields runs `_check_originator()` on both. If the stored
   email's domain has since been switched off, fixing a typo in the name
   refuses the whole resubmit (the other edits are lost too).
   **Recommend: fix.** Check the domain only when the email itself changed.
4. **Order of change lines** — the originator lines sit between the field
   lines and the `ชื่อสินค้า:` line, so the order depends on whether the
   originator changed. **Recommend: fix** (originator lines last).
5. **Duplicate work in `is_requester`/`is_originator`** — local imports on
   every call; `_may_own` checks the Requester twice. Cosmetic.
   **Recommend: fix** (import `normalize_email` at module level).
6. **`ขอแทน` label hardcoded instead of `ON_BEHALF_PREFIX`** — nothing
   parses that prefix today, and the edit line is in a `request_edited`
   event, not `submitted`. **Recommend: no change.**
7. **The Requester has no active/Plant check, the Originator does** — by the
   spec ("the Requester, whatever their Role"); a deactivated Account cannot
   log in anyway. A Requester-role Account moved to another Plant can still
   resubmit its old request. **Recommend: no change** (it is their request);
   say if you want the Plant rule for Requesters too.
8. **Type hints** — `my_requests()` has no return annotation and the two
   lambdas are untyped (CLAUDE.md: type hints on all functions).
   **Recommend: fix.**
