# HANDOFF — Item Request Portal

> For any new Claude Code session or agent: read `docs/IT-HANDOVER.md`, this
> file, `CLAUDE.md`, `CONTEXT.md`, and `docs/decisions.md` before doing
> anything. If chat history contradicts these files, the files win.
>
> Last updated: 2026-11-03 · Owner: Peter (Procurement Strategy, Carabao Group)
> until 2026-11-13, when Peter leaves; then the IT team (`docs/IT-HANDOVER.md`).
> The goal now is handover, not go-live.

---

## 1. What this is

Web app where factory staff at 4 plants (CBD, APM, APG, ACM) request new
**non-stock and service** purchase items. The portal checks for duplicates,
suggests a category, composes the standard name, issues a central 11-digit
code on approval, and exports AX/D365 import files per plant.

It replaces: Microsoft Forms → Peter checks manually → types into AX → emails back.

## 2. Status

**Built and running on Peter's machine, with login and roles (STORY-001, done
2026-09-30), validated code override (STORY-010, done 2026-10-01), email
notification (STORY-002, done 2026-10-14), requester resubmit (STORY-009,
done 2026-10-19) and the Name Prefix on category moves (STORY-013, done
2026-10-21). Not yet open to the plants.**

**Goal now: handover, not go-live (Peter, 2026-10-27).** Peter leaves on
2026-11-13. The aim until then is that the next owner can pick the portal
up from these files alone; opening it to the plants is the next owner's.

**Go-live condition: Cutover Plan phase 1 first.** The group central master
(`Central_v5_with_DCM`, 13,400 codes) is **not yet loaded into D365**, and
the plants still open items in the old system. The portal may open only
after phase 1 of the Cutover Plan. Items opened in the old system after
2026-08-07 (after the v5 master was cut) need a delta before cutover. The
successor picks the route (`Rule of Item/Handover 2026-11/04-pipeline-master-กลาง.md`
on the PurchaseWFH team site, `docs/IT-HANDOVER.md` C3; Peter's OneDrive copy
is deleted when his account closes):
option A, the delta goes through the portal, which issues the numbers
itself; option B, the delta goes through the group pipeline and the
register is then re-synced (STORY-005), otherwise the portal and the delta
issue the same numbers.

**Never re-run the whole group pipeline once v5 codes are in use.** The
pipeline issues every code afresh, so existing codes may shift. A delta
must keep every v5 code as it is (details: the same
`04-pipeline-master-กลาง.md` on the team site).

Besides the cutover, it still has to be deployed (STORY-006). **All code
prerequisites of the deploy are done**; left:
1. IT's Graph values for email (§7); outside `APP_ENV=dev` the app refuses
   to start without them, so STORY-006 waits for them.
2. STORY-006 itself (Render/Railway + PostgreSQL), split on 2026-10-21.
   **Part A done (2026-10-26):** CI on PostgreSQL 16 with a schema-drift
   check, race tests, login limit per Account and per client IP with
   "being checked" slots, one worker, the `unblock_ip` command. Whole-branch
   review with no (ก), Peter's browser checklist passed
   (`docs/stories/STORY-006/part-a-browser-checklist.md`). Merged to master
   as `390e9a0` (2026-10-26); CI on master green, 939 passed, 0 skipped
   (Peter, from the run). Branch deleted. **Part B waits for IT:** deploy, backup/restore,
   real email, plus the part B notes in the story (where the `unblock_ip`
   and `reset_password` log lines land on the platform, whether its shell
   output is kept as a log, choosing `FORWARDED_ALLOW_IPS`).

Operating the login limit (README "When things break"): 50 failed logins
from one client IP in 15 minutes block it for 15 minutes; the log line is
`login_ip_blocked ip=… until=… UTC` (`app.accounts`). Lift early with
`python -m app.unblock_ip <ip> --by "<your name>"` (exit 0 lifted, 1 bad
input or no `--by`, 2 not blocked); it logs `login_ip_unblocked ip=… by=…`
to its own window. On the dev machine there is no log file: the app logs
to the window running `uvicorn`.

