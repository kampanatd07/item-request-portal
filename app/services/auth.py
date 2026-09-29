"""Accounts and password authentication.

Only this module touches password hashes. Login failures are deliberately
indistinguishable (same message, same work) so the form cannot be used to
find out which emails have an Account.
"""

from functools import lru_cache

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import ROLES, Account, Factory

MIN_PASSWORD_LENGTH = 12
LOGIN_FAILED = "อีเมลหรือรหัสผ่านไม่ถูกต้อง"


class AuthError(Exception):
    """Auth error with a user-facing Thai message."""


@lru_cache
def _hasher(time_cost: int, memory_cost: int, parallelism: int) -> PasswordHasher:
    return PasswordHasher(time_cost=time_cost, memory_cost=memory_cost, parallelism=parallelism)


def _current_hasher() -> PasswordHasher:
    return _hasher(settings.argon2_time_cost, settings.argon2_memory_cost,
                   settings.argon2_parallelism)


@lru_cache
def _dummy_hash(time_cost: int, memory_cost: int, parallelism: int) -> str:
    # Same cost parameters as real hashes, so verifying against it takes as long.
    return _hasher(time_cost, memory_cost, parallelism).hash("dummy password for timing")


def has_role(account: Account, minimum: str) -> bool:
    """True if the Account's Role is `minimum` or higher (ROLES is lowest → highest)."""
    return ROLES.index(account.role) >= ROLES.index(minimum)


def hash_password(password: str) -> str:
    return _current_hasher().hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _current_hasher().verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def normalize_email(email: str) -> str:
    return email.strip().lower()


def check_password_rules(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise AuthError(f"รหัสผ่านต้องมีอย่างน้อย {MIN_PASSWORD_LENGTH} ตัวอักษร")


def create_account(
    db: Session,
    email: str,
    display_name: str,
    role: str,
    password: str,
    factory_id: int | None = None,
    must_change_password: bool = True,
) -> Account:
    """Create an Account. A Requester needs a Plant; other Roles must not have one."""
    email = normalize_email(email)
    display_name = display_name.strip()
    if "@" not in email:
        raise AuthError("รูปแบบอีเมลไม่ถูกต้อง")
    if not display_name:
        raise AuthError("กรุณาระบุชื่อ")
    if role not in ROLES:
        raise AuthError("บทบาทไม่ถูกต้อง")
    if role == "requester":
        if factory_id is None or db.get(Factory, factory_id) is None:
            raise AuthError("ผู้ขอต้องสังกัดโรงงาน")
    elif factory_id is not None:
        raise AuthError("เฉพาะผู้ขอเท่านั้นที่สังกัดโรงงาน")
    check_password_rules(password)
    if db.scalar(select(Account).where(Account.email == email)) is not None:
        raise AuthError("อีเมลนี้มีบัญชีอยู่แล้ว")

    account = Account(
        email=email,
        display_name=display_name,
        role=role,
        factory_id=factory_id,
        password_hash=hash_password(password),
        must_change_password=must_change_password,
    )
    db.add(account)
    db.commit()
    return account


def authenticate(db: Session, email: str, password: str) -> Account:
    """Return the active Account for these credentials, or raise one generic AuthError."""
    account = db.scalar(select(Account).where(Account.email == normalize_email(email)))
    if account is None:
        # Burn the same hashing time as a real check (AC6).
        verify_password(_dummy_hash(settings.argon2_time_cost, settings.argon2_memory_cost,
                                    settings.argon2_parallelism), password)
        raise AuthError(LOGIN_FAILED)
    if not verify_password(account.password_hash, password) or not account.active:
        raise AuthError(LOGIN_FAILED)

    # Upgrade old hashes in place when the cost parameters are raised.
    if _current_hasher().check_needs_rehash(account.password_hash):
        account.password_hash = hash_password(password)
        db.commit()
    return account
