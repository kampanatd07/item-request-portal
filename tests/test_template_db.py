"""The seeded template DB that every test copies (chore/fast-tests).

If these fail, tests would start from something other than create_all + seed,
or leak data into each other. The seeded_template fixture also fails the run
if any test modifies the template itself.
"""

from contextlib import contextmanager

from sqlalchemy import text

from app.database import Base
from tests.conftest import build_seeded_db, copy_db, db_fingerprint


@contextmanager
def _engines(*engines):
    try:
        yield engines
    finally:
        for engine in engines:
            engine.dispose()


def test_copy_matches_a_fresh_create_all_and_seed(seeded_template):
    with _engines(copy_db(seeded_template), build_seeded_db()) as (copy, fresh):
        fp = db_fingerprint(copy, ignore_clock=True)
        # Same DDL and same values, table by table (insert timestamps aside).
        assert fp == db_fingerprint(fresh, ignore_clock=True)
        assert set(Base.metadata.tables) <= set(fp["rows"])
        with copy.connect() as c:
            assert c.execute(text("SELECT COUNT(*) FROM running_register")).scalar() > 0


def test_writes_to_one_copy_never_reach_the_template_or_other_copies(seeded_template):
    before = db_fingerprint(seeded_template)
    with _engines(copy_db(seeded_template), copy_db(seeded_template)) as (first, second):
        with first.begin() as c:
            c.execute(text("UPDATE factories SET name = 'changed'"))  # values, not counts
        assert db_fingerprint(first) != before
        assert db_fingerprint(seeded_template) == before
        assert db_fingerprint(second) == before


def test_db_session_is_a_copy_not_the_template(db_session, seeded_template):
    assert db_session.get_bind() is not seeded_template
