# 06: A Name Override longer than 110 characters is refused

Status: ready-for-agent
Triage: ready-for-agent
Parent: STORY-013
Blocked by: None (can start immediately)

**What to build:** when Procurement types a Name Override in the queue, the
system refuses a name longer than 110 characters with a Thai error giving
the length, and changes nothing. Today only an empty name is refused, so a
longer name would be exported into AX/D365, which the group standard does
not allow (Item Name ≤ 110). Must ship before the plants get access, with
the rest of STORY-013 (Peter, 2026-10-20). Found while planning ticket 02:
a category move refuses a name over 110, but the same name could be typed
directly.

- [ ] A Name Override of 110 characters is saved
- [ ] 111 characters: refused with a Thai message giving the length; the
      Item Name and the events unchanged
- [ ] The length counts the name as it would be stored (spaces collapsed, as
      `edit_name` stores it)
- [ ] The queue's name panel shows the error and keeps the old name

Other naming rules for a Name Override (no `,`, separators, unit spacing):
not here, see STORY-007's Notes.
