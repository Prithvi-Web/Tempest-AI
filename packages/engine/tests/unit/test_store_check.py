"""C1 gate pins: `store_check --no-sspl-binaries --no-proof-data-in-document-store`.

L33 — the document store is never SSPL, and never a second datastore for proofs. Every check is
proven to FAIL on a violating tree: a gate that cannot fail is decoration.
"""

import json
from pathlib import Path

import pytest

from tempest.dev import store_check

_BOTH = ["--no-sspl-binaries", "--no-proof-data-in-document-store"]


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """A minimal tree that PASSES both flags, for tests to then break one property at a time."""
    engine = tmp_path / "packages" / "engine" / "src" / "tempest"
    engine.mkdir(parents=True)
    (engine / "store.py").write_text("import sqlite3\n")
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "MERGE-CONTRACT.md").write_text(
        "## Declared cross-store references (L33)\n\n"
        "| From | Field | To | Nullable |\n"
        "|---|---|---|---|\n"
        "| platform `messages` | `tempest_bundle_id` | engine `bundles.id` | yes |\n"
    )
    data = tmp_path / "packages" / "platform" / "data"
    data.mkdir(parents=True)
    (data / "package.json").write_text(
        json.dumps(
            {
                # mongoose (MIT) and the mongodb driver (Apache-2.0) are permissive: the data
                # MODEL is adopted, the SSPL server is not — that distinction is ADR-0068.
                "dependencies": {"mongoose": "^8.0.0", "mongodb": "^6.0.0"},
                # The downloader in devDependencies is test-only tooling that never ships.
                "devDependencies": {"mongodb-memory-server": "^9.0.0"},
            }
        )
    )
    return tmp_path


def _run(root: Path, *flags: str) -> int:
    return store_check.main([*(flags or _BOTH), "--root", str(root)])


