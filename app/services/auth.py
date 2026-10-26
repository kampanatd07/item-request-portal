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
from sqlalchemy import delete, or_, select, update
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
    so its counts change one login at a time. Never held through a hash
    (ticket 08): parallel guesses are held to the limit by slots instead."""
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
                 client_ip: str | None) -> Account:
    """Return the active Account for these credentials, or raise one generic AuthError.

    Every outcome that is not a success — unknown email, wrong password,
    deactivated, locked — gives the same message after the same hashing work,
    so the form reveals neither which emails exist nor that one is locked.

    Hold a slot, check, settle (STORY-006 ticket 08). (1) A short transaction
    takes a "being checked" slot on the IP and on the Account. Confirmed
    failures + slots in use may not pass the limits (50 per IP, 10 per
    Account), so parallel guesses cannot pass them either: a full or blocked
    IP gets IpBlocked at once, without hashing; a full or locked Account gets
    no slot and its real hash is never checked (a dummy hash takes the same
    time). (2) The password is hashed holding no lock, transaction or
    connection. (3) A second short transaction frees the slots and records the
    outcome. Lock order in both: the IP row, then the Account row. Any other
    error after (1) frees the slots before it is passed on.
    """
    now = now or utc_now()
    ip = _ip_key(client_ip)

    # 1. Take the slots; read what the check needs; let go of everything.
    ip_row = _lock_ip_row(db, ip, now)
    if (_ip_is_blocked(ip_row, now)
            or ip_row.failed_count + _pending(ip_row, now) >= MAX_FAILED_LOGINS_PER_IP):
        db.commit()
        raise IpBlocked(IP_BLOCKED)
    _hold_slot(ip_row, now)
    account_id = db.scalar(select(Account.id).where(Account.email == normalize_email(email)))
    checked_hash = None  # the real hash, only when the Account got a slot
    if account_id is not None:
        account = _lock_row(db, account_id)
        if (not _is_locked(account, now)
                and account.failed_login_count + _pending(account, now) < MAX_FAILED_LOGINS):
            _hold_slot(account, now)
            checked_hash = account.password_hash
    db.commit()

    try:
        return _check_and_settle(db, ip, account_id, checked_hash, password, now)
    except AuthError:
        raise
    except BaseException:
        _free_slots_after_error(db, ip, account_id if checked_hash else None, now)
        raise


def _check_and_settle(db: Session, ip: str, account_id: int | None, checked_hash: str | None,
                      password: str, now: datetime) -> Account:
    """Steps 2 and 3 of authenticate. Nothing here raises after the settling
    commit, so the caller's error path never frees the slots a second time."""
    has_slot = checked_hash is not None
    # 2. Hash with nothing held. No slot (unknown email, or the Account is
    # locked or full): the same work against a dummy hash (AC6).
    password_ok = _verify(checked_hash, password) and has_slot
    # 3. Settle, on freshly locked rows (IP, then Account).
    ip_row, account = _lock_rows(db, ip, account_id, now)
    if (has_slot and password_ok and account is not None and not _is_locked(account, now)
            and account.password_hash != checked_hash):
        # Changed while being checked (upgraded by another login, or a new
        # password). Checked again once, holding nothing; then everything is
        # written on rows locked afresh, never on the ones read before. A
        # locked Account is refused first, without this second hash, so a right
        # guess costs no more time than a wrong one.
        checked_hash = account.password_hash
        db.commit()
        password_ok = verify_password(checked_hash, password)
        ip_row, account = _lock_rows(db, ip, account_id, now)
        if account is None or account.password_hash != checked_hash:
            password_ok = False  # changed again: refuse rather than chase it
    _free_slot(ip_row)
    if has_slot and account is not None:
        _free_slot(account)
    # Locked meanwhile: refused exactly like a wrong password on a locked
    # Account, so a right guess cannot be told apart.
    locked = account is not None and _is_locked(account, now)
    if not (password_ok and account is not None and account.active and not locked):
        if has_slot and account is not None and not locked:
            _register_failure(account, now)
        _login_failed(db, ip_row, now)
    account.failed_login_count = 0
    db.commit()
    try:
        _upgrade_hash(db, account, checked_hash, password)
    except Exception:  # noqa: BLE001 — the login already succeeded; the upgrade can wait
        db.rollback()
        logging.getLogger("app.auth").warning("login_hash_upgrade_failed", exc_info=True)
    return account


def _verify(stored_hash: str | None, password: str) -> bool:
    """The password check, or the same work against a dummy hash."""
    return verify_password(stored_hash or _dummy_hash(
        settings.argon2_time_cost, settings.argon2_memory_cost, settings.argon2_parallelism),
        password)


