# 05: Procurement sees resubmits clearly in the queue

Status: ready-for-agent
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

- [ ] Badge on resubmitted requests; none on new ones
- [ ] Latest reply and changes shown above the history
- [ ] Warning shown when a Procurement-typed name was replaced
- [ ] No warning when Procurement never edited the name, or when the resubmit
      kept the name
