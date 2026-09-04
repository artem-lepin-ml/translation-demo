"""seed(): all 4 matrix models registered; criteria repointed to an on-matrix model."""
from __future__ import annotations

import pytest


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    from palimpsest.webapp import db, seed as seedmod
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(db, "_conn", None)
    seedmod.seed()
    yield db
    if db._conn is not None:
        db._conn.close(); db._conn = None


def test_four_models_seeded(seeded):
    conn = seeded.connect()
    assert conn.execute("SELECT COUNT(*) n FROM model").fetchone()["n"] == 4


def test_criteria_point_at_matrix_model(seeded):
    from palimpsest.webapp.model_matrix import MATRIX
    conn = seeded.connect()
    for r in conn.execute("SELECT DISTINCT model_name FROM criterion"):
        assert r["model_name"] in MATRIX, "criterion still points off-matrix"


def test_idx1_paragraph_has_terms(seeded):
    # Real Phase C terminology for this paragraph (demo seed) carries 6
    # identified_terms — was >=10 against the old placeholder-seed content.
    conn = seeded.connect()
    n = conn.execute(
        "SELECT COUNT(*) n FROM term t JOIN paragraph p ON p.id=t.paragraph_id WHERE p.idx=1"
    ).fetchone()["n"]
    assert n >= 6
