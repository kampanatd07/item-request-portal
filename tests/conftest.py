import os

# Before any app import: Settings reads these once. Cheap Argon2 keeps the suite
# fast (production cost is unchanged), and APP_ENV=dev whatever the local .env says.
os.environ["APP_ENV"] = "dev"
os.environ["ARGON2_TIME_COST"] = "1"
os.environ["ARGON2_MEMORY_COST"] = "8"
os.environ["ARGON2_PARALLELISM"] = "1"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.seed import seed  # noqa: E402


def memory_engine():
    """An empty in-memory SQLite DB on one shared connection (StaticPool), so the
    app, the test and TestClient's thread all see the same data."""
    return create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )


def build_seeded_db():
    """create_all + seed into a fresh in-memory DB: what every test starts from."""
    engine = memory_engine()
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as session:
        seed(session)
        session.commit()
    return engine


def copy_db(source):
    """A new in-memory DB holding a byte-for-byte copy of `source` (SQLite backup API)."""
    target = memory_engine()
    src, dst = source.raw_connection(), target.raw_connection()
    try:
        src.driver_connection.backup(dst.driver_connection)
    finally:
        # Hand the shared StaticPool connections back; they stay open.
        src.close()
        dst.close()
    return target


def _clock_columns(table: str) -> set[str]:
    """Columns the DB fills with the current time (server_default now()), e.g.
    running_register.updated_at: they differ between two seeds by design."""
    t = Base.metadata.tables.get(table)
    return {c.name for c in t.columns if c.server_default is not None
            and "now" in str(getattr(c.server_default, "arg", "")).lower()} if t is not None else set()


def db_fingerprint(engine, ignore_clock: bool = False) -> dict:
    """Schema DDL (tables, indexes, constraints) plus a hash of every table's rows.

    Equal fingerprints mean the same structure and the same values, not just the
    same row counts. `ignore_clock` leaves out columns stamped with the time of
    insertion, for comparing two separately seeded DBs.
    """
    import hashlib

    from sqlalchemy import text

    with engine.connect() as c:
        ddl = sorted(r[0] for r in c.execute(text(
            "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL")))
        tables = [r[0] for r in c.execute(text(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"))]
        rows = {}
        for t in tables:
            skip = _clock_columns(t) if ignore_clock else set()
            digest = hashlib.sha256()
            for row in c.execute(text(f'SELECT * FROM "{t}" ORDER BY rowid')).mappings():
                digest.update(repr(tuple(v for k, v in row.items() if k not in skip)).encode())
            rows[t] = digest.hexdigest()
    return {"ddl": ddl, "rows": rows}


@pytest.fixture(scope="session")
def seeded_template():
    """Seeded once per pytest run; tests never touch it, they get copies.

    Seeding took ~0.35 s per test (~2 min for the suite); a copy takes ~1 ms.
    Copies, not a rolled-back transaction, because services commit themselves.
    """
    engine = build_seeded_db()
    before = db_fingerprint(engine)
    yield engine
    # A test that wrote to the template would have handed every later test a
    # dirty start; fail the run loudly instead.
    changed = db_fingerprint(engine) != before
    engine.dispose()
    assert not changed, "a test modified the shared seeded template DB"


@pytest.fixture()
def db_session(seeded_template):
    engine = copy_db(seeded_template)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    yield session
    session.close()
    engine.dispose()


def central_ids(db, factory_code: str = "APM", group_code: str = "900",
                sub_code: str = "01"):
    """Ids for a request against the central standard: (factory, system, group, sub).

    Every test that creates a request goes through here, so a future taxonomy
    change is a one-line fix instead of a sweep across test files.
    """
    from sqlalchemy import select

    from app.models import CodeGroup, CodeSystem, Factory

    factory = db.scalar(select(Factory).where(Factory.code == factory_code))
    system = db.scalar(select(CodeSystem).where(CodeSystem.code == "CENTRAL"))
    group = db.scalar(
        select(CodeGroup).where(
            CodeGroup.code_system_id == system.id,
            CodeGroup.code == group_code,
            CodeGroup.parent_id.is_(None),
        )
    )
    sub = db.scalar(
        select(CodeGroup).where(
            CodeGroup.parent_id == group.id, CodeGroup.code == sub_code
        )
    )
    return factory, system, group, sub


TEST_PASSWORD = "test-password-123"


def account_for(db, role: str = "procurement", plant: str | None = None):
    """The test Account for a Role (and Plant, for a Requester); created once per DB.

    Service-level tests pass it as the acting Account.
    """
    from sqlalchemy import select

    from app.models import Account, Factory
    from app.services.auth import create_account

    email = f"{role}-{(plant or 'any').lower()}@test.local"
    account = db.scalar(select(Account).where(Account.email == email))
    if account is None:
        factory_id = (db.scalar(select(Factory.id).where(Factory.code == plant))
                      if plant else None)
        account = create_account(db, email, f"Test {role}", role, TEST_PASSWORD,
                                 factory_id=factory_id, must_change_password=False)
    return account


@pytest.fixture()
def app_db(db_session):
    """Point the app at the test DB for the duration of a test."""
    def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    yield db_session
    app.dependency_overrides.clear()


@pytest.fixture()
def anon_client(app_db):
    with TestClient(app) as c:
        yield c


def login(c: TestClient, email: str, password: str = TEST_PASSWORD):
    """Log in through the real endpoint; the client keeps the session cookie."""
    return c.post("/login", data={"email": email, "password": password},
                  follow_redirects=False)


@pytest.fixture()
def client_as(app_db):
    """client_as(role, plant=None) -> a TestClient logged in as a new Account."""
    from sqlalchemy import select

    from app.models import Factory
    from app.services.auth import create_account

    clients: list[TestClient] = []

    def _make(role: str, plant: str | None = None) -> TestClient:
        factory_id = None
        if plant is not None:
            factory_id = app_db.scalar(select(Factory.id).where(Factory.code == plant))
        email = f"{role}{len(clients)}@test.local"
        create_account(app_db, email, f"Test {role}", role, TEST_PASSWORD,
                       factory_id=factory_id, must_change_password=False)
        c = TestClient(app)
        c.__enter__()
        clients.append(c)
        assert login(c, email).status_code == 303
        return c

    yield _make
    for c in clients:
        c.__exit__(None, None, None)


class FakeClock:
    """Stands in for app.services.clock: tests move time instead of sleeping."""

    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, **delta) -> None:
        from datetime import timedelta

        self.now += timedelta(**delta)


@pytest.fixture()
def clock(app_db):
    """A movable clock for every request (login time, session expiry, lockout).

    Request it before `client`/`client_as` so logins are stamped with it too.
    """
    from datetime import datetime

    from app.services.clock import get_clock

    fake = FakeClock(datetime(2026, 9, 29, 8, 0, 0))
    app.dependency_overrides[get_clock] = lambda: fake
    yield fake


@pytest.fixture()
def client(client_as):
    """Logged in as an Administrator, who may do everything."""
    return client_as("administrator")
