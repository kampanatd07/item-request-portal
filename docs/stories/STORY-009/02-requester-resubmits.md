# 02: A Requester resubmits their own Needs Info request

Status: done
Triage: ready-for-agent
Parent: STORY-009
Blocked by: 01

**What to build:** On "My requests", a Needs Info request the Account
submitted has an "แก้ไขและส่งกลับ" button that leads to its resubmit page. The
page is the request form, prefilled with the request's current values,
including any Sub-Category Procurement chose. Plant is locked. A box at the top
reads "จัดซื้อต้องการ: <latest Needs Info reason>". The Duplicate Check runs as
soon as the page loads and again while typing; it never blocks. A required
reply sits above the "ส่งกลับให้จัดซื้อ" button.

On send, the request leaves Needs Info only through a conditional claim
(`UPDATE … SET status = 'submitted' WHERE id = :id AND status = 'needs_info'`,
the STORY-002 pattern). Then, in the same transaction:
- the Item Name is recomposed through ticket 01's validation path;
- the request's Procurement note is cleared;
- a `request_edited` event is written, one line per changed field
  (`field: old → new`, Item Name included), only if something changed;
- a `submitted` event is written, with the reply and the top 3 duplicate
  candidates.

Plant always comes from the stored request. In this ticket the originator
fields are left as they are; ticket 04 covers them.

- [x] Happy path: fields edited, name recomposed, status `submitted`, events
      as above, Procurement note cleared
- [x] A name Procurement typed earlier is replaced; the old name is in the
      `request_edited` event
- [x] Another Account's request (GET or POST) → 403
- [x] Own request no longer in Needs Info → 409 "คำขอนี้ไม่ได้รอข้อมูลแล้ว
      (สถานะปัจจุบัน: …)"; nothing saved, no event
- [x] A posted Plant is ignored
- [x] Empty reply → Thai error, nothing saved
- [x] A request with no stored Base Name shows an empty, required Base Name
      field
- [x] Duplicate Check results appear on load
- [x] Thai fields (SARA AM, spaced units) survive a resubmit unchanged

Implementation notes (2026-10-16):
- Service `resubmit_request`. Order of steps:
  1. Ownership check: `requester_email` only, so 403 for anyone else,
     Procurement included.
  2. The reply: NFC + fix_thai, one line, at most 1000 characters.
  3. Work out the Search name, before any lock (this may ask the LLM).
  4. Claim the row: `UPDATE … SET status='submitted', updated_at=… WHERE
     status='needs_info'`. 0 rows → 409, or 404 if the request is gone.
  5. Validate the fields and save, in the same transaction. A refusal rolls
     back to needs_info.
- **"No edit"** (decision A): every posted field equals what the form was
  prefilled with, compared as text with whitespace collapsed (a textarea
  drops a leading newline and sends CRLF). With no edit, the Item Name is
  kept even if Procurement typed it, and no `request_edited` is written.
  Any edit recomposes the name, and `request_edited` lists each edited
  field plus the Item Name.
- **Search name:** if the Base Name changed and the Search name was left as
  it was, a new one is worked out before the claim, as for a new request. A
  Search name the Requester typed wins.
- **Resubmit form:** `request_form.html` with `r` set.
  - Plant is shown, never posted.
  - The stored code system, group, sub-category, UoM and Procurement
    Category stay selectable even if switched off since.
  - On load the Duplicate Check runs with no suggestions (`dup_only`).
  - While typing, suggestions show but no category is picked automatically
    (`no_autopick`).
  - The preview starts with the stored Item Name.
- 409 added to the htmx swap list in `base.html`.
- Code review: three rounds. Round 1 and 2 correctness findings were fixed
  test-first (auto-pick on load, inactive values, CRLF and truncated search
  names counting as edits, LLM under the claim, `updated_at`, the reply,
  404). In round 3, Peter split the findings: item 5 fixed (see Search name
  above); the rest noted below.
- Known limits from review round 3 (accepted, Peter 2026-10-16):
  1. A group or sub-category switched off while the request waited stays
     selected, but any other edit is then refused ("หมวดย่อยไม่ถูกต้อง",
     422, nothing saved). The Requester must pick an active one. The message
     does not say the old one was switched off.
  2. After moving away from a switched-off group or sub-category, it cannot
     be picked again (the fragments list active ones only).
  3. Editing only price, UoM, spec, Search name or the category leaves the
     preview on the stored name, but the server recomposes on any edit (Q16;
     the old name is in `request_edited`, and ticket 05 warns).
  4. Typing into a name field and undoing it: the preview shows the
     recomposed name, but the server keeps the stored one (nothing was
     edited).
  5. Clearing the Search name counts as an edit even if the classifier gives
     back the same value. The name is recomposed and a
     `Search name: X → X` line appears.
  6. If the stored Search name is empty, every resubmit classifies (maybe the
     LLM) before the claim and may not use the result. Slow, not wrong, and
     rare, since a submit always sets one.
- Review of the item-5 fix (2026-10-16): no new finding that saves wrong
  data, lets the wrong person act, or loses data. Noted:
  1. A request with no stored Base Name (only rows from before the
     `base_name` migration, so dev databases; production starts empty)
     counts as "Base Name changed" on its first resubmit, so an untouched
     Search name is worked out again.
  2. Any Base Name change, a case or typo fix included, works the Search
     name out again if it was left as it was. This is the rule as agreed;
     the form does not show that the old value will be replaced.
  3. Clicking a suggestion that equals the stored Search name looks the same
     as leaving it untouched, so the classifier's top pick is stored instead.
  4. A refreshed Search name equal to the old one still logs
     `Search name: X → X`.
  5. With the LLM down, the refresh stores the classifier's fallback (first
     words of the Base Name), the same as a new request would.
  6. The refresh decision reads the row before the claim. Only a resubmit
     writes `base_name`/`search_name`, and it needs the claim, so the two
     reads cannot differ in practice.
  7. Clean-ups: `auto_select=inf` as a "never pick" flag, the overlapping
     `dup_only`/`no_autopick` modes, and missing type hints on the new
     test helpers.
