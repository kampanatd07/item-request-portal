# HANDOFF — Item Request Portal

> For any new Claude Code session or agent: read this file, `CLAUDE.md`, `CONTEXT.md`, and
> `docs/decisions.md` before doing anything. If chat history contradicts these
> files, the files win.
>
> Last updated: 2026-10-14 · Owner: Peter (Procurement Strategy, Carabao Group)

---

## 1. What this is

Web app where factory staff at 4 plants (CBD, APM, APG, ACM) request new
**non-stock and service** purchase items. The portal checks for duplicates,
suggests a category, composes the standard name, issues a central 11-digit
code on approval, and exports AX/D365 import files per plant.

It replaces: Microsoft Forms → Peter checks manually → types into AX → emails back.

## 2. Status

**Built and running on Peter's machine, with login and roles (STORY-001, done
2026-09-30), validated code override (STORY-010, done 2026-10-01) and email
notification (STORY-002, done 2026-10-14). Not yet open to the plants** — it
still has to be deployed (STORY-006), which now waits for requester resubmit
(STORY-009, must ship before the plants get access) and IT's Graph values (§7).

| Area | State |
|---|---|
| Request form (structured fields, live name preview) | done |
| Duplicate check (trigram fuzzy vs item master snapshot) | done |
| Category suggestion (learns from 13,391 classified items) | done — 60% top-1, 68% top-3 on holdout |
| Search-name suggestion (dictionary + master neighbours + optional LLM) | done |
| Size / UoM cleaning | done (UoM still the old 5 units — see STORY-003) |
| Central 11-digit code from running register | done — minting refuses when the next number is retired, on a request or in the group master (register behind → STORY-005) |
| Code override / Retired Codes | done — STORY-010: two-step override checked against the group master, register moves up, thrown-away numbers kept in `retired_codes` (never reused) |
| Naming standard `[CATEGORY] - [name] - [detail]` | done |
| Export to 4 plant import templates | done — **never tested against real AX** |
| Admin config pages | done |
| Login / roles | done — STORY-001: login, role guards, Administrator-only register actions, Account admin, password change + 8 h expiry, lockout, My requests |
| Email notification | done — STORY-002 tickets 01–06 (Graph sender tested with a fake transport only; first real send waits for IT, see §7) |
| Deployment | **not started — STORY-006** |

Tests: 609 passing (`pytest`).

The suite runs in ~13 s: `create_all` + `seed` run once per pytest session
into an in-memory template, and each test's `db_session` gets a copy through
the SQLite backup API (`tests/conftest.py`; `tests/test_template_db.py`
guards that a copy equals a fresh seed and that copies are isolated). Tests
pass in random order too (checked with pytest-randomly, not installed).
`pytest.ini` sets `timeout = 60` (pytest-timeout, in `requirements-dev.txt`)
so a hung test fails with stack traces instead of stalling the run.

## 3. Group standard this app implements

Source documents live in `docs/group-standard/`. The approved standard:

- **Code**: `[Group 3][Sub-Category 2][Item Type 2 = 00][Running 4]`, one code per
  item across all plants. Sub-Category ≥ 01 keeps central codes disjoint from
  the 11,377 legacy ACM/APM/APG codes (which all have `0000` in digits 4-7).
- **Name**: `[CATEGORY] - [ชื่อสินค้า/บริการ] - [รายละเอียดจำเพาะ]`, ≤ 110 chars,
  ` - ` the only separator, number + unit spaced (`20 L`).
- **Taxonomy**: 20 groups / 130 sub-categories → `app/data/taxonomy.json`
- **Running register**: last number per group+sub → `app/data/running_register.json`,
  loaded into the `running_register` table. **The app owns this register.**
- **Scope**: non-stock (9xx) + service (7xx) only. Stock (CBD 99xx → 8xx) belongs
  to the stock team; its code systems are seeded but `active = False`.

## 4. How to run (Windows)

```powershell
cd D:\dev\item-request-portal          # NOT inside OneDrive — see trap 6.6
.\.venv\Scripts\Activate.ps1           # if blocked: Set-ExecutionPolicy -Scope Process Bypass
$env:APP_ENV = "dev"                    # required locally: unset means production (fails closed)
alembic upgrade head
python -m app.seed                      # must print "Seed complete."
python -m app.create_admin              # first time only: your own Administrator login
uvicorn app.main:app --port 8000
```

First-time setup: `python -m venv .venv` then `pip install -r requirements.txt`.
Peter's machine has Python 3.13 from python.org on PATH (Sep 2026). If `python`
prints nothing, it is the Microsoft Store stub — check with `where.exe python`.

After first run, upload in **Snapshot** page:
1. `Carabao_Group_Item_Master_Central_v4.xlsx` → "Master ที่จัดหมวดแล้ว" (enables category suggestion)
2. Legacy item master export → CBD / D365 snapshot (enables duplicate check)

