---
name: carabao-item-master
description: Carabao Group item-master standard (non-stock 9xx + service 7xx) — 11-digit central code, running register rules, naming convention, 24-unit UoM, taxonomy, governance, and Thai-text processing traps. Use whenever work touches item codes, item names, categories, units of measure, Thai product text (regex, normalization, matching, dedup), the running register, or AX/D365 item import files — in any project, not just item-request-portal.
---

# Carabao Group item master

A mistake here does not crash. It silently issues a wrong code or a duplicate
item into the group master, and plants start ordering against it. Treat every
rule below as a data-correctness rule, not a style rule.

Owner of the standard: Peter (Procurement Strategy). Any rule marked
**approved** changes only with his explicit OK.

## 1. Central code (approved)

```
900 01 00 0001
│   │  │  └── Running 4 — from the central register, one counter per Group+Sub
│   │  └───── Item Type 2 — always "00" in this phase
│   └──────── Sub-Category 2 — 01..99
└──────────── Item Group 3 — 7xx service, 9xx non-stock
```

- One code per item across all plants (CBD, ACM, APM, APG).
- Sub ≥ `01` always. All 11,377 legacy ACM/APM/APG codes have `0000` in digits
  4–7, so central codes cannot collide with them.
- Running 9999 reached → a new Sub-Category is needed; Data Owner approves.

## 2. Running register — iron rules

- Numbers are issued **only** by incrementing the register row for that
  Group+Sub, inside the same transaction that assigns the code (row lock on
  Postgres). **Never** compute `max(existing) + 1` — it cannot see codes issued
  elsewhere and races under concurrency.
- A counter never moves backwards. An issued number is never reused, even if the
  item is blocked.
- No pre-reserved blocks. (Legacy systems pre-generated 5,316 empty codes — the
  reason this rule exists.)
- Moving an item to another Sub-Category or Group = a **new code**. Category is
  locked once a code is issued, except by an Administrator (Data Steward) while
  the request is still approved and not exported — that issues a new code from
  the new Sub-Category's register and burns the old number (Governance §4).

## 3. Naming (approved)

```
[CATEGORY] - [ชื่อสินค้า/บริการ] - [รายละเอียดจำเพาะ]      ≤ 110 chars
```

| Segment | Content | Max |
|---|---|---|
| CATEGORY | the Sub-Category's name prefix, upper case (`references/taxonomy.md`) | 16 |
| name | head noun first, then brand / model | 50 |
| detail | size / spec / material / packing | 40 |

**Separators**
- ` - ` (space-dash-space) is the only level separator.
- `--` and `:` are never used. `,` is never used at all — drop it (`1,000` →
  `1000`, `ชุดตรวจ ,Funnel` → `ชุดตรวจ Funnel`).
- `/` is allowed only inside a spec, unspaced: `208 L/Drum`, `18 W/965`.
  Never as a separator (` / `).
- No leading separator or punctuation.

**Word order** — head noun before modifiers: `Ball Bearing SKF`, not
`SKF Ball Bearing`.

**Language (Hybrid)**

| Part | Language | Example |
|---|---|---|
| CATEGORY prefix | English, always | `BEARING`, `PPE` |
| Brand / model / part no. | English, exactly as the maker writes it | `SKF 6001-2RSH`, `Kingston A400`, `KIMAX` |
| Units, sizes, technical spec | English, always | `M12x1.75x40 mm`, `18 W`, `250 mL` |
| Common name with an international technical term | English | `Ball Bearing`, `Butterfly Valve`, `Safety Goggle` |
| Common name the floor says in Thai | Thai | `น้ำยาล้างจาน`, `ปูนซีเมนต์` |
| Service | Thai for domestic work, English for a foreign contract | `งานสอบเทียบ`, `MA Contract` |

**Numbers and units** — number, one space, SI unit as written in the UoM
standard: `20 L`, `250 mL`, `25 cm`, `5 kg`, `1 in`. Never `20ลิตร`, `20LT.`,
`(20L)`, `1"`. A dimension chain states the unit once: `10x20 mm`,
`M4x0.7x10 mm`. Packing goes after a slash: `208 L/Drum`, `20 L/แกลลอน`.

**Abbreviations** — only those in the Abbreviation Dictionary
(`references/uom.md` §Abbreviations; the full 52-term list is in the UoM
Confirm workbook).

**Never in a name** — `(ยกเลิก)` (use Lifecycle = Blocked), price, vendor, PO
or document number, project name.

**Not enough information → Needs Review, never guess.** `กรองน้ำมันเครื่อง`
with no vehicle model cannot be named while `กรองน้ำมันเครื่อง Toyota 1DZII`
exists; it goes to review.

**Before → after**

| Before | After |
|---|---|
| `Repair Air Blower--Asset & Spare parts--Air Diffuser` | `MACHINE REPAIR - งานซ่อม Air Blower - Air Diffuser Part` |
| `ชุดตรวจ ,Funnel 100 ml (non-sterile)` | `LAB CONSUMABLE - Filtration Funnel - 100 mL Non-Sterile` |
| `MOBIL NUTO H 32 -1/208LT.` | `LUBRICANT - Hydraulic Oil MOBIL NUTO H 32 - 208 L/Drum` |
| `ลูกปืน SKF 6001-2RSH` | `BEARING - Ball Bearing SKF - 6001-2RSH` |
| `ข้องอเชื่อม SUS304 90° SCH10 1"` | `PIPE FITTING - Butt Weld Elbow 90° SUS304 - SCH10 1 in` |
| `งานสอบเทียบ pH meter pH Basic-Bio-Kit` | `CALIBRATION - งานสอบเทียบ pH Meter - Model pH Basic-Bio-Kit` |

