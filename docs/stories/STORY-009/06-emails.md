# 06: Emails: Procurement hears about resubmits; Needs Info links to the form

Status: ready-for-agent
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

- [ ] A Requester resubmits → one email to each active Procurement/Administrator
      Account, content as above
- [ ] Procurement/Administrator resubmits, or uses the queue button → no email
- [ ] Inactive Procurement Accounts get nothing
- [ ] A failing sender: resubmit still succeeds; a log line; no event; the
      request is not on the resend list
- [ ] The Needs Info email (txt and html) links to the resubmit page with the
      new wording
