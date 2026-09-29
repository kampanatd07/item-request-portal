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


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, expire_on_commit=False)
    session = TestingSession()
    seed(session)
    yield session
    session.close()


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
