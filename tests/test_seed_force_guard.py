"""seed() refuses to reseed a non-empty DB unless PALIMPSEST_SEED_FORCE=1
(wave-4 Б3.5) — a code-level guard against silently blowing away live
predictions with a re-seed."""
from __future__ import annotations

import pytest


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    from palimpsest.webapp import db
    path = tmp_path / "guard.db"
    monkeypatch.setattr(db, "DB_PATH", path)
    monkeypatch.setattr(db, "_conn", None)
    yield path, db
    if db._conn is not None:
        db._conn.close()
        db._conn = None


def test_seed_refuses_non_empty_db_without_force(db_path, monkeypatch):
    from palimpsest.webapp import seed as seedmod

    monkeypatch.delenv("PALIMPSEST_SEED_FORCE", raising=False)
    seedmod.seed()  # first pass: DB doesn't pre-exist -> guard doesn't trip

    with pytest.raises(RuntimeError, match="PALIMPSEST_SEED_FORCE"):
        seedmod.seed()  # second pass: DB is now non-empty -> must refuse


def test_seed_force_env_overrides_guard(db_path, monkeypatch):
    from palimpsest.webapp import seed as seedmod

    monkeypatch.delenv("PALIMPSEST_SEED_FORCE", raising=False)
    seedmod.seed()

    monkeypatch.setenv("PALIMPSEST_SEED_FORCE", "1")
    seedmod.seed()  # must not raise


def test_seed_on_missing_db_never_trips_guard(db_path):
    """The file doesn't pre-exist yet — the guard's `.exists()` check must
    short-circuit so a first-ever seed never needs the env var."""
    from palimpsest.webapp import seed as seedmod

    path, _ = db_path
    assert not path.exists()
    seedmod.seed()  # must not raise