An Administrator locked out with no other Administrator to reset them:
`python -m app.reset_password <email> --by "<your name>"` (README "When
things break"; interactive shell only, it prints the temporary password).
Administrators only (any other Account: the Account admin page); exit 0
reset, 1 bad input. Built ahead of part B on `story/006-reset-password-cli`,
merged to master as `7325bc9` (2026-10-27); CI on master green, 953
passed, 0 skipped (Peter, from the run). Branch deleted.

`FORWARDED_ALLOW_IPS`: the proxy IPs/CIDRs whose `X-Forwarded-For` is
believed, or `none` if clients connect directly. Required outside
`APP_ENV=dev` (the app, migrations and `create_admin` refuse to start
without it); `*` is refused. A wrong value is not caught: part B must check
on the deployed app that two machines count as two IPs. If the platform
does not publish its proxy IPs, see the "trust one hop" option in STORY-006
Further Notes. A stray comma is ignored; only commas count as unset
(STORY-015 item 21, done on `story/006-reset-password-cli`).

**Never move `dev.db` data to production.** It holds test Administrator
Accounts (`temp.admin@test.local`, `temp2.admin@test.local`) and test
requests. It was migrated to head on 2026-10-26; the backup taken before
was deleted after master's CI was green (Peter). `*.db.bak-*` is ignored
by git for the next backup.

Open work after part A (none is a go-live condition):
- STORY-015: login-limit and review follow-ups (items 1–42).
- STORY-017: quote the `--by` value in the CLI audit lines.
- STORY-016: re-check the acting Administrator under the lock: **first
  story after go-live**.
- CI pinned to `ubuntu-24.04` (below).
- Pydantic class-based `Config` (below).

After the plants open: STORY-014 (the name preview shows the saved name).

Open item (noted 2026-10-23, Peter accepted the impact): login "being
checked" slots (`pending_checks` / `pending_since` on `accounts` and
`login_ip_failures`, STORY-006 ticket 08) are one counter and one time per
row, with no identity per slot. When they expire (1 minute after the count
went 0 → 1) all are cleared, including ones taken a moment ago by logins
still running, and those logins' later frees take others' slots. Accepted
impact: on an Account it cannot happen in practice (the 10-failure lock
empties the slots long before a minute); on a busy IP (a plant whose
successful logins keep a slot in use) up to about one more limit's worth of
in-flight attempts can pass at the moment of a block. The exact fix is one
row per slot (key, token, taken_at): a new table and migration. Revisit if
a block is ever seen to let through far more than 50 failures.

Open small item (noted 2026-10-23): CI is pinned to `ubuntu-24.04`
(`.github/workflows/ci.yml`) because `ubuntu-latest` moves to Ubuntu 26
from 2026-10-19. Move CI to Ubuntu 26 on purpose after go-live, as its own
change with a green run.

Open small item (not fixed, noted 2026-10-21): `app/config.py` `Settings`
uses a class-based `Config`, which Pydantic 2 warns is deprecated
(`PydanticDeprecatedSince20`, removed in V3). Move to
`model_config = SettingsConfigDict(env_file=".env")` before any Pydantic 3
upgrade; check `.env` is still read.

| Area | State |
|---|---|
| Request form (structured fields, live name preview) | done |
| Duplicate check (trigram fuzzy vs item master snapshot) | done |
| Category suggestion (learns from 13,391 classified items) | done — 60% top-1, 68% top-3 on holdout |
| Search-name suggestion (dictionary + master neighbours + optional LLM) | done |
| Size / UoM cleaning | done (UoM still the old 5 units — see STORY-003) |
| Central 11-digit code from running register | done — minting refuses when the next number is retired, on a request or in the group master (register behind → STORY-005) |
| Code override / Retired Codes | done — STORY-010: two-step override checked against the group master, register moves up, thrown-away numbers kept in `retired_codes` (never reused) |
| Naming standard `[CATEGORY] - [name] - [detail]` | done — STORY-013: one Name Prefix rule (`naming.starts_with_prefix` / `searchable_part`), a category move swaps the prefix, the queue warns when a name does not fit its category, Name Override ≤ 110, seed refuses a bad prefix |
| Export to 4 plant import templates | done — **never tested against real AX** |
| Admin config pages | done |
| Login / roles | done — STORY-001: login, role guards, Administrator-only register actions, Account admin, password change + 8 h expiry, lockout, My requests |
| Email notification | done — STORY-002 tickets 01–06 (Graph sender tested with a fake transport only; first real send waits for IT, see §7) |
| Requester resubmit | done — STORY-009: Requester or Originator edits and resubmits a Needs Info request (conditional claim, one 409 for the loser), queue badge + reply card + replaced-name warning, best-effort email to Procurement; the code system must now fit the request's Plant (fix also for new requests) |
| Deployment | part A done (CI on PostgreSQL, race tests, login limits, one worker; merged `390e9a0`) — part B (deploy, backup, real email) waits for IT — STORY-006 |

Tests: 916 passing locally, 37 PostgreSQL tests skipped without
`TEST_POSTGRES_URL`; CI runs all 953 on PostgreSQL 16 (confirmed by Peter
from the run on master `7325bc9`, 2026-10-27, and again on master `38ab22e`
after the docs/handover-status merge). Read CI numbers from the run's log
itself, never from a summary: `f429488` was once recorded green and was red.

The suite ran in ~13 s on 2026-10-21 but took ~61 s on 2026-10-26 (cause
not looked into; the 3 subprocess tests take 2–4 s each). The suite's setup:
`create_all` + `seed` run once per pytest session
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

First-time setup: `python -m venv .venv` then `pip install -r requirements-dev.txt`
(it includes `requirements.txt`, plus pytest-timeout for `pytest.ini`).
Peter's machine has Python 3.13 from python.org on PATH (Sep 2026). If `python`
prints nothing, it is the Microsoft Store stub — check with `where.exe python`.

