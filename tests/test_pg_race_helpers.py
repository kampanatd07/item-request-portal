"""The race helpers report the real cause when a race test fails
(STORY-006 ticket 01 review, findings 2-5)."""

import pytest
from sqlalchemy import text

from tests.conftest import PG_COPY_PREFIX, _pg_admin, drop_leftover_pg_databases, memory_engine
from tests.pg_race import Race


def test_an_error_in_a_is_shown_not_a_timeout():
    # Fails before any PostgreSQL-only step, so it runs on SQLite too.
    def a(db):
        raise ValueError("A broke before its commit")

    def b(db):
        pytest.fail("B must not start when A failed")

    engine = memory_engine()
    try:
        with Race(engine) as race, pytest.raises(ValueError, match="A broke before its commit"):
            race.run(a, b)
    finally:
        engine.dispose()


@pytest.mark.postgres
def test_b_finishing_without_a_lock_wait_shows_what_b_raised(pg_engine):
    def a(db):
        db.commit()  # reaches its (held) commit at once

    def b(db):
        raise RuntimeError("B setup broke")

    with Race(pg_engine) as race, pytest.raises(AssertionError, match="B setup broke"):
        race.run(a, b)


@pytest.mark.postgres
def test_only_leftover_test_databases_are_dropped(pg_engine):
    leftover, other = f"{PG_COPY_PREFIX}1_0", "irpkeep_not_a_test_db"
    admin = _pg_admin()
    try:
        with admin.connect() as c:
            for name in (leftover, other):
                c.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
                c.execute(text(f'CREATE DATABASE "{name}"'))
        dropped = drop_leftover_pg_databases(admin)
        with admin.connect() as c:
            present = {n for (n,) in c.execute(text("SELECT datname FROM pg_database"))}
        assert leftover in dropped and leftover not in present
        assert other in present
        # This run's own template and copy survive.
        assert pg_engine.url.database in present
    finally:
        with admin.connect() as c:
            c.execute(text(f'DROP DATABASE IF EXISTS "{other}"'))
        admin.dispose()
