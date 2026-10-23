"""Lift a login block on a client IP (STORY-006 ticket 08).

Run: python -m app.unblock_ip <ip> --by "<your name>"
The IP is the one in the `login_ip_blocked ip=...` log line ("unknown" for the
shared bucket; any address of an IPv6 /64 lifts that /64). --by is required:
on a container the OS user is usually root, which says nothing about who.

Exit codes: 0 unblocked, 1 bad input (not an IP, no --by), 2 that IP is not
blocked (nothing changed).
"""

import argparse
import sys
from collections.abc import Callable
from datetime import datetime

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.services.auth import AuthError, unblock_ip


class _BadInput(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        # argparse would exit with 2, which here means "not blocked".
        raise _BadInput(message)


def run(db: Session, argv: list[str], out: Callable[[str], None] = print,
        now: datetime | None = None) -> int:
    """Parse `argv`, lift the block, report. Returns an exit code. `now` is
    for tests (default: the current time)."""
    parser = _Parser(prog="python -m app.unblock_ip",
                     description="Lift a login block on a client IP.")
    parser.add_argument("ip", help='the IP from the login_ip_blocked log line, or "unknown"')
    parser.add_argument("--by", required=True, help="your name: who is lifting the block")
    try:
        args = parser.parse_args(argv)
        lifted = unblock_ip(db, args.ip, by=args.by, now=now)
    except (_BadInput, AuthError) as e:
        out(f"Error: {e}")
        out(parser.format_usage().strip())
        return 1
    if not lifted:
        out(f"{args.ip} is not blocked. Nothing changed.")
        return 2
    out(f"Unblocked {args.ip}.")
    return 0


if __name__ == "__main__":
    with SessionLocal() as session:
        sys.exit(run(session, sys.argv[1:]))