def _lock_rows(db: Session, ip: str, account_id: int | None,
               now: datetime) -> tuple[LoginIpFailure, Account | None]:
    """The IP row, then the Account row, locked until commit: the one lock order."""
    ip_row = _lock_ip_row(db, ip, now)
    return ip_row, _lock_row(db, account_id) if account_id is not None else None


# A slot not freed within this time (its login crashed) counts as free again.
PENDING_EXPIRY = timedelta(minutes=1)


def _pending(row: Account | LoginIpFailure, now: datetime) -> int:
    """Slots in use on `row`. Once they have run out (1 minute after the count
    went 0 -> 1), they are written back as empty, so the limit holds again
    from the next slot on, and a lost slot never locks anyone out."""
    if (row.pending_checks and row.pending_since is not None
            and now - row.pending_since >= PENDING_EXPIRY):
        row.pending_checks = 0
        row.pending_since = None
    return row.pending_checks


def _hold_slot(row: Account | LoginIpFailure, now: datetime) -> None:
    if row.pending_checks <= 0:
        row.pending_checks = 0
        row.pending_since = now
    row.pending_checks += 1


def _free_slot(row: Account | LoginIpFailure) -> None:
    """Never below 0: a login that ends after its slots expired frees nothing."""
    row.pending_checks = max(0, row.pending_checks - 1)
    if row.pending_checks == 0:
        row.pending_since = None


def _free_slots_after_error(db: Session, ip: str, account_id: int | None,
                            now: datetime) -> None:
    """Give back the slots of a login that failed with an error (not a wrong
    password). If even this fails, the slots expire on their own."""
    try:
        db.rollback()
        _free_slot(_lock_ip_row(db, ip, now))
        if account_id is not None:
            account = _lock_row(db, account_id)
            if account is not None:
                _free_slot(account)
        db.commit()
    except Exception:  # noqa: BLE001 — the original error is what matters
        db.rollback()
        logging.getLogger("app.auth").warning("login_slot_release_failed", exc_info=True)


def _upgrade_hash(db: Session, account: Account, checked_hash: str, password: str) -> None:
    """Re-hash with the current cost parameters when they were raised, but
    only if the stored hash is still the one just checked: a password changed
    meanwhile is never overwritten with the old one."""
    if not _current_hasher().check_needs_rehash(checked_hash):
        return
    new_hash = hash_password(password)
    db.execute(update(Account)
               .where(Account.id == account.id, Account.password_hash == checked_hash)
               .values(password_hash=new_hash))
    db.commit()


def ip_key_or_none(raw: str | None) -> str | None:
    """How a client IP is counted, or None if `raw` is not an IP. IPv6 counts
    per /64 (one subscriber's usual prefix, so a sprayer cannot rotate inside
    it); an IPv4-mapped IPv6 address counts as its IPv4."""
    try:
        ip = ipaddress.ip_address((raw or "").strip())
    except ValueError:
        return None
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return str(ip.ipv4_mapped)
        return str(ipaddress.IPv6Network((int(ip), 64), strict=False))
    return str(ip)


def _ip_key(client_ip: str | None) -> str:
    """The IP as stored (see ip_key_or_none), or "unknown" for anything that
    is not an IP (no client address, a test client), so odd values share one
    bucket and never exceed the column. Every "unknown" is logged as a
    warning: on a server it means a setup fault (e.g. FORWARDED_ALLOW_IPS), and
    everyone in that bucket is counted, and blocked, together."""
    key = ip_key_or_none(client_ip)
    if key is None:
        logging.getLogger("app.auth").warning(
            "login_client_ip_unknown raw=%s: counted in the shared 'unknown' bucket; "
            "check FORWARDED_ALLOW_IPS", _one_line(repr(client_ip)[:100]))
        return "unknown"
    return key


def _lock_ip_row(db: Session, ip: str, now: datetime) -> LoginIpFailure:
    """The IP's row, locked until commit (Postgres); created if missing. Two
    first logins from a new IP at once: one inserts, the other's insert fails
    in its savepoint, and it then waits for and reads that row. A row deleted
    in between (a manual delete) is simply created again."""
    stmt = (select(LoginIpFailure).where(LoginIpFailure.ip == ip)
            .with_for_update().execution_options(populate_existing=True))
    for _ in range(3):
        row = db.scalar(stmt)
        if row is not None:
            return row
        try:
            with db.begin_nested():
                db.add(LoginIpFailure(ip=ip, failed_count=0, window_started_at=now))
        except IntegrityError:
            pass  # another login created it first
    raise RuntimeError(f"login_ip_failures row for {ip!r} kept vanishing")


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
    """Count the failure against the IP and start the block when it reaches
    the limit, commit (with the Account's own count, if any), tidy old IP rows,
    and raise the one generic error."""
    if ip_row.failed_count == 0:
        ip_row.window_started_at = now
    ip_row.failed_count += 1
    if ip_row.failed_count >= MAX_FAILED_LOGINS_PER_IP and ip_row.blocked_until is None:
        ip_row.blocked_until = now + IP_BLOCK
        audit_log.info("login_ip_blocked ip=%s until=%s UTC", _one_line(ip_row.ip),
                       f"{ip_row.blocked_until:%Y-%m-%d %H:%M}")
    db.commit()
    _prune_idle_ip_rows(db, now)
    raise AuthError(LOGIN_FAILED)


