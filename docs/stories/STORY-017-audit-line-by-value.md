# STORY-017: Audit line: quote the `--by` value or allow only a set of characters

Status: todo · Depends on: `story/006-reset-password-cli` (`clean_by`) · Not a go-live condition (Peter, 2026-10-27)
Triage: needs-triage

## Why
`python -m app.unblock_ip` and `python -m app.reset_password` write who
acted (`--by`) into a `key=value` audit line (`login_ip_unblocked ip=… by=…`,
`account_admin by=cli:… action=… target=…`). The audit trail must be true:
a name must not be able to add or hide a field. `auth.clean_by` refuses
`=` and the fullwidth `＝` (U+FF1D) by name, which narrows the problem but
does not close it (review of `1031004..94ab3e4`, 2026-10-27, items 2 and 9).

## Scope
Fix it in the log line itself, once, instead of adding look-alikes forever:
1. Other look-alikes still pass `clean_by`: `﹦` (U+FE66), `⁼` (U+207C),
   `₌` (U+208C)… `--by 'x action﹦deactivate target⁼boss@x'` reads as extra
   fields to a person or a lenient parser. (review item 2)
2. Zero-width and bidi control characters (U+200B, U+202E) pass and are
   written as-is: a log viewer can show the name and the fields after it in
   a different order than they are stored. (review item 9)

Options to weigh at triage:
- **Quote the value** in the line (e.g. `by=%s` with `ascii()` / `repr`, or
  JSON-style quoting), so nothing inside it can read as a separator; keeps
  Thai names possible (escaped).
- **An allowlist** of name characters (Thai, Latin letters, digits, space,
  `.`, `-`, `(`, `)`), refused with exit 1 otherwise; the line stays plain.
Either way, keep `_one_line`'s CR/LF rule and the `cli:` prefix.

## Out of scope
- The web audit lines (`by=<email>`): emails are validated on create.
- Structured (JSON) logging for the whole app.

## Acceptance criteria
_(at triage)_

## Files likely touched
`app/services/auth.py` (`clean_by`, the two audit lines), `app/unblock_ip.py`,
`app/reset_password.py`, `tests/test_reset_password_cli.py`,
`tests/test_login_ip_hardening.py`, README "When things break".

## Domain rules that apply
- HANDOFF §6.2: never NFKC on Thai text (no NFKC to catch look-alikes).
- CLI messages stay ASCII (a piped Windows window writes cp1252; see the
  cp1252 test in `tests/test_reset_password_cli.py`).

## Plan
_(filled by /to-spec + /to-tickets)_

## Notes
