"""The race helpers report the real cause when a race test fails
(STORY-006 ticket 01 review, findings 2-5; ticket 03 review, findings 1, 2, 7)."""

import time

import pytest
from sqlalchemy import text

from tests.conftest import PG_COPY_PREFIX, _pg_admin, drop_leftover_pg_databases, memory_engine
from tests.pg_race import WAIT_SECONDS, Race, session_on


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

    started = time.monotonic()
    with Race(pg_engine) as race, pytest.raises(AssertionError, match="B setup broke"):
        race.run(a, b)
    # Decided at once; A aborted rather than held until a timeout.
    assert time.monotonic() - started < WAIT_SECONDS / 2


def _lock_register_row(sub: str):
    def run(db):
        db.execute(text(
            "SELECT 1 FROM running_register WHERE group_code = '900' AND sub_code = :sub "
            "FOR UPDATE"), {"sub": sub})
        db.commit()
        return sub
    return run


@pytest.mark.postgres
def test_run_without_wait_passes_when_b_takes_other_rows(pg_engine):
    with Race(pg_engine) as race:
        assert race.run_without_wait(_lock_register_row("01"), _lock_register_row("02")) == (
            "01", "02")


@pytest.mark.postgres
def test_run_without_wait_fails_at_once_when_b_waits_on_a_lock_and_frees_it(pg_engine):
    started = time.monotonic()
    with Race(pg_engine) as race, pytest.raises(AssertionError, match="waited on a lock"):
        race.run_without_wait(_lock_register_row("01"), _lock_register_row("01"))
    # Seen in pg_stat_activity, not after a timeout.
    assert time.monotonic() - started < WAIT_SECONDS / 2
    # A was aborted and rolled back: nobody holds the row any more.
    with session_on(pg_engine) as db:
        db.execute(text(
            "SELECT 1 FROM running_register WHERE group_code = '900' AND sub_code = '01' "
            "FOR UPDATE NOWAIT"))
        db.rollback()


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