class TestPassing:
    def test_a_clean_tree_passes_both_flags(
        self, tree: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert _run(tree) == 0
        assert "L33 holds" in capsys.readouterr().out

    def test_the_real_repository_passes(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert store_check.main(_BOTH) == 0
        assert "L33 holds" in capsys.readouterr().out

    def test_repo_root_marker_walk_finds_the_repository(self) -> None:
        assert (store_check._repo_root() / "packages" / "desktop").is_dir()

    def test_no_flags_is_refused(self, tree: Path) -> None:
        """A gate invoked to check nothing must say so rather than print green."""
        with pytest.raises(SystemExit):
            store_check.main(["--root", str(tree)])


class TestSsplBinaries:
    def test_a_file_named_mongod_fails(self, tree: Path) -> None:
        (tree / "packages" / "platform" / "data" / "mongod").write_bytes(b"\x7fELF")
        assert _run(tree) == 1

    def test_a_windows_server_binary_fails_by_stem(self, tree: Path) -> None:
        (tree / "mongos.exe").write_bytes(b"MZ")
        assert _run(tree) == 1

    def test_sspl_license_text_fails(self, tree: Path) -> None:
        (tree / "packages" / "platform" / "data" / "LICENSE-server.txt").write_text(
            "Server Side Public License\nVERSION 1\n"
        )
        assert _run(tree) == 1

    def test_runtime_dependency_on_the_mongod_downloader_fails(self, tree: Path) -> None:
        pkg = tree / "packages" / "platform" / "data" / "package.json"
        pkg.write_text(json.dumps({"dependencies": {"mongodb-memory-server": "^9.0.0"}}))
        assert _run(tree) == 1

    def test_dev_dependency_on_the_downloader_is_allowed(self, tree: Path) -> None:
        """Already the fixture's shape; pinned on its own so the distinction cannot erode."""
        pkg = json.loads((tree / "packages" / "platform" / "data" / "package.json").read_text())
        assert "mongodb-memory-server" in pkg["devDependencies"]
        assert _run(tree) == 0

    def test_malformed_manifest_with_the_downloader_still_fails(self, tree: Path) -> None:
        """The paranoid reader: an unclosed brace must not let the downloader slip past."""
        (tree / "packages" / "platform" / "data" / "package.json").write_text(
            '{"dependencies": {"mongodb-memory-server": "^9.0.0"'
        )
        assert _run(tree) == 1

    def test_manifest_without_dependencies_passes(self, tree: Path) -> None:
        (tree / "packages" / "platform" / "data" / "package.json").write_text(
            json.dumps({"name": "x"})
        )
        assert _run(tree) == 0

    def test_build_output_directories_are_not_scanned(self, tree: Path) -> None:
        """`node_modules` is not repository content; the claim is about what the repo carries."""
        planted = tree / "node_modules" / ".bin"
        planted.mkdir(parents=True)
        (planted / "mongod").write_bytes(b"\x7fELF")
        assert _run(tree) == 0


class TestProofDataStaysInSqlite:
    @pytest.mark.parametrize("statement", ["import pymongo", "from motor import core"])
    def test_engine_importing_a_document_store_client_fails(
        self, tree: Path, statement: str
    ) -> None:
        (tree / "packages" / "engine" / "src" / "tempest" / "bad.py").write_text(statement + "\n")
        assert _run(tree) == 1

    def test_the_client_name_in_prose_or_strings_does_not_fail(self, tree: Path) -> None:
        """Trap 25's class: the gate must match the import statement, never its discussion."""
        (tree / "packages" / "engine" / "src" / "tempest" / "doc.py").write_text(
            '"""Never import pymongo here."""\nNAME = "pymongo"\n'
        )
        assert _run(tree) == 0

    def test_missing_merge_contract_fails(self, tree: Path) -> None:
        (tree / "docs" / "MERGE-CONTRACT.md").unlink()
        assert _run(tree) == 1

    def test_cross_store_table_with_no_rows_fails(self, tree: Path) -> None:
        (tree / "docs" / "MERGE-CONTRACT.md").write_text(
            "## Declared cross-store references (L33)\n\n| From | Field | To |\n|---|---|---|\n"
        )
        assert _run(tree) == 1

    def test_sspl_flag_alone_skips_the_document_store_checks(self, tree: Path) -> None:
        (tree / "docs" / "MERGE-CONTRACT.md").unlink()
        assert _run(tree, "--no-sspl-binaries") == 0


class TestReviewPins:
    """Pins for the C1 adversarial-review findings (S1-S7) — each was a real bypass."""

    def test_tracked_content_in_a_skip_named_directory_is_still_scanned(self, tree: Path) -> None:
        """S1: `dist/` is skipped as build output by NAME, but git-tracked content is repo
        content and must be scanned wherever it sits."""
        import subprocess

        def git(*args: str) -> None:
            subprocess.run(["git", "-C", str(tree), *args], capture_output=True, check=True)

        git("init", "-q")
        git("config", "user.email", "pin@test")
        git("config", "user.name", "pin")
        hidden = tree / "packages" / "platform" / "server" / "dist"
        hidden.mkdir(parents=True)
        (hidden / "mongod").write_bytes(b"\x7fELF")
        git("add", "-A")
        git("commit", "-qm", "smuggle")
        assert _run(tree) == 1

    def test_a_decoy_dependencies_string_cannot_mask_the_real_block(self, tree: Path) -> None:
        """S2: the manifest is parsed as JSON first — a quoted decoy must not aim the check
        at the wrong braces."""
        (tree / "packages" / "platform" / "data" / "package.json").write_text(
            '{"description": "see \\"dependencies\\": {} for details",'
            ' "dependencies": {"mongodb-memory-server": "^9.0.0"}}'
        )
        assert _run(tree) == 1

    def test_a_comma_form_import_is_found(self, tree: Path) -> None:
        """S3: `import sys, pymongo` is a static import too — AST sees what a line-anchored
        regex missed."""
        (tree / "packages" / "engine" / "src" / "tempest" / "sneak.py").write_text(
            "import sys, pymongo\n"
        )
        assert _run(tree) == 1

    def test_an_import_statement_inside_a_docstring_is_not_an_import(self, tree: Path) -> None:
        (tree / "packages" / "engine" / "src" / "tempest" / "docd.py").write_text(
            '"""Example:\nimport pymongo\n"""\nX = 1\n'
        )
        assert _run(tree) == 0

    def test_an_unparseable_file_falls_back_to_the_textual_scan(self, tree: Path) -> None:
        (tree / "packages" / "engine" / "src" / "tempest" / "broken.py").write_text(
            "def broken(:\nimport pymongo\n"
        )
        assert _run(tree) == 1

    def test_placeholder_rows_do_not_satisfy_the_cross_store_table(self, tree: Path) -> None:
        """S5: an emptied table full of em-dashes is a declaration of nothing."""
        (tree / "docs" / "MERGE-CONTRACT.md").write_text(
            "## Declared cross-store references (L33)\n\n"
            "| From | Field | To |\n|---|---|---|\n| — | — | — |\n"
        )
        assert _run(tree) == 1

    def test_a_prettified_separator_is_not_a_data_row(self, tree: Path) -> None:
        (tree / "docs" / "MERGE-CONTRACT.md").write_text(
            "## Declared cross-store references (L33)\n\n"
            "| From | Field | To |\n| --- | --- | --- |\n"
            "| platform `runs` | `tempest_run_id` | engine `runs.id` |\n"
        )
        assert _run(tree) == 0

    def test_a_symlink_cycle_does_not_hang_or_crash_the_walk(self, tree: Path) -> None:
        """S6: symlinks are skipped whole — a cycle must not loop and a link cannot BE the
        binary."""
        (tree / "packages" / "platform" / "loop").symlink_to(tree / "packages")
        assert _run(tree) == 0

    def test_a_bad_root_fails_cleanly_rather_than_crashing(self, tmp_path: Path) -> None:
        assert store_check.main([*_BOTH, "--root", str(tmp_path / "nope")]) == 1

    def test_the_british_spelling_of_licence_is_scanned(self, tree: Path) -> None:
        """S7: SSPL text behind `LICENCE` is the same problem wearing different vowels."""
        (tree / "packages" / "platform" / "data" / "LICENCE.md").write_text(
            "Server Side Public License\n"
        )
        assert _run(tree) == 1
