# 02: A Requester resubmits their own Needs Info request

Status: ready-for-agent
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

- [ ] Happy path: fields edited, name recomposed, status `submitted`, events
      as above, Procurement note cleared
- [ ] A name Procurement typed earlier is replaced; the old name is in the
      `request_edited` event
- [ ] Another Account's request (GET or POST) → 403
- [ ] Own request no longer in Needs Info → 409 "คำขอนี้ไม่ได้รอข้อมูลแล้ว
      (สถานะปัจจุบัน: …)"; nothing saved, no event
- [ ] A posted Plant is ignored
- [ ] Empty reply → Thai error, nothing saved
- [ ] A request with no stored Base Name shows an empty, required Base Name
      field
- [ ] Duplicate Check results appear on load
- [ ] Thai fields (SARA AM, spaced units) survive a resubmit unchanged
