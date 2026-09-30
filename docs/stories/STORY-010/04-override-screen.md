# 04: Override screen — reason, whose item it is, and what will be lost

Status: todo
Triage: ready-for-agent
Parent: STORY-010
Blocked by: 03

**What to build:** The Administrator overrides a code from the request's
status panel in two steps, so a typo cannot silently attach the request to
someone else's item. Step 1: type code X and a reason, press "ตรวจสอบรหัส";
the panel shows the result of `check_override` (ticket 03): the item name X
belongs to in the group master, any warning (no Plant snapshot), any refusal
in Thai, and — when X is above the register — how many numbers will be thrown
away. Step 2: "ยืนยันใช้รหัสนี้" saves it; when more than 10 numbers would be
lost, an extra checkbox "ยืนยันว่าเลข N ตัวจะถูกทิ้งถาวร" must be ticked. The
form stays visible on errors (htmx error slot). Only Administrators see the
form (as today). Thai UI.

- [ ] Checking a code shows the master item's name before anything is saved,
      and saving without having checked is not possible
- [ ] Refusals and warnings from ticket 03 appear in Thai inside the form,
      and the form survives
- [ ] A jump of more than 10 shows the number of lost codes and needs the
      extra checkbox; the server refuses without it (not just the browser)
- [ ] The saved request shows the new code via `partials/item_code.html`;
      history shows `code_overridden` with the reason and, if any,
      `register_advanced`
- [ ] Procurement never sees the form and gets 403 on both endpoints
