"""Accounts and password authentication.

Only this module touches password hashes. Login failures are deliberately
indistinguishable (same message, same work) so the form cannot be used to
find out which emails have an Account.
"""

import ipaddress
import logging
import re
import secrets
from datetime import datetime, timedelta
from functools import lru_cache
from typing import NoReturn

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import delete, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.models import ROLES, Account, Factory, LoginIpFailure
from app.services.clock import utc_now

MIN_PASSWORD_LENGTH = 12
MAX_EMAIL_LENGTH = 254  # accounts.email
MAX_DISPLAY_NAME_LENGTH = 100  # accounts.display_name
TEMPORARY_PASSWORD_BYTES = 12  # token_urlsafe -> 16 characters
# 10 consecutive wrong passwords lock the email for 15 minutes (STORY-001 AC9).
MAX_FAILED_LOGINS = 10
LOCKOUT = timedelta(minutes=15)
ACCOUNT_LOCKED = "บัญชีถูกล็อกชั่วคราว 15 นาที เพราะใส่รหัสผ่านผิดหลายครั้ง"
# 50 failed logins from one client IP within 15 minutes block that IP for 15
# minutes (STORY-006 AC 5), against password spraying: one password tried
# across many emails, which the per-email lockout cannot see. High because a
# whole plant may reach the portal from one public IP; only failures count.
MAX_FAILED_LOGINS_PER_IP = 50
IP_WINDOW = timedelta(minutes=15)
IP_BLOCK = timedelta(minutes=15)
# Rows untouched this long are deleted (after a failed login, see _prune_idle_ip_rows).
IP_ROW_IDLE = timedelta(days=1)
IP_BLOCKED = "มีการเข้าสู่ระบบผิดจากเครื่องนี้หลายครั้งเกินไป กรุณารอ 15 นาทีแล้วลองใหม่"

# Account administration is logged here (who, action, target) until STORY-011
# moves it into the DB. Never pass a password, hash or temporary password.
audit_log = logging.getLogger("app.accounts")
LOGIN_FAILED = "อีเมลหรือรหัสผ่านไม่ถูกต้อง"
# local@domain.tld with no whitespace or control characters anywhere: a line
# break in an email would otherwise let it forge lines in the audit log.
_EMAIL_RE = re.compile(r"[^@\s\x00-\x1f\x7f]+@[^@\s\x00-\x1f\x7f]+\.[^@\s\x00-\x1f\x7f]+")


class AuthError(Exception):
    """Auth error with a user-facing Thai message."""


class IpBlocked(AuthError):
    """This client IP made too many failed logins; refused before any hashing."""


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
    # Column limits (accounts.email 254, display_name 100): PostgreSQL would
    # raise instead of truncating, and the page would answer 500.
    if len(email) > MAX_EMAIL_LENGTH:
        raise AuthError(f"อีเมลยาวเกิน {MAX_EMAIL_LENGTH} ตัวอักษร")
    if not display_name:
        raise AuthError("กรุณาระบุชื่อ")
    if len(display_name) > MAX_DISPLAY_NAME_LENGTH:
        raise AuthError(f"ชื่อยาวเกิน {MAX_DISPLAY_NAME_LENGTH} ตัวอักษร")
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


def _lock_row(db: Session, account_id: int) -> Account:
    """Reload an Account with its row locked until commit (Postgres; SQLite ignores it),
    so parallel guesses are counted one after another and none slip past the limit."""
    return db.scalar(
        select(Account).where(Account.id == account_id)
        .with_for_update().execution_options(populate_existing=True)
    )


def _is_locked(account: Account, now: datetime) -> bool:
    """True while a lock is running. A lock that has run out is cleared, and the
    count starts again from zero (a single typo right after must not re-lock)."""
    if account.locked_until is None:
        return False
    if account.locked_until > now:
        return True
    account.locked_until = None
    account.failed_login_count = 0
    return False


