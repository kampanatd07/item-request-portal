"""Create an Administrator from the command line (bootstraps the first login).

Run: python -m app.create_admin
The password is read with getpass (never echoed, never in shell history)
and asked twice.
"""

import getpass
import sys
from collections.abc import Callable

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.services.auth import AuthError, create_account


def run(
    db: Session,
    ask: Callable[[str], str] = input,
    ask_secret: Callable[[str], str] = getpass.getpass,
    out: Callable[[str], None] = print,
) -> int:
    """Prompt for the Administrator's details and create the Account. Returns an exit code."""
    email = ask("Email: ")
    display_name = ask("Display name: ")
    password = ask_secret("Password (min 12 characters): ")
    if ask_secret("Confirm password: ") != password:
        out("Passwords do not match. No Account created.")
        return 1
    try:
        account = create_account(
            db, email, display_name, "administrator", password,
            # They chose this password themselves, so no forced change.
            must_change_password=False,
        )
    except AuthError as e:
        out(f"Could not create Account: {e}")
        return 1
    out(f"Administrator created: {account.email}")
    return 0


if __name__ == "__main__":
    with SessionLocal() as session:
        sys.exit(run(session))