(`Central_v5_with_DCM.xlsx` is IRM-encrypted and cannot be read by code.)

## 5. Where things are

| Path | What |
|---|---|
| `app/services/codegen.py` | code issuance — central register + legacy engine |
| `app/services/naming.py` | name composition + standard's rules |
| `app/services/units.py` | size normalization |
| `app/services/categorizer.py` | category suggestion + learning from corrections |
| `app/services/classifier.py` | search-name suggestion |
| `app/services/snapshots.py` | master import, `normalize()`, trigram similarity |
| `app/services/exporter.py` | per-plant import file builders |
| `app/seed.py` | idempotent reference data (safe to re-run) |
| `tests/fixtures/` | real AX temp templates — export tests assert header parity |
| `tests/conftest.py` | `central_ids()` helper — use it in every new test |
| `docs/stories/` | the backlog, one self-contained file per story |

## 6. Traps already hit — do not repeat

1. **Never `\b` next to Thai characters.** Thai vowels/tone marks are non-word
   characters, so `\bสี\b` matches inside `สีดำ`. Use `(?<![ก-๙])` / `(?![ก-๙])`.
   Also no `\b` between digit and letter (`25cm` has no boundary).
2. **Never `NFKC` on Thai.** It splits SARA AM (`ำ`) into two characters and
   duplicate detection silently fails. Use `NFC` + `fix_thai()` (in snapshots.py).
3. **Thai has no spaces between words.** Thai dictionary terms match as
   substrings; rank by *position first* (head noun is at the front), length second.
4. **Running numbers come only from `running_register`.** Never compute
   `max(existing)+1` for central codes — the register is the single owner.
5. **Migrations on SQLite need batch mode** for ALTERs (`render_as_batch` is on
   in `env.py`). Autogenerate on a stale DB can emit spurious `create_foreign_key`
   lines — read every generated migration before committing.
6. **OneDrive breaks SQLite and git** (lock files, "Operation not permitted").
   Work from `D:\dev\` (outside OneDrive; C: is nearly full).
7. **Services must not be classified as parts.** `งานซ่อมปั๊มน้ำ` matched pump
   parts and was auto-selected into 900-06 at full confidence. Service markers
   now exclude Item-type categories — keep that guard.
8. **Tests use `create_all`, not migrations.** A migration can be broken while all
   tests pass. After any migration, verify on a fresh DB:
   `rm dev.db && alembic upgrade head && python -m app.seed`.

## 7. Decisions only Peter can make (not code)

- Test-import 1–2 exported rows into real AX/D365 (STORY-005 depends on it)
- In that test, also import a code that already exists in one D365 company
  (e.g. APG) into another (e.g. APM), and record what AX/D365 does (refuses,
  releases, or duplicates). The result decides whether the override check
  on a D365 match goes back from a warning to a refusal (STORY-012)
- Send a sample D365 item export showing the company / legal-entity column
  (STORY-012 is blocked on it)
- Email (STORY-002) — ask IT for: an App Registration with the `Mail.Send`
  **application** permission + admin consent, and an Application Access
  Policy that limits it to one shared sender mailbox (e.g.
  `item-portal@carabao.co.th`). Then provide `MS_TENANT_ID`, `MS_CLIENT_ID`,
  `MS_CLIENT_SECRET`, `MAIL_SENDER`; plus `MAIL_REPLY_TO` (Procurement mailbox for
  replies) before deploy. Outside `APP_ENV=dev` the app refuses to start
  without the four Graph values, so deploy cannot go ahead before IT sends them. Steps are spelled out in `.env.example`. Then send
  one real test email (any request through needs_info) and check it arrives,
  with the Reply-To and the copy in the sender's Sent Items. Allowed originator email domains are data on the
  Settings page (seeded: apm.co.th, acmf.co.th, apg.co.th, carabao.co.th)
- **Client secret expiry:** an Azure client secret has an end date (often
  6–24 months). Note it here when IT creates it and renew it before that
  date — after it expires every email fails with "Graph credentials do not
  work". Secret expires on: _(fill in)_
- Fill `Carabao_Item_Master_Decision_Sheet.xlsx` (D1–D4); the register must be
  re-synced afterwards
- The cut-over date after which **only** this portal issues central codes —
  until then, codes issued by hand elsewhere will collide with the register
- Complete reference lists: UoM confirmation, procurement categories,
  group → D365 ItemGroupId mapping

## 8. Working with Peter

- Thai for conversation, English for code/comments/commits
- Short and direct; give a recommendation with the reason, not a menu
- Report problems plainly with numbers
- Plan first, get confirmation, then build; explain significant decisions in 2–3 sentences
- He approves every merge