def _register_failure(account: Account, now: datetime) -> bool:
    """Count one wrong password; returns True if this one locked the Account.
    Failures during a lock never reach here, so a lock is never extended."""
    account.failed_login_count += 1
    if account.failed_login_count < MAX_FAILED_LOGINS:
        return False
    account.locked_until = now + LOCKOUT
    _audit(None, "locked", account, f"until={account.locked_until:%Y-%m-%d %H:%M} UTC")
    return True


def authenticate(db: Session, email: str, password: str, now: datetime | None = None, *,
                 client_ip: str) -> Account:
    """Return the active Account for these credentials, or raise one generic AuthError.

    Every outcome that is not a success — unknown email, wrong password,
    deactivated, locked — gives the same message after the same hashing work,
    so the form reveals neither which emails exist nor that one is locked.
    Each such failure also counts against `client_ip`; a blocked IP gets
    IpBlocked at once, without hashing. Lock order: the IP row, then the
    Account row, held through the hashing so parallel guesses count one after
    another (STORY-006 ticket 07).
    """
    now = now or utc_now()
    ip_row = _lock_ip_row(db, _ip_key(client_ip), now)
    if _ip_is_blocked(ip_row, now):
        db.commit()
        raise IpBlocked(IP_BLOCKED)
    found = db.scalar(select(Account.id).where(Account.email == normalize_email(email)))
    if found is None:
        # Burn the same hashing time as a real check (AC6).
        verify_password(_dummy_hash(settings.argon2_time_cost, settings.argon2_memory_cost,
                                    settings.argon2_parallelism), password)
        _login_failed(db, ip_row, now)
    account = _lock_row(db, found)
    password_ok = verify_password(account.password_hash, password)  # always, for timing
    if _is_locked(account, now):
        _login_failed(db, ip_row, now)
    if not password_ok or not account.active:
        _register_failure(account, now)
        _login_failed(db, ip_row, now)
    account.failed_login_count = 0
    db.commit()

    # Upgrade old hashes in place when the cost parameters are raised.
    if _current_hasher().check_needs_rehash(account.password_hash):
        account.password_hash = hash_password(password)
        db.commit()
    return account


def _ip_key(client_ip: str | None) -> str:
    """The IP as stored: normalised, or "unknown" for anything that is not an
    IP (no client address, a test client), so odd values share one bucket and
    never exceed the column."""
    try:
        return str(ipaddress.ip_address((client_ip or "").strip()))[:45]
    except ValueError:
        return "unknown"


def _lock_ip_row(db: Session, ip: str, now: datetime) -> LoginIpFailure:
    """The IP's row, locked until commit (Postgres); created if missing. Two
    first logins from a new IP at once: one inserts, the other's insert fails
    in its savepoint, and it then waits for and reads that row."""
    stmt = (select(LoginIpFailure).where(LoginIpFailure.ip == ip)
            .with_for_update().execution_options(populate_existing=True))
    row = db.scalar(stmt)
    if row is None:
        try:
            with db.begin_nested():
                db.add(LoginIpFailure(ip=ip, failed_count=0, window_started_at=now))
        except IntegrityError:
            pass  # another login created it first
        row = db.scalar(stmt)
    return row


def _ip_is_blocked(row: LoginIpFailure, now: datetime) -> bool:
    """True while a block runs. A block or window that has run out starts the
    count again from zero."""
    if row.blocked_until is not None:
        if row.blocked_until > now:
            return True
        row.blocked_until = None
        row.failed_count = 0
    if row.failed_count and now - row.window_started_at >= IP_WINDOW:
        row.failed_count = 0
    return False


def _login_failed(db: Session, ip_row: LoginIpFailure, now: datetime) -> NoReturn:
    """Count the failure against the IP, commit (with the Account's own count,
    if any), tidy old IP rows, and raise the one generic error."""
    if ip_row.failed_count == 0:
        ip_row.window_started_at = now
    ip_row.failed_count += 1
    if ip_row.failed_count >= MAX_FAILED_LOGINS_PER_IP:
        ip_row.blocked_until = now + IP_BLOCK
        audit_log.info("login_ip_blocked ip=%s until=%s UTC", _one_line(ip_row.ip),
                       f"{ip_row.blocked_until:%Y-%m-%d %H:%M}")
    db.commit()
    _prune_idle_ip_rows(db, now)
    raise AuthError(LOGIN_FAILED)


