"""Accounts and password authentication.

Only this module touches password hashes. Login failures are deliberately
indistinguishable (same message, same work) so the form cannot be used to
find out which emails have an Account.
"""

import logging
import re
import secrets
from functools import lru_cache

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import ROLES, Account, Factory

MIN_PASSWORD_LENGTH = 12
TEMPORARY_PASSWORD_BYTES = 12  # token_urlsafe -> 16 characters

# Account administration is logged here (who, action, target) until STORY-011
# moves it into the DB. Never pass a password, hash or temporary password.
audit_log = logging.getLogger("app.accounts")
LOGIN_FAILED = "อีเมลหรือรหัสผ่านไม่ถูกต้อง"
# local@domain.tld with no whitespace or control characters anywhere: a line
# break in an email would otherwise let it forge lines in the audit log.
_EMAIL_RE = re.compile(r"[^@\s\x00-\x1f\x7f]+@[^@\s\x00-\x1f\x7f]+\.[^@\s\x00-\x1f\x7f]+")


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
    if not _EMAIL_RE.fullmatch(email):
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


# --- Account administration (Administrator pages) --------------------------------

def list_accounts(db: Session) -> list[Account]:
    return list(db.scalars(select(Account).order_by(Account.active.desc(), Account.email)))


def generate_temporary_password() -> str:
    """A random password shown once to the Administrator; forced change at next login."""
    return secrets.token_urlsafe(TEMPORARY_PASSWORD_BYTES)


def _one_line(value: str) -> str:
    """Escape CR/LF so no value can start a forged line in the log."""
    return value.replace("\r", "\\r").replace("\n", "\\n")


def _audit(acting: Account, action: str, target: Account, detail: str = "") -> None:
    audit_log.info(
        "account_admin by=%s action=%s target=%s%s",
        _one_line(acting.email), _one_line(action), _one_line(target.email),
        f" {_one_line(detail)}" if detail else "",
    )


def _get_account(db: Session, account_id: int) -> Account:
    account = db.get(Account, account_id)
    if account is None:
        raise AuthError("ไม่พบบัญชีนี้")
    return account


def _check_plant(db: Session, role: str, factory_id: int | None) -> int | None:
    """The Plant an Account with this Role should carry: required for a Requester, else none."""
    if role != "requester":
        return None
    factory = db.get(Factory, factory_id) if factory_id is not None else None
    if factory is None or not factory.active:
        raise AuthError("ผู้ขอต้องสังกัดโรงงาน — กรุณาเลือกโรงงาน")
    return factory.id


def _is_last_active_administrator(db: Session, account: Account) -> bool:
    """True if `account` is the only active Administrator.

    Locks every active Administrator row (Postgres) until commit, always in id
    order so two requests lock in the same sequence and cannot deadlock. Two
    Administrators deactivating each other at once are thus serialised: the
    second sees the first's change and is refused. Decided on the rows read
    under the lock, not on `account`'s possibly stale fields.
    """
    active_admins = list(db.scalars(
        select(Account.id)
        .where(Account.role == "administrator", Account.active)
        .order_by(Account.id)
        .with_for_update()
    ))
    return active_admins == [account.id]


def admin_create_account(
    db: Session, acting: Account, *, email: str, display_name: str, role: str,
    factory_id: int | None = None,
) -> tuple[Account, str]:
    """Create an Account with a random temporary password; returns (account, password)."""
    if role in ROLES:
        # Plant is kept only for a Requester, so a stray form value is dropped.
        factory_id = _check_plant(db, role, factory_id)
    temporary = generate_temporary_password()
    account = create_account(db, email, display_name, role, temporary,
                             factory_id=factory_id, must_change_password=True)
    _audit(acting, "create", account,
           f"name={account.display_name} role={role}"
           + (f" plant={account.factory.code}" if account.factory else ""))
    return account, temporary


def change_access(
    db: Session, acting: Account, account_id: int, *, role: str, factory_id: int | None,
) -> Account:
    """Change an Account's Role and/or Plant.

    A Requester must have a Plant; any other Role has none. Existing requests keep
    the Plant they were submitted for. A Role change ends open sessions, since what
    the Account may do has changed.
    """
    account = _get_account(db, account_id)
    if role not in ROLES:
        raise AuthError("บทบาทไม่ถูกต้อง")
    new_plant = _check_plant(db, role, factory_id)
    if role != account.role and _is_last_active_administrator(db, account):
        raise AuthError("ลด Role ไม่ได้ — นี่คือผู้ดูแลระบบคนสุดท้ายที่ใช้งานอยู่")

    changes = []
    if role != account.role:
        changes.append(f"role={account.role}->{role}")
        account.role = role
        account.session_version += 1
    if new_plant != account.factory_id:
        old = db.get(Factory, account.factory_id).code if account.factory_id else "-"
        new = db.get(Factory, new_plant).code if new_plant else "-"
        changes.append(f"plant={old}->{new}")
        account.factory_id = new_plant
    if not changes:
        return account
    db.commit()
    _audit(acting, "change_access", account, " ".join(changes))
    return account


def deactivate_account(db: Session, acting: Account, account_id: int) -> Account:
    account = _get_account(db, account_id)
    if account.id == acting.id:
        raise AuthError("ปิดใช้งานบัญชีของตัวเองไม่ได้")
    if _is_last_active_administrator(db, account):
        raise AuthError("ปิดใช้งานไม่ได้ — นี่คือผู้ดูแลระบบคนสุดท้ายที่ใช้งานอยู่")
    if not account.active:
        return account
    account.active = False
    account.session_version += 1  # logs it out everywhere at once
    db.commit()
    _audit(acting, "deactivate", account)
    return account


def reactivate_account(db: Session, acting: Account, account_id: int) -> Account:
    account = _get_account(db, account_id)
    if account.active:
        return account
    account.active = True
    # A fresh start: a lockout from before deactivation must not carry over.
    account.failed_login_count = 0
    account.locked_until = None
    db.commit()
    _audit(acting, "reactivate", account)
    return account


def reset_password(db: Session, acting: Account, account_id: int) -> str:
    """Give the Account a new random temporary password; returns it (show once, never log)."""
    account = _get_account(db, account_id)
    temporary = generate_temporary_password()
    account.password_hash = hash_password(temporary)
    account.must_change_password = True
    account.session_version += 1
    db.commit()
    _audit(acting, "reset_password", account)
    return temporary
