# Problem Statement — Item Request Portal

## The problem (1 paragraph)

Peter (procurement) is the single bottleneck for creating purchase items in AX for 11 factories across 2 item-code systems (each with its own code pattern rules). Requests arrive via Microsoft Forms; Peter manually checks each request for duplicates against AX, generates an item code following the rules of the target system, creates the item in AX, and notifies the requester. At 200–1,000 requests/month this consumes hours per day, and every step (duplicate check, code generation, notification) is manual and error-prone.

## Users

| Role | Count | What they do in the system |
|---|---|---|
| Factory requester | ~11 factories, multiple users each | Submit item requests via web form, see live duplicate warnings, track request status |
| Procurement (Peter) | 1 (possibly +1 backup) | Review queue, resolve duplicate candidates, approve/reject, generate/override item codes, export AX import file, mark as created |

Login: Azure AD / Microsoft 365 SSO.

## Success metrics (measurable)

- Time from request submission to item created drops from days to < 1 working day for standard cases.
- Peter's hands-on time per item drops from ~X min to < 1 min (approve click + batch export).
- Duplicate items created in AX: near zero (system flags candidates before submission and before approval).
- Requesters stop asking "is my item ready yet?" — status is self-service.

## Core flow (v1)

1. Requester logs in (Azure AD), fills web form with controlled dropdowns (factory, category, unit, target system).
2. System checks for duplicates in real time against AX item master (fuzzy match on name/spec) and warns before submission.
3. Request enters procurement queue with duplicate candidates pre-listed.
4. Peter approves → system generates item code from per-system rule config (Peter can override for judgment cases).
5. Approved items batch-exported as AX import file (per factory/system template).
6. Peter imports into AX, marks batch as created → system emails requesters with their item codes; status visible in web.
7. Full audit trail on every request.

## Key design decisions (agreed in discovery)

- **Human-in-the-loop, no direct AX write.** System produces AX import files; Peter imports manually. Safest, no AX-side integration project needed.
- **Duplicate-check data source:** AX DB read-only query — but access requires IT approval (see risks).
- **Code generation:** rule engine driven by per-system config, not hardcoded; deterministic cases fully automated, judgment cases show a suggested code Peter can edit.
- **Running-number safety:** system must sync the latest item numbers from AX before generating codes, because items may still be created manually in AX in parallel.

## Must-not-lose capabilities (from current workflow)

- Peter's final say on every item (approve/override) — the system assists, never auto-creates.
- Ability to handle judgment cases that don't fit the standard rules.
- A record of who requested what (Forms currently provides this) — replaced by audit trail.

## Risks / dependencies

- **AX DB read access is not yet granted (IT request pending).** Fallback for v1: Peter uploads a periodic item-master export (Excel/CSV) as the duplicate-check source; swap to live DB query when access is granted. The duplicate-check module must be built behind an interface so the source can change without touching the rest.
- Item-code rules for both systems must be written down precisely before the rule engine is built (Phase 1 task with Peter).
- AX import file template(s) must be confirmed working with a small test batch before go-live.

## Out of scope for v1

- Direct write to AX (API/DB) — revisit only if import-file flow proves painful.
- Editing/deactivating existing items.
- Approval workflow beyond procurement (e.g., factory-manager pre-approval).
- Teams notifications (email + in-web status only for v1).
- Reporting/analytics dashboards beyond the request queue.
