"""Reset an Account's password from the command line (STORY-006 part B prep):
for an Administrator locked out with no other Administrator to reset them.

Run: python -m app.reset_password <email> --by "<your name>"
Run it only in an interactive shell: the temporary password is printed once
to this window. Never as a one-off job or run command whose output the
platform keeps as a log, or the password stays in that log.

Same reset as the Account admin page: changed at the next login, every open
session ends, the lockout is cleared. The log line says who reset whom,
never the password. --by is required: on a container the OS user is usually
root, which says nothing about who.

Exit codes: 0 reset, 1 bad input (no --by, unknown email, deactivated Account).
"""

import argparse
import sys
from collections.abc import Callable

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.logging_setup import setup_logging
from app.services.auth import AuthError, reset_password_from_cli


class _BadInput(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        # argparse would exit with 2; every bad input here is 1.
        raise _BadInput(message)


def run(db: Session, argv: list[str], out: Callable[[str], None] = print) -> int:
    """Parse `argv`, reset the password, show it once. Returns an exit code."""
    parser = _Parser(prog="python -m app.reset_password",
                     description="Reset an Account's password to a temporary one.")
    parser.add_argument("email", help="the Account's email")
    parser.add_argument("--by", required=True, help="your name: who is resetting it")
    try:
        args = parser.parse_args(argv)
        temporary = reset_password_from_cli(db, args.email, by=args.by)
    except (_BadInput, AuthError) as e:
        out(f"Error: {e}")
        out(parser.format_usage().strip())
        return 1
    out(f"Password reset for {args.email.strip().lower()}. It must be changed at the next login.")
    out(f"Temporary password (shown once, write it down now): {temporary}")
    return 0


if __name__ == "__main__":
    setup_logging()  # the line saying who reset whom; never the password
    with SessionLocal() as session:
        sys.exit(run(session, sys.argv[1:]))