After first run, upload in **Snapshot** page:
1. `Carabao_Group_Item_Master_Central_v4.xlsx` → "Master ที่จัดหมวดแล้ว" (enables category suggestion)
2. Legacy item master export → CBD / D365 snapshot (enables duplicate check)

(`Central_v5_with_DCM.xlsx` is IRM-encrypted and cannot be read by code.)
So the snapshot in use is `Central_v4`, which has **no DCM items**: the
duplicate check and any re-check against the master do not see DCM items.
Upload an unencrypted copy of v5 instead once one is available.

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
9. **Never find the CATEGORY by "everything before the first ` - `".** A Name
   Override need not start with a prefix (`Ball Bearing SKF - 20 L`), so that
   cuts a real name. Use `naming.starts_with_prefix` / `searchable_part` /
   `swap_prefix` with the Sub-Category's prefix (STORY-013).

## 7. Open decisions and outside steps (not code)

Until 2026-11-13 Peter; after that the role named in **who** (roles:
`docs/IT-HANDOVER.md` C1).

- Test-import 1–2 exported rows into real AX/D365 (STORY-005 depends on it)
  — **who:** `[BUSINESS-OWNER]` with the AX/D365 team
- In that test, also import a code that already exists in one D365 company
  (e.g. APG) into another (e.g. APM), and record what AX/D365 does (refuses,
  releases, or duplicates). The result decides whether the override check
  on a D365 match goes back from a warning to a refusal (STORY-012)
  — **who:** `[BUSINESS-OWNER]`
- Send a sample D365 item export showing the company / legal-entity column
  (STORY-012 is blocked on it) — **who:** `[BUSINESS-OWNER]`
- Email (STORY-002) — **who:** `[IT-OWNER]`. Ask IT for: an App Registration with the `Mail.Send`
  **application** permission + admin consent, and an Application Access
  Policy that limits it to one shared sender mailbox (e.g.
  `item-portal@carabao.co.th`). Then provide `MS_TENANT_ID`, `MS_CLIENT_ID`,
  `MS_CLIENT_SECRET`, `MAIL_SENDER`; plus `MAIL_REPLY_TO` (Procurement mailbox for
  replies) before deploy. Outside `APP_ENV=dev` the app refuses to start
  without the four Graph values, so deploy cannot go ahead before IT sends them. Steps are spelled out in `.env.example`. Then send
  one real test email (any request through needs_info) and check it arrives,
  with the Reply-To and the copy in the sender's Sent Items. Allowed originator email domains are data on the
  Settings page (seeded: apm.co.th, acmf.co.th, apg.co.th, carabao.co.th)
- **External hosting policy (STORY-006 AC 6)** — **who:** `[IT-OWNER]`:
  whether company data policy allows item data on an external host. If not, the deploy platform changes (company VM, see
  decisions.md 2026-07-24), so get the answer before choosing Render/Railway
  in part B. Answer: _(fill in)_
- **Client secret expiry** — **who:** `[IT-OWNER]`: an Azure client secret has an end date (often
  6–24 months). Note it here when IT creates it and renew it before that
  date — after it expires every email fails with "Graph credentials do not
  work". Secret expires on: _(fill in)_
- ~~Fill the Decision Sheet (D1–D4)~~ **Done and applied since 2026-08-06:**
  `Decision_Sheet_v2_corrected` → group pipeline → `Central_v4` →
  `Central_v5_with_DCM` (final, 13,400 codes). The register the portal was
  seeded from (`Running_Number_Register_v1`) refers to v5.
- The cut-over date after which **only** this portal issues central codes —
  until then, codes issued by hand elsewhere will collide with the register.
  It comes after Cutover Plan phase 1 and the delta of items opened in the
  old system since 2026-08-07 (§2) — **who:** `[BUSINESS-OWNER]`
- The delta route, option A (through the portal) or B (through the
  pipeline, then STORY-005) (§2) — **who:** `[BUSINESS-OWNER]`
- Which taxonomy is current: 105 sub-categories in the v4 file vs 130 in
  the portal (STORY-005 note 2) — **who:** `[BUSINESS-OWNER]`
- Verify `700-02`, `901-06`, `906-02` against an unencrypted copy of v5
  (STORY-005 note 1) — **who:** `[BUSINESS-OWNER]`
- Complete reference lists: UoM confirmation, procurement categories,
  group → D365 ItemGroupId mapping — **who:** `[BUSINESS-OWNER]`

## 8. Working with the owner

How Claude works with the user (language, plans, merges, CI, tests) is in
`CLAUDE.md` ("Working with the user", "Working rules"). One rule kept here:

- **No merge on red CI.** No branch protection is set up (on GitHub Free a
  private repo cannot have it), so a red CI run does not block the merge
  button: whoever approves the merge (`[IT-OWNER]`) checks the CI result
  first (decided 2026-10-21). Turn on branch protection after the repo move
  if the plan allows (`docs/IT-HANDOVER.md` A5).
