# Architecture — Item Request Portal

Updated 2026-11-03 to match the code on master. Why each choice was made:
`docs/decisions.md`. Status and how to run: `docs/HANDOFF.md`.

## Stack & why
| Choice | Reason |
|---|---|
| FastAPI + SQLAlchemy + Alembic | One-person maintainable; schema changes only through migrations |
| PostgreSQL 16 (production, CI) / SQLite (development) | Real constraints and row locks in production; zero setup on a laptop |
| HTMX + Jinja2 | Forms/lists/queue app; one language, no build step |
| One Docker container, one uvicorn worker | Simple to host; one worker keeps the mail limiter within Exchange's per-mailbox rate (README "Deploying") |
| Microsoft Graph for email | Company mailbox, no SMTP server (STORY-002) |
| Render/Railway, or a company VM | Decided 2026-07-24 for the pilot; re-check against company data policy before deploy (HANDOFF §7) |

## Layers
`app/routes/` (HTTP, role guards) → `app/services/` (all business logic) →
`app/models/core.py` (tables). Templates in `app/templates/`, reference data
in `app/data/*.json` loaded by `python -m app.seed` (safe to re-run).
Command-line tools: `app.create_admin`, `app.unblock_ip`, `app.reset_password`.

## Data model (`app/models/core.py`)
| Table | Purpose |
|---|---|
| `accounts` | Logins: Role `requester` / `procurement` / `administrator`; a Requester belongs to one Plant; deactivated, never deleted; lockout and session version |
| `login_ip_failures` | Failed logins per client IP (limit against password spraying) |
| `factories` | The 4 Plants (CBD, APM, APG, ACM) |
| `code_systems`, `factory_code_systems` | Code systems and which Plant may use which; only `CENTRAL` is active (legacy/stock systems kept inactive) |
| `code_groups` | Category / Sub-Category tree per code system, editable config |
| `running_register` | **The central running number per Category+Sub** — the only source of central codes |
| `retired_codes` | Central codes issued then thrown away: never reused |
| `item_requests` | One request: requester, Plant, category, name parts, status, issued code |
| `request_events` | Append-only audit trail of each request |
| `item_snapshot`, `snapshot_imports` | Uploaded item-master copies (duplicate check, "is this code already in the master") and the audit of each upload |
| `export_batches` | One generated import file per Plant |
| `search_terms`, `uoms`, `uom_aliases`, `procurement_categories`, `group_export_map`, `mail_domains` | Reference data edited on the admin pages |

Request status: `submitted → in_review → approved → exported → created → notified`,
plus `needs_info` (Requester edits and resubmits) and `rejected`.

## Code generation (`app/services/codegen.py`)
- Central code: `[Group 3][Sub-Category 2][00][Running 4]`, e.g. `90099001234`.
- The next number comes **only** from `running_register`, under a row lock,
  at approval. Before taking it, the portal checks the number is not a
  Retired Code, not on another request and not in the group master; if it
  is, it refuses (the register is behind, STORY-005) instead of skipping.
- An Administrator can override a code (STORY-010): checked against the
  register and the master; thrown-away numbers go to `retired_codes`.
- Legacy code systems still have a `max(existing) + 1` engine, but they are
  inactive (stock is out of scope). Never use it for central codes
  (HANDOFF §6.4).

## Duplicate check (`app/services/snapshots.py`)
Token prefilter in SQL, then trigram similarity in Python, against the
uploaded snapshot. Portable across SQLite and PostgreSQL; can move to
`pg_trgm` later without changing callers. Thai text: NFC + `fix_thai`,
never NFKC (HANDOFF §6.2).

## How it runs
- Local: `start.bat`, or the steps in HANDOFF §4 (SQLite), or
  `docker compose up` (app + PostgreSQL).
- Container start: `alembic upgrade head` → `python -m app.seed` → uvicorn,
  one worker, `--no-proxy-headers` (the app reads `X-Forwarded-For` itself,
  from `FORWARDED_ALLOW_IPS` only).
- CI (`.github/workflows/ci.yml`, every push): PostgreSQL 16, migrations +
  seed on an empty database, `alembic check` for schema drift, the whole
  test suite including the PostgreSQL tests.
- Production: **not deployed yet** (STORY-006 part B). Logs, backups and
  restore are part of that work and have not been set up or tested.

## External dependencies
- Item-master snapshots are uploaded by hand (Excel). A stale snapshot means
  the duplicate check misses new items. Today's snapshot is `Central_v4`,
  without DCM items (HANDOFF §4).
- Microsoft Graph (`Mail.Send`) for email. If it fails, statuses are still
  visible on the web and unsent mails can be resent.
- Anthropic API, optional: search-name suggestions; without a key the
  dictionary is used.
- AX/D365: no connection. The portal only produces import files.
