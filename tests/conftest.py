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


@pytest.fixture()
def client(client_as):
    """Logged in as an Administrator, who may do everything."""
    return client_as("administrator")