## 4. Units of measure

24 codes only — `references/uom.md`. Service default `JOB`, goods default `EA`,
but a default is a guess, not a confirmation. If Purchase UoM ≠ Base UoM, Pack
Size is mandatory. Never change the Base UoM of an item with open POs.

Never auto-merge look-alike units (`Job` vs `JOB` may be different per AX
environment). Merging is a deliberate, logged admin action.

## 5. Classification

**Decide in this order**
1. Service or Non-Stock → 7xx or 9xx.
2. Item Group — one of the 20. Never invent a group.
3. Sub-Category — one of the 130 in `references/taxonomy.md`. A new
   Sub-Category needs Data Owner approval.

**Principles (approved)**
- Classify by **what the thing is**, not who buys it.
- Classify from the item name, **never inherit the legacy group** — 29% of real
  ACM/APM/APG items sit in the wrong group (tools under 905 Factory Consume,
  cleaning liquid under 906). Copying the old group copies the error.
- Two tie-breakers:
  - *"Who wears or uses it, and for what?"* — staff uniform → 906-04;
    apparel for a marketing activity → 908-07.
  - *"If another department bought the same thing, would they get the same
    item?"* — if yes, it belongs in the shared group: travel → 710-02,
    transport → 709-01, not under Marketing.
- Marketing Activity (POSM, Merchandise, Event Production, DR Consultant,
  Media) is an **attribute**, not a category.

**Service vs part**
- A service request must never land in an Item-type category.
  `งานซ่อมปั๊มน้ำ` is service 700-xx, not pump parts 900-06.
- Split into two codes (one 7xx service + one 9xx part) only when the name
  carries a service verb: Repair, PM, Install, Overhaul, MA (and Thai
  equivalents ซ่อม, ติดตั้ง, บำรุงรักษา…). A plain part name stays one code.

**Sub-Category 99 (Other) — last resort**
- Allowed, but the requester must give a reason why no specific Sub-Category
  fits, and the request is flagged for procurement.
- Reasons are the input to the yearly taxonomy review. KPI: 99 ≤ 15% of all
  items (21.3% at Aug 2026).

**Needs Review — never guess**
- Looks like a fixed asset (machine, vehicle): flag it; procurement checks with
  Accounting and approves or rejects. Never auto-issue a code.
- Name empty or only punctuation.
- Uniform where "who wears it, for what" cannot be decided.
- Name too vague to separate from existing variants (see §3).

**Suggestions and duplicates**
- Auto-select a suggestion only when confidence reflects *closeness* of the
  match, not just agreement among distant neighbours. Always editable until a
  code is issued; after that only an Administrator may change the category,
  before export, and doing so issues a new code (§2).
- Duplicate merge is conservative: identical after normalization **and** same
  Sub-Category.

## 6. Thai text — traps already paid for

1. **Never `\b` next to Thai.** Thai vowels and tone marks are non-word chars,
   so `\bสี\b` matches inside `สีดำ` (64 safety items once fell into Chemicals).
   Use `(?<![ก-๙])` / `(?![ก-๙])`. Also no `\b` between a digit and a letter —
   `25cm` has no boundary.
2. **Never NFKC.** It splits SARA AM `ำ` into `ํ` + `า`; Thai keywords stop
   matching. Use NFC, then `fix_thai` (below).
3. **Thai has no spaces between words.** Match dictionary terms as substrings;
   rank by position first (the head noun comes first), length second. Otherwise
   `ติดตั้งเครื่องแพ็คกล่อง` is classified as `กล่อง` instead of an installation.
4. Duplicate detection: trigram similarity on normalized text, not exact match.

Reference helpers (copy, don't re-derive):

```python
import re, unicodedata

def fix_thai(text: str) -> str:
    return text.replace("ํา", "ำ")          # recompose SARA AM

def normalize(text: str) -> str:
    text = fix_thai(unicodedata.normalize("NFC", text or "")).lower()
    text = re.sub(r"[^\w฀-๿]+", " ", text)  # keep Thai + word chars
    return " ".join(text.split())

def thai_word(term: str) -> str:            # regex for a standalone Thai term
    return rf"(?<![ก-๙]){re.escape(term)}(?![ก-๙])"
```

## 7. Scope guards

- **Never touch CBD codes starting `99`** (stock items → 8xx family). Owned by
  the stock team. Reference only.
- Items are never deleted — Lifecycle = Blocked.

## 8. Governance gates (for any request flow)

G1 search before creating (Thai common name, English/brand/model, old code) →
G2 required fields (name per §3, Group+Sub, Base UoM, Pack if needed, reason if a
near match exists) → G3 central steward approves and is the only one who issues
a number. SLA 2 working days.

## Reviewing a change

Grep the diff for `\b`, `NFKC`, `max(`, direct writes to a code field, new
regexes over Thai text, and hardcoded taxonomy. For each rule touched, run its
test or say plainly that none exists. Report each violation with file:line, the
rule, and a concrete example of the wrong data it would produce.

## Sources

Full documents: `docs/group-standard/` in the item-request-portal repo
(GROUP_HANDOVER, UoM Standard, Governance, Cutover Plan, Restructure Proposal).
Reference implementation: `app/services/` in the same repo (codegen, naming,
units, snapshots, categorizer).
