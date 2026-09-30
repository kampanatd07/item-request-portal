"""The single source of "now" for auth.

Session expiry and login lockout depend on time; reading it through one
injectable function lets tests move the clock instead of sleeping.
"""

from collections.abc import Callable
from datetime import datetime, timezone

Clock = Callable[[], datetime]


def utc_now() -> datetime:
    """Naive UTC, matching how the DB stores DateTime columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def get_clock() -> Clock:
    """FastAPI dependency; tests override it with a fixed or movable clock."""
    return utc_now