def unblock_ip(db: Session, raw_ip: str, *, by: str, now: datetime | None = None) -> bool:
    """Lift a login block on an IP (an IPv6 address lifts its /64; "unknown"
    lifts the shared bucket). Returns False, changing nothing, if that IP is
    not blocked. `by` names who did it, for the log; required."""
    now = now or utc_now()
    by = " ".join((by or "").split())
    if not by:
        raise AuthError("--by is required: who is lifting the block")
    ip = "unknown" if raw_ip.strip().lower() == "unknown" else ip_key_or_none(raw_ip)
    if ip is None:
        raise AuthError(f"not an IP address: {raw_ip!r}")
    row = db.scalar(select(LoginIpFailure).where(LoginIpFailure.ip == ip).with_for_update())
    if row is None or row.blocked_until is None or row.blocked_until <= now:
        db.rollback()
        return False
    row.blocked_until = None
    row.failed_count = 0
    row.pending_checks = 0
    row.pending_since = None
    db.commit()
    audit_log.info("login_ip_unblocked ip=%s by=%s", _one_line(ip), _one_line(by))
    return True


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
                       LoginIpFailure.blocked_until < cutoff),
                   # Never a row whose logins are being checked right now.
                   or_(LoginIpFailure.pending_checks == 0,
                       LoginIpFailure.pending_since < now - PENDING_EXPIRY))
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


PERMISSION_CHANGED = "สิทธิ์ของคุณเปลี่ยนไปแล้ว — กรุณาเข้าสู่ระบบใหม่"


def _lock_active_administrators(db: Session, acting: Account) -> list[int]:
    """Lock every active Administrator row (Postgres) until commit and return
    their ids; refuse unless `acting` is still one of them.

    Always in id order, so two requests lock in the same sequence and cannot
    deadlock. Two Administrators acting on each other at once are thus
    serialised, and the second is decided on the rows read under the lock,
    not on anyone's possibly stale fields: an Administrator deactivated or
    demoted a moment ago passed the route's guard, but is refused here
    (STORY-006 ticket 04).
    """
    active_admins = list(db.scalars(
        select(Account.id)
        .where(Account.role == "administrator", Account.active)
        .order_by(Account.id)
        .with_for_update()
    ))
    if acting.id not in active_admins:
        raise AuthError(PERMISSION_CHANGED)
    return active_admins


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
    active_admins = _lock_active_administrators(db, acting)
    if role != account.role and active_admins == [account.id]:
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
    if _lock_active_administrators(db, acting) == [account.id]:
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


def _give_temporary_password(db: Session, account: Account) -> str:
    """The reset itself, shared by the Account admin page and the command:
    a new random temporary password, changed at the next login; every open
    session ends; the lockout is cleared. Returns the password (show once,
    never log)."""
    temporary = generate_temporary_password()
    account.password_hash = hash_password(temporary)
    account.must_change_password = True
    account.session_version += 1
    # Someone locked out asks for a reset; let the temporary password work now.
    account.failed_login_count = 0
    account.locked_until = None
    db.commit()
    return temporary


def reset_password(db: Session, acting: Account, account_id: int) -> str:
    """Give the Account a new random temporary password; returns it (show once, never log)."""
    account = _get_account(db, account_id)
    temporary = _give_temporary_password(db, account)
    _audit(acting, "reset_password", account)
    return temporary


def reset_password_from_cli(db: Session, email: str, *, by: str) -> str:
    """The reset for `python -m app.reset_password`: an Administrator locked
    out with no other Administrator to reset them. `by` names who did it, for
    the log (`by=cli:<name>`, so it is never taken for an Account's email);
    required. A deactivated Account is refused: it could not log in anyway."""
    by = " ".join((by or "").split())
    if not by:
        raise AuthError("--by is required: who is resetting the password")
    account = db.scalar(select(Account).where(Account.email == normalize_email(email)))
    if account is None:
        raise AuthError(f"no Account with the email {email.strip()!r}")
    if not account.active:
        raise AuthError(f"{account.email} is deactivated: reactivate it first "
                        "(Account admin page), then reset the password")
    temporary = _give_temporary_password(db, account)
    audit_log.info("account_admin by=%s action=reset_password target=%s",
                   _one_line(f"cli:{by}"), _one_line(account.email))
    return temporary
