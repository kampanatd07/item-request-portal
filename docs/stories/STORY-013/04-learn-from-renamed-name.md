# 04: Category suggestion learns from the renamed name

Status: ready-for-agent
Triage: ready-for-agent
Parent: STORY-013
Blocked by: 01, 02

**What to build:** after a category move, the correction fed to category
suggestion is the Item Name after the prefix swap, with its Name Prefix cut
off by the shared searchable-part rule (Q5, Q10, Q11), so the learned name
and the learned category agree, and the learned text has the same shape a
Requester types (no prefix). Today it learns the old-prefixed name under the
new category.

- [ ] After a move, suggesting a category for the name without a prefix finds
      the new category (STORY-013 AC11)
- [ ] The learned text has no Name Prefix
- [ ] A name kept without a prefix (ticket 03) is learned whole
- [ ] `tests/test_categorizer.py` keeps passing; if any of its assertions
      would have to change beyond the one allowed in ticket 02, stop and ask