def _prune_idle_ip_rows(db: Session, now: datetime) -> None:
    """Delete IP rows idle for IP_ROW_IDLE, in a short transaction of its own,
    after the login has committed. Rows another login holds are skipped
    (SKIP LOCKED, Postgres), so this never waits on or deadlocks with a login;
    and a failure here is logged, never passed on to the login."""
    cutoff = now - IP_ROW_IDLE
    try:
        stale = list(db.scalars(
            select(LoginIpFailure.ip)
            .where(LoginIpFailure.window_started_at < cutoff,
                   or_(LoginIpFailure.blocked_until.is_(None),
                       LoginIpFailure.blocked_until < cutoff))
            .with_for_update(skip_locked=True)
        ))
        if stale:
            db.execute(delete(LoginIpFailure).where(LoginIpFailure.ip.in_(stale)))
        db.commit()
    except Exception:  # noqa: BLE001 — tidying must never fail a login
        db.rollback()
        logging.getLogger("app.auth").warning("login_ip_prune_failed", exc_info=True)


def change_own_password(
    db: Session, account: Account, *, current: str, new: str, confirm: str,
    now: datetime | None = None,
) -> None:
    """An Account replaces its own password (also the forced first-login change).

    Bumps the session version so every other session of the Account ends; the
    caller re-issues the current session's cookie. A wrong current password
    counts toward the same lockout as the login page; if it triggers the lock,
    this session is ended too, since a logged-in session guessing the password
    looks like a stolen cookie.
    """
    now = now or utc_now()
    account = _lock_row(db, account.id)
    current_ok = verify_password(account.password_hash, current)
    if _is_locked(account, now):
        db.commit()
        raise AuthError(ACCOUNT_LOCKED)
    if not current_ok:
        if _register_failure(account, now):
            account.session_version += 1
            db.commit()
            raise AuthError(ACCOUNT_LOCKED)
        db.commit()
        raise AuthError("รหัสผ่านปัจจุบันไม่ถูกต้อง")
    # The right password resets the count, as on the login page — committed now,
    # before the checks below can refuse the new password and roll it back.
    account.failed_login_count = 0
    db.commit()
    if new != confirm:
        raise AuthError("รหัสผ่านใหม่ทั้งสองช่องไม่ตรงกัน")
    check_password_rules(new)
    if new == current:
        # Otherwise a forced change could just re-enter the temporary password.
        raise AuthError("รหัสผ่านใหม่ต้องไม่ซ้ำกับรหัสผ่านปัจจุบัน")
    account.password_hash = hash_password(new)
    account.must_change_password = False
    account.session_version += 1
    db.commit()
    _audit(account, "change_password", account)


# --- Account administration (Administrator pages) --------------------------------

def list_accounts(db: Session) -> list[Account]:
    return list(db.scalars(select(Account).order_by(Account.active.desc(), Account.email)))


def generate_temporary_password() -> str:
    """A random password shown once to the Administrator; forced change at next login."""
    return secrets.token_urlsafe(TEMPORARY_PASSWORD_BYTES)


def _one_line(value: str) -> str:
    """Escape CR/LF so no value can start a forged line in the log."""
    return value.replace("\r", "\\r").replace("\n", "\\n")


def _audit(acting: Account | None, action: str, target: Account, detail: str = "") -> None:
    """`acting` None means the system did it (e.g. a lockout)."""
    audit_log.info(
        "account_admin by=%s action=%s target=%s%s",
        _one_line(acting.email if acting else "system"), _one_line(action),
        _one_line(target.email),
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
    # Someone locked out asks for a reset; let the temporary password work now.
    account.failed_login_count = 0
    account.locked_until = None
    db.commit()
    _audit(acting, "reset_password", account)
    return temporary
