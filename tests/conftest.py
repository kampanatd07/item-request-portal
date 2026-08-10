import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.seed import seed


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


@pytest.fixture()
def client(db_session):
    def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
