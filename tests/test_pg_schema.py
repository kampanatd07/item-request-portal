"""PostgreSQL: the migrations build the schema the models describe, and every
test gets its own copy of the migrated database (STORY-006 ticket 01).

Tests elsewhere use create_all, so a broken or missing migration passes them
all (HANDOFF §6.8); this is where it shows.
"""

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import func, select

from app.database import Base
from app.models import Account
from tests.conftest import account_for
from tests.pg_race import session_on

pytestmark = pytest.mark.postgres


def test_migrated_schema_matches_the_models(pg_engine):
    with pg_engine.connect() as c:
        diff = compare_metadata(MigrationContext.configure(c), Base.metadata)
    assert diff == [], "schema drift between migrations and models:\n" + "\n".join(
        map(repr, diff))


def test_migrated_database_is_seeded(pg_engine):
    from app.models import RunningRegister

    with session_on(pg_engine) as s:
        assert s.scalar(select(func.count()).select_from(RunningRegister)) > 0


def test_each_copy_is_fresh_and_writes_stay_in_it(pg_copy):
    first = pg_copy()
    with session_on(first) as s:
        account_for(s, "procurement")  # commits
        assert s.scalar(select(func.count()).select_from(Account)) == 1
    second = pg_copy()
    with session_on(second) as s:
        assert s.scalar(select(func.count()).select_from(Account)) == 0
