# 05: Procurement sees resubmits clearly in the queue

Status: done
Triage: ready-for-agent
Parent: STORY-009
Blocked by: 02

**What to build:**
- **Queue table:** a "ส่งกลับแล้ว" badge on `submitted` requests that were in
  Needs Info before.
- **Request detail, above the history:** the latest reply and the changed
  fields (from the latest `request_edited`).
- **Replaced-name warning:** if that resubmit replaced an Item Name Procurement
  had typed (a `name_edited` event since the last Needs Info), a clear warning
  "ชื่อที่จัดซื้อแก้ไว้ถูกแทนที่: <เดิม> → <ใหม่>". Display only; nothing is
  blocked.

- [x] Badge on resubmitted requests; none on new ones
- [x] Latest reply and changes shown above the history
- [x] Warning shown when a Procurement-typed name was replaced
- [x] No warning when Procurement never edited the name, or when the resubmit
      kept the name

## Notes (2026-10-19)

- **Where:** `app/services/queue_view.py`, read-only, worked out from the
  request's events. `resubmitted_ids()` (one query for the queue page) and
  `latest_resubmit()` (the latest `submitted` that followed a `needs_info`,
  with the `request_edited` written just before it).
- **Badge** "ส่งกลับแล้ว" only on `submitted` rows (spec). The requeue button
  counts as coming back too.
- **Card** "ส่งกลับจากรอข้อมูล" under the request's main fields, above the
  name/category panels and the history, at every status (Peter, 2026-10-19).
  It shows the reply (first line of the `submitted` detail; the Duplicate
  Check line is left out) and the change lines. After the requeue button it
  reads "รับเข้าคิวใหม่โดยจัดซื้อ" with "หมายเหตุ".
- **Replaced-name warning:** shown when the resubmit changed the Item Name
  and the last event that set the name before it is a `name_edited`. Only
  `name_edited` and a `request_edited` with a `ชื่อสินค้า:` line count as
  setting the name. Hidden once Procurement types a name again after the
  resubmit (stale).
  - **Rule changed after code review (Peter, 2026-10-19).** The first rule
    was a time window: a `name_edited` after the previous `submitted`. It
    caught a name typed while reviewing, before Needs Info, but missed one
    kept through a requeue or an edit-free resubmit and replaced a round
    later (that cycle's `submitted` reset the window). The last-setter rule
    asks where the replaced name came from, however many rounds ago.
  - The `request_edited` line format is defined once in requests.py
    (`change_line`, `NAME_CHANGE_LABEL`, `CHANGE_ARROW`) and read back here.
- **History:** `request_edited` = "แก้ไขข้อมูลคำขอ" (the Requester, the
  Originator or Procurement may write it). The history times are now Thai
  time (`thai_time`), like the card; before this ticket they were UTC.
- **Known limit:** requeue and resubmit write the same `submitted` event, so
  the card tells them apart by actor: the Requester or Originator = a
  resubmit. When Procurement is the Requester and presses "รับเข้าคิวใหม่",
  the card says "ส่งกลับจากรอข้อมูล". No data is wrong.
- **Tests:** `tests/test_queue_resubmit.py`, 18 tests, over HTTP, including
  the review's case (typed → Needs Info → requeue → Needs Info → size
  edited → warning). Old tests: none changed. Suite: 694 passed.
- **Mutation check:** each made at least one test fail: counting
  `name_edited` from the first event; counting from the last `needs_info`
  (the ticket's original wording); dropping the stale check; treating every
  `submitted` as the owner's; dropping the status check on the badge. After
  the review fixes: going back to the time window (2 fail), not counting a
  `request_edited` as a name setter, UTC times in the history.
- **TODO after STORY-009 merges:** add to the Notes of STORY-013
  (`docs/stories/STORY-013-category-change-name-prefix.md`, on master since
  933689d; this branch was cut before it): the event that changes the name
  prefix on a category move must not count as a name setter, or it would
  wipe out where a Procurement-typed name came from (ticket 05's
  replaced-name rule, `queue_view._replaced_name`).

## Code review (2026-10-19)

Ran `/code-review` on the uncommitted diff. 9 findings. Peter's decisions:
fixed 1, 4, 5, 7, 8, 9; 2, 3 and 6 not changed. A follow-up review of the
fix diff only: see the end of this file.

1. **A name typed in an earlier cycle, kept, then replaced now: no warning.**
   Submit → Procurement types TYPED → Needs Info → requeue (or a resubmit with
   no edits, which keeps TYPED) → Needs Info → the Requester edits the size,
   the name is recomposed and TYPED is lost. The window starts after the
   requeue's `submitted`, so no `name_edited` is found.
   **Recommend: fix, by changing the rule** to "the last event that set the
   name before this resubmit is a `name_edited`" (the event the replaced
   name came from), instead of a time window. All 15 current tests keep
   their meaning (the earlier-cycle test: that name was already replaced by a
   `request_edited`, so it is not the last setter). This changes the rule you
   confirmed in decision 1, so it needs your OK.
2. **The requeue by a Procurement Requester shows as a reply** — the known
   limit above. A real fix gives requeue its own marker (another action or a
   detail prefix). That changes ticket 03's event and its tests (old tests).
   **Recommend: no change now**; record it as a known limit (done above).
3. **The card and warning show at every status** (an approved request still
   opens with a yellow card, maybe a red warning). This is what you chose in
   decision 3. **Recommend: no change.**
4. **Two clocks on one page:** the card uses `thai_time` (UTC+7), the history
   table uses raw `strftime` (UTC), so one event shows two times 7 h apart.
   The history's UTC time is older than this ticket.
   **Recommend: fix the history** to use `thai_time` (one line).
5. **The change-line format is copied, not shared** (`ชื่อสินค้า: ` and ` → `
   in requests.py and queue_view.py). A change in one silently removes the
   warning. **Recommend: fix**: define both once in requests.py and import.
6. **A name containing " → " is split in the wrong place.** Unlikely in item
   names; a real fix needs the names stored structured (a schema change).
   **Recommend: no change.**
7. **The detail page loads the events twice** (the history uses
   `req.events`, `latest_resubmit` queries again). **Recommend: fix**: use
   `req.events`.
8. **`events.index(edited)` searches for a position already known.**
   **Recommend: fix** (pass the index).
9. **"แก้ไขโดยผู้ขอ" is wrong when the Originator edits.**
   **Recommend: fix**: "แก้ไขข้อมูลคำขอ".

### Review of the fix diff only (2026-10-19)

No correctness defects. Checked: the setter rule's edge cases
(`category_changed` does not touch `item_name`, so it is rightly not a
setter), `req.events` ordering and freshness, no import cycle, change-line
text byte-identical to before, the new tests fail under the old window rule.
Its one gap ("the last setter is a `request_edited` → no warning") is already
pinned by `test_no_warning_for_a_name_typed_in_an_earlier_cycle`: the
mutation that stops counting `request_edited` as a setter fails it.
