"""devseed builds a real store at bench shape: N runs, one ~5 MB observation, index intact."""

import json
import sqlite3
from pathlib import Path

from tempest_api.devseed import main


def test_devseed_builds_a_bench_shaped_store(tmp_path: Path, capsys) -> None:
    data_dir = tmp_path / "data"
    assert main(["--data-dir", str(data_dir), "--runs", "50"]) == 0
    seeded = json.loads(capsys.readouterr().out)
    assert seeded["runs"] == 50

    with sqlite3.connect(data_dir / "tempest.db") as conn:
        assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 50
        payload = conn.execute(
            "SELECT detail FROM divergences WHERE id = ?", (seeded["big_divergence_id"],)
        ).fetchone()[0]
        assert len(payload) >= 5 * 1024 * 1024, "the seeded observation must be ~5 MB"
        stamp = conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        assert stamp is not None
        fts = conn.execute("SELECT COUNT(*) FROM divergences_fts").fetchone()[0]
        assert fts == 1, "seeding must go through the production open path (FTS triggers live)"
