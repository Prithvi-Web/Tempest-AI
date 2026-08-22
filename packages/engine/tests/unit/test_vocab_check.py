"""C3 gate pins: `vocab_check --reserved-verdicts --platform-tree` (L31).

Every check is proven to FAIL on a violating tree: a gate that cannot fail is decoration.
The subtle arms matter most — the gate must bite on real violations without crying wolf on
typed comparisons, seam code, prose, or substrings, because a noisy vocabulary lint is a
vocabulary lint someone will eventually silence.
"""

from pathlib import Path

import pytest

from tempest.dev import vocab_check

_ARGS = ["--reserved-verdicts", "--platform-tree"]


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """A minimal vendored tree that PASSES, for tests to then break one property at a time."""
    client = tmp_path / "packages" / "platform" / "client" / "src"
    client.mkdir(parents=True)
    (client / "App.tsx").write_text("export const App = () => null;\n")
    return tmp_path


def _run(root: Path) -> int:
    return vocab_check.main([*_ARGS, "--root", str(root)])


class TestPassing:
    def test_a_clean_vendored_tree_passes(
        self, tree: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert _run(tree) == 0
        assert "L31 holds" in capsys.readouterr().out

    def test_the_real_repository_passes(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert vocab_check.main(_ARGS) == 0
        assert "L31 holds" in capsys.readouterr().out

    def test_repo_root_marker_walk_finds_the_repository(self) -> None:
        assert (vocab_check._repo_root() / "packages" / "desktop").is_dir()

    def test_a_repo_with_no_platform_tree_fails_rather_than_passing_vacuously(
        self, tmp_path: Path
    ) -> None:
        assert _run(tmp_path) == 1


class TestReservedTokens:
    def test_a_reserved_token_in_vendored_source_fails(self, tree: Path) -> None:
        (tree / "packages" / "platform" / "client" / "src" / "Badge.tsx").write_text(
            'export const label = "DIVERGENT";\n'
        )
        assert _run(tree) == 1

    def test_a_token_inside_a_seam_is_our_integration_code_and_passes(self, tree: Path) -> None:
        seam = tree / "packages" / "platform" / "client" / "tempest"
        seam.mkdir(parents=True)
        (seam / "verdicts.ts").write_text('export type V = "DIVERGENT" | "UNPROVEN";\n')
        assert _run(tree) == 0

    def test_lowercase_english_is_not_the_reserved_vocabulary(self, tree: Path) -> None:
        (tree / "packages" / "platform" / "client" / "src" / "help.ts").write_text(
            'export const hint = "this claim is unproven and divergent from the docs";\n'
        )
        assert _run(tree) == 0

    def test_a_substring_is_not_a_token(self, tree: Path) -> None:
        (tree / "packages" / "platform" / "client" / "src" / "prov.ts").write_text(
            "export const UNPROVENANCE_TRACKING = 1;\n"
        )
        assert _run(tree) == 0

    def test_non_source_files_are_out_of_scope(self, tree: Path) -> None:
        (tree / "packages" / "platform" / "client" / "NOTES.md").write_text(
            "The engine may answer UNPROVEN.\n"
        )
        assert _run(tree) == 0

    def test_node_modules_are_not_scanned(self, tree: Path) -> None:
        planted = tree / "packages" / "platform" / "client" / "node_modules" / "x"
        planted.mkdir(parents=True)
        (planted / "index.js").write_text('module.exports = "DIVERGENT";\n')
        assert _run(tree) == 0


class TestFieldWrites:
    def test_writing_a_verdict_field_fails(self, tree: Path) -> None:
        (tree / "packages" / "platform" / "client" / "src" / "state.ts").write_text(
            'const message = { verdict: "looks good" };\n'
        )
        assert _run(tree) == 1

    def test_comparing_a_verdict_is_reading_not_writing(self, tree: Path) -> None:
        (tree / "packages" / "platform" / "client" / "src" / "read.ts").write_text(
            'if (target.verdict === "x") { console.log(1); }\n'
        )
        assert _run(tree) == 0

    @pytest.mark.parametrize("field", ["confidence", "risk_score", "riskScore", "reason_code"])
    def test_writing_a_confidence_shaped_field_fails(self, tree: Path, field: str) -> None:
        (tree / "packages" / "platform" / "client" / "src" / "bad.ts").write_text(
            f"const assessment = {{ {field}: 0.97 }};\n"
        )
        assert _run(tree) == 1
