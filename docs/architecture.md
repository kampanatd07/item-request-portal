# Architecture — Item Request Portal

## Stack & why
| Choice | Reason |
|---|---|
| FastAPI + SQLAlchemy + Alembic | One-person maintainable; skills transfer to data/ML serving |
| PostgreSQL | Real constraints + trigram fuzzy search (pg_trgm) for duplicate check |
| HTMX + Jinja2 | Forms/lists/queue app; one language, no build step |
| Docker on Render/Railway | Pilot without IT dependency |

## Data model (proposed — see decisions.md)
| Entity | Purpose |
|---|---|
| users | App accounts (requester / procurement / admin), factory link |
| factories | CBD, APM, APG, ACM → which code systems apply |
| code_systems | 5 systems: CBD_STOCK, CBD_NONSTOCK, D365_STOCK, D365_NONSTOCK, D365_SERVICE — each with a code pattern template |
| code_groups | Selectable group/category values per system (editable config), incl. sub-levels (CBD subcategory, D365 mould type) |
| item_snapshot | Imported item master per system; source for duplicate check + max running number |
| snapshot_imports | Audit of each master upload (file, rows, by whom) |
| requests | One item request: requester, factory, system, group refs, name parts (ชื่อ/แบรนด์/รุ่น/ขนาด/ชนิด/สี), status, generated_code |
| request_events | Append-only audit trail (submitted, flagged-dup, approved, code-generated, exported, created, notified) |
| export_batches | One generated import file: system, file, created_by; items link back to requests |

Status flow: `submitted → in_review → approved → exported → created (in AX/D365) → notified` (+ `rejected`, `needs_info`)

## Code generation
- Pattern templates per system, e.g. D365: `{group}0000{run:4}`; CBD stock: `9905{cat}{sub}{run:4}`; CBD non-stock: `64{cat}{run:6}` (SVSP special-cased in config, mould `806{type:3}{run:5}`)
- Next running = max(existing in item_snapshot ∪ pending approved requests) + 1, computed at approval time inside a DB transaction; unique constraint on generated_code as the last line of defense
- Peter can override any generated code; override is logged

## How it runs
Local: `docker compose up` (app + postgres) | Prod: Render/Railway single container + managed Postgres; logs in platform dashboard; DB backups via platform daily snapshot + weekly pg_dump to storage

## External dependencies
- Item master snapshots uploaded manually (Excel/CSV) — stale snapshot ⇒ duplicate check misses new items; UI shows snapshot age
- SMTP for email notifications — if down, statuses still visible in web
