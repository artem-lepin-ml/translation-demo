"""seed(): PALIMPSEST_SEED_DEMO=1 curates the vLLM rows out (spec §4)."""
from __future__ import annotations

import pytest


@pytest.fixture
def seeded_env(tmp_path, monkeypatch):
    def _make(demo: bool):
        from palimpsest.webapp import db, seed as seedmod

        monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
        monkeypatch.setattr(db, "_conn", None)
        if demo:
            monkeypatch.setenv("PALIMPSEST_SEED_DEMO", "1")
        else:
            monkeypatch.delenv("PALIMPSEST_SEED_DEMO", raising=False)
        seedmod.seed()
        return db

    yield _make
    from palimpsest.webapp import db

    if db._conn is not None:
        db._conn.close()
        db._conn = None


def test_demo_flag_seeds_five_openrouter_only_models(seeded_env):
    db = seeded_env(demo=True)
    conn = db.connect()
    rows = conn.execute("SELECT base_url FROM model").fetchall()
    assert len(rows) == 5
    assert all("openrouter" in r["base_url"] for r in rows)


def test_demo_flag_criteria_fk_resolves(seeded_env):
    db = seeded_env(demo=True)
    conn = db.connect()
    model_names = {r["name"] for r in conn.execute("SELECT name FROM model")}
    for r in conn.execute("SELECT DISTINCT model_name FROM criterion"):
        assert r["model_name"] in model_names


def test_no_flag_seeds_all_eight_models(seeded_env):
    db = seeded_env(demo=False)
    conn = db.connect()
    assert conn.execute("SELECT COUNT(*) n FROM model").fetchone()["n"] == 8
