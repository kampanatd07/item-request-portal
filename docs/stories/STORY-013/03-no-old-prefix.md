# 03: A name without the old prefix is kept, with a warning

Status: ready-for-agent
Triage: ready-for-agent
Parent: STORY-013
Blocked by: 02

**What to build:** when a request moves to another Sub-Category but its Item
Name does not start with the old Sub-Category's Name Prefix (a Name Override
without one, or a Name Prefix edited in the taxonomy since), the move goes
ahead and the name is left exactly as it is: the system never guesses where
the category part is (Q7). The category panel shows a red warning
"ชื่อไม่ได้ขึ้นต้นด้วย prefix ของหมวดเดิม (<prefix เดิม>) — ตรวจและแก้ชื่อเอง",
and `category_changed` notes that the name did not change. The standing
warning from ticket 01 then stays on the queue detail until the name is fixed.

- [ ] Name without the old prefix: moved, name unchanged (STORY-013 AC4)
- [ ] Red warning on the category panel naming the old prefix
- [ ] `category_changed` says the name did not change; no
      `name_prefix_changed` event
- [ ] The queue detail's standing warning shows afterwards (ticket 01)
- [ ] Same for an Administrator's move of a coded `approved` request (the code
      is still re-issued)
