# Project: Item Request Portal

## What this is
Web app that replaces the manual Microsoft Forms → check → create-in-AX/D365 workflow for purchase item creation. Requesters from 4 factories submit item requests with live duplicate checking; procurement (Peter) reviews, approves, auto-generates item codes per system rules, and exports AX/D365 import files.
Users: Factory requesters (4 factories: CBD, APM, APG, ACM) + procurement (1-2 people)
Status: Phase 2 — slices 1-4 shipped (form+queue, dup-check, codegen, export). Next: search-name AI taxonomy, then notifications+auth.

## Stack
FastAPI + SQLAlchemy + Alembic | PostgreSQL | HTMX + Jinja2 | deploy target: Render/Railway (Docker)

## Architecture rules
- routes → services → models; business logic only in services
- Schema changes only via Alembic migrations
- Every feature ships with tests (happy path + failure path)
- Secrets via env vars only; .env.example stays current
- Duplicate-check + running-number source behind an interface (v1: uploaded snapshot; later: AX DB query)
- Code generation rules are DB config, never hardcoded

## Conventions
- Code, comments, commits: English. UI text: Thai. Chat with user: Thai.
- Type hints on all functions; commit messages explain why
- Branch per slice; red CI blocks merge

## Working with me (the user)
- I'm building engineering skills — briefly explain significant decisions (2-3 sentences)
- Propose a plan before writing features; wait for my confirmation
- Flag problems in existing code but don't fix beyond agreed scope
- Push back when I drift from the out-of-scope list

## Session start
Read docs/decisions.md, check git status, summarize project state in 2-3 lines first.

## Out of scope for v1
- Direct write to AX/D365 (API/DB) — export files only
- Editing/deactivating existing items
- Approval workflow beyond procurement
- Teams notifications (email + in-web status only)
- Reporting dashboards beyond the request queue
- Factories beyond CBD, APM, APG, ACM
