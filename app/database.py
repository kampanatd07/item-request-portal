from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

# check_same_thread only applies to SQLite (local dev / tests); ignored by Postgres
# timeout: SQLite waits this long for its write lock, which an email send
# holds (STORY-002); the default 5 s would fail other writes during a slow send.
connect_args = ({"check_same_thread": False, "timeout": 30}
                if settings.database_url.startswith("sqlite") else {})
engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_session_factory():
    """FastAPI dependency: how background work (e.g. sending email after the
    response) opens its own session, since the request's session is closed
    by then. Tests point it at their database."""
    return SessionLocal


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
