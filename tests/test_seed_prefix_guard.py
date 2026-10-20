"""STORY-013 ticket 01 follow-up: the seed refuses a Name Prefix longer than 16.

Name Prefixes come only from app/data/taxonomy.json through the seed, so the
group standard's CATEGORY ≤ 16 is enforced there, before anything is written.
"""

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app import seed as seed_module
from app.database import Base
from app.models import CodeGroup, Factory


@pytest.fixture()
def empty_db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    yield factory
    engine.dispose()


def _taxonomy_with(monkeypatch, **changes) -> None:
    """taxonomy.json as shipped, with prefixes replaced for some (group, sub)."""
    real = seed_module._load_json

    def load(name: str):
        rows = real(name)
        if name == "taxonomy.json":
            rows = [dict(r) for r in rows]
            for r in rows:
                key = f"g{r['group']}_{r['sub']}"
                if key in changes:
                    r["prefix"] = changes[key]
        return rows

    monkeypatch.setattr(seed_module, "_load_json", load)


def test_the_shipped_taxonomy_seeds(empty_db):
    with empty_db() as db:
        seed_module.seed(db)
        assert db.scalar(select(func.count()).select_from(CodeGroup)) > 130


def test_a_prefix_over_16_is_refused_before_anything_is_written(empty_db, monkeypatch):
    _taxonomy_with(monkeypatch, g900_01="SPARE PARTS AND ACCESSORIES",
                   g902_01="MAINTENANCE SERVICES")
    with empty_db() as db:
        with pytest.raises(seed_module.SeedError) as refused:
            seed_module.seed(db)
    message = str(refused.value)
    assert "900-01" in message and "SPARE PARTS AND ACCESSORIES" in message and "27" in message
    assert "902-01" in message and "MAINTENANCE SERVICES" in message
    assert "16" in message and "taxonomy.json" in message
    with empty_db() as db:  # nothing written, not even the factories
        assert db.scalar(select(func.count()).select_from(Factory)) == 0
        assert db.scalar(select(func.count()).select_from(CodeGroup)) == 0


def test_the_length_is_counted_after_cleaning(empty_db, monkeypatch):
    # 16 characters once the surrounding spaces are cleaned off: accepted.
    _taxonomy_with(monkeypatch, g900_01="  ABCDEFGHIJKLMNOP  ")
    with empty_db() as db:
        seed_module.seed(db)
        assert db.scalar(select(func.count()).select_from(Factory)) > 0


def test_the_command_line_prints_the_thai_message_and_fails(empty_db, monkeypatch, capsys):
    _taxonomy_with(monkeypatch, g900_01="SPARE PARTS AND ACCESSORIES")
    monkeypatch.setattr(seed_module, "SessionLocal", empty_db)
    assert seed_module.main() == 1
    out = capsys.readouterr()
    assert "SPARE PARTS AND ACCESSORIES" in out.err and "Seed complete." not in out.out
