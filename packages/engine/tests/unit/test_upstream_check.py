"""C1 gate pins: `python -m tempest.dev.upstream_check --max-inline-deltas 40 --ledger-complete`.

L27 — upstream mergeability is a shipped feature. Every check is proven to FAIL on a violating
tree, not merely to pass on the real one: a gate that cannot fail is decoration. Fixtures are
real git repositories, because the gate's drift check is a claim about git state and a faked
`git diff` would measure the fake (L4's discipline applied to a dev gate).
"""

import subprocess
from pathlib import Path

import pytest

from tempest.dev import upstream_check

_FAKE_UPSTREAM_SHA = "d" * 40


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True
    ).stdout


def _upstream_md(baseline: str, ledger_rows: list[tuple[str, str]] | None = None) -> str:
    rows = ledger_rows or []
    body = "\n".join(f"| `{path}` | {reason} | — |" for path, reason in rows)
    table = body or "| *(none)* | — | — |"
    return (
        "# UPSTREAM\n\n"
        f"- **Adopted commit:** {_FAKE_UPSTREAM_SHA}\n"
        f"- **Vendor baseline:** {baseline}\n\n"
        "## Inline-delta ledger\n\n"
        "| Path | Reason | Upstream issue |\n"
        "|---|---|---|\n"
        f"{table}\n"
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A real git repo with a vendored platform tree and a correct UPSTREAM.md — the passing
    state, for tests to then break one property at a time."""
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "pin@test")
    _git(tmp_path, "config", "user.name", "pin")
    platform = tmp_path / "packages" / "platform"
    (platform / "server").mkdir(parents=True)
    (platform / "server" / "app.js").write_text("original\n")
    (platform / "UPSTREAM.md").write_text(_upstream_md("PENDING"))
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "vendor")
    baseline = _git(tmp_path, "rev-parse", "HEAD").strip()
    # The follow-up commit writes the baseline — it touches only UPSTREAM.md, which is exempt,
    # exactly the shape of the real vendoring flow.
    (platform / "UPSTREAM.md").write_text(_upstream_md(baseline))
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "baseline")
    return tmp_path


def _run(root: Path, *extra: str) -> int:
    return upstream_check.main(
        ["--max-inline-deltas", "40", "--ledger-complete", "--root", str(root), *extra]
    )


def _baseline_of(root: Path) -> str:
    body = (root / "packages" / "platform" / "UPSTREAM.md").read_text()
    for line in body.splitlines():
        if line.startswith("- **Vendor baseline:**"):
            return line.split("**Vendor baseline:**")[1].strip()
    raise AssertionError("fixture has no baseline line")


class TestPassing:
    def test_clean_vendored_tree_passes(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert _run(repo) == 0
        assert "mergeability intact" in capsys.readouterr().out

    def test_the_real_repository_passes(self, capsys: pytest.CaptureFixture[str]) -> None:
        """The shipped UPSTREAM.md parses and the real tree carries no undeclared drift."""
        assert upstream_check.main(["--max-inline-deltas", "40", "--ledger-complete"]) == 0
        assert "mergeability intact" in capsys.readouterr().out

    def test_repo_root_marker_walk_finds_the_repository(self) -> None:
        assert (upstream_check._repo_root() / "packages" / "desktop").is_dir()


class TestStructure:
    def test_missing_upstream_md_fails(self, repo: Path) -> None:
        (repo / "packages" / "platform" / "UPSTREAM.md").unlink()
        assert _run(repo) == 1

    def test_missing_adopted_commit_line_fails(self, repo: Path) -> None:
        md = repo / "packages" / "platform" / "UPSTREAM.md"
        md.write_text(md.read_text().replace("- **Adopted commit:**", "- adopted:"))
        assert _run(repo) == 1

    def test_adopted_line_without_forty_hex_fails(self, repo: Path) -> None:
        md = repo / "packages" / "platform" / "UPSTREAM.md"
        md.write_text(md.read_text().replace(_FAKE_UPSTREAM_SHA, "HEAD"))
        assert _run(repo) == 1

    def test_missing_baseline_line_fails(self, repo: Path) -> None:
        md = repo / "packages" / "platform" / "UPSTREAM.md"
        md.write_text(md.read_text().replace("- **Vendor baseline:**", "- baseline:"))
        assert _run(repo) == 1

    def test_unresolvable_baseline_fails(self, repo: Path) -> None:
        """A 40-hex string that is not a commit in THIS repo is a fictional reference point."""
        md = repo / "packages" / "platform" / "UPSTREAM.md"
        md.write_text(md.read_text().replace(_baseline_of(repo), "a" * 40))
        assert _run(repo) == 1


class TestDrift:
    def test_undeclared_committed_drift_fails(self, repo: Path) -> None:
        (repo / "packages" / "platform" / "server" / "app.js").write_text("edited\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "edit")
        assert _run(repo) == 1

    def test_declared_drift_passes(self, repo: Path) -> None:
        (repo / "packages" / "platform" / "server" / "app.js").write_text("edited\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "edit")
        md = repo / "packages" / "platform" / "UPSTREAM.md"
        md.write_text(
            _upstream_md(
                _baseline_of(repo),
                [("packages/platform/server/app.js", "pin: a declared inline delta")],
            )
        )
        assert _run(repo) == 0

    def test_undeclared_uncommitted_edit_fails(self, repo: Path) -> None:
        """The gate reads the working tree, not just HEAD — verify runs on the working tree."""
        (repo / "packages" / "platform" / "server" / "app.js").write_text("dirty\n")
        assert _run(repo) == 1

    def test_undeclared_untracked_file_fails(self, repo: Path) -> None:
        (repo / "packages" / "platform" / "server" / "new.js").write_text("new\n")
        assert _run(repo) == 1

    def test_staged_rename_must_declare_the_new_path(self, repo: Path) -> None:
        _git(repo, "mv", "packages/platform/server/app.js", "packages/platform/server/app2.js")
        assert _run(repo) == 1

    def test_seam_directory_changes_are_exempt(self, repo: Path) -> None:
        """`packages/platform/<pkg>/tempest/**` is the declared integration seam (L27)."""
        seam = repo / "packages" / "platform" / "server" / "tempest"
        seam.mkdir()
        (seam / "seam.js").write_text("integration\n")
        assert _run(repo) == 0

    def test_upstream_md_edits_are_exempt(self, repo: Path) -> None:
        md = repo / "packages" / "platform" / "UPSTREAM.md"
        md.write_text(md.read_text() + "\nnote appended, uncommitted\n")
        assert _run(repo) == 0

    def test_drift_outside_the_platform_tree_is_out_of_scope(self, repo: Path) -> None:
        (repo / "elsewhere.txt").write_text("not platform\n")
        assert _run(repo) == 0


class TestLedgerHygiene:
    def test_stale_ledger_row_fails(self, repo: Path) -> None:
        """A row for a path that no longer differs is a map disagreeing with the territory."""
        md = repo / "packages" / "platform" / "UPSTREAM.md"
        md.write_text(
            _upstream_md(
                _baseline_of(repo),
                [("packages/platform/server/app.js", "claims a delta that does not exist")],
            )
        )
        assert _run(repo) == 1

    def test_row_without_a_reason_fails(self, repo: Path) -> None:
        (repo / "packages" / "platform" / "server" / "app.js").write_text("edited\n")
        md = repo / "packages" / "platform" / "UPSTREAM.md"
        md.write_text(_upstream_md(_baseline_of(repo), [("packages/platform/server/app.js", "")]))
        assert _run(repo) == 1

    def test_row_count_over_the_cap_fails(self, repo: Path) -> None:
        paths = []
        for index in range(3):
            path = repo / "packages" / "platform" / "server" / f"d{index}.js"
            path.write_text("delta\n")
            paths.append((f"packages/platform/server/d{index}.js", "pin"))
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "three deltas")
        md = repo / "packages" / "platform" / "UPSTREAM.md"
        md.write_text(_upstream_md(_baseline_of(repo), paths))
        assert (
            upstream_check.main(
                ["--max-inline-deltas", "2", "--ledger-complete", "--root", str(repo)]
            )
            == 1
        )

    def test_rows_at_exactly_the_cap_pass(self, repo: Path) -> None:
        (repo / "packages" / "platform" / "server" / "app.js").write_text("edited\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "edit")
        md = repo / "packages" / "platform" / "UPSTREAM.md"
        md.write_text(
            _upstream_md(_baseline_of(repo), [("packages/platform/server/app.js", "pin")])
        )
        assert (
            upstream_check.main(
                ["--max-inline-deltas", "1", "--ledger-complete", "--root", str(repo)]
            )
            == 0
        )


class TestReviewPins:
    """Pins for the C1 adversarial-review findings (U1-U6) — each was a real bypass."""

    def test_rename_into_a_seam_still_surfaces_the_vanished_original(self, repo: Path) -> None:
        """U1: `git mv vendored-file <pkg>/tempest/` must not delete it with zero trace —
        renames count as delete + add, and the delete side needs a ledger row."""
        seam = repo / "packages" / "platform" / "server" / "tempest"
        seam.mkdir()
        _git(
            repo, "mv", "packages/platform/server/app.js", "packages/platform/server/tempest/app.js"
        )
        _git(repo, "commit", "-qm", "sneak")
        assert _run(repo) == 1
        md = repo / "packages" / "platform" / "UPSTREAM.md"
        md.write_text(
            _upstream_md(
                _baseline_of(repo),
                [("packages/platform/server/app.js", "moved into the seam — delete declared")],
            )
        )
        assert _run(repo) == 0

    def test_an_untracked_directory_is_enumerated_per_file(self, repo: Path) -> None:
        """U2: one `?? dir/` status entry must not let a single row declare unbounded files."""
        patch = repo / "packages" / "platform" / "server" / "patch"
        patch.mkdir()
        (patch / "a.js").write_text("a\n")
        (patch / "b.js").write_text("b\n")
        md = repo / "packages" / "platform" / "UPSTREAM.md"
        md.write_text(
            _upstream_md(_baseline_of(repo), [("packages/platform/server/patch/", "a dir row")])
        )
        assert _run(repo) == 1  # the two files are undeclared; the dir row is stale
        md.write_text(
            _upstream_md(
                _baseline_of(repo),
                [
                    ("packages/platform/server/patch/a.js", "pin"),
                    ("packages/platform/server/patch/b.js", "pin"),
                ],
            )
        )
        assert _run(repo) == 0

    def test_a_plain_file_named_tempest_is_not_a_seam(self, repo: Path) -> None:
        """U3: the seam exemption is for paths INSIDE `<pkg>/tempest/`, never a file so named."""
        (repo / "packages" / "platform" / "server" / "tempest").write_text("not a seam\n")
        assert _run(repo) == 1

    def test_a_non_ascii_path_round_trips_between_git_and_the_ledger(self, repo: Path) -> None:
        """U4: quotePath off — `café.js` must match its ledger row byte-identically."""
        target = repo / "packages" / "platform" / "server" / "café.js"
        target.write_text("accent\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "accent")
        assert _run(repo) == 1
        md = repo / "packages" / "platform" / "UPSTREAM.md"
        md.write_text(
            _upstream_md(_baseline_of(repo), [("packages/platform/server/café.js", "pin")])
        )
        assert _run(repo) == 0

    def test_a_fenced_example_field_is_documentation_not_structure(self, repo: Path) -> None:
        """U5: a doc example inside a fence must not retarget the baseline."""
        md = repo / "packages" / "platform" / "UPSTREAM.md"
        md.write_text(
            "```markdown\n- **Vendor baseline:** " + "b" * 40 + "\n```\n" + md.read_text()
        )
        assert _run(repo) == 0

    def test_duplicate_baseline_lines_are_ambiguous_and_fail(self, repo: Path) -> None:
        md = repo / "packages" / "platform" / "UPSTREAM.md"
        md.write_text(md.read_text() + f"\n- **Vendor baseline:** {'c' * 40}\n")
        assert _run(repo) == 1

    def test_a_prettified_separator_is_not_a_stale_row(self, repo: Path) -> None:
        """U6: `| --- | --- | --- |` is a separator in any dialect, never a data row."""
        md = repo / "packages" / "platform" / "UPSTREAM.md"
        md.write_text(md.read_text().replace("|---|---|---|", "| --- | --- | --- |"))
        assert _run(repo) == 0

    def test_finder_junk_is_exempt(self, repo: Path) -> None:
        """Opening a folder in Finder must not redden the gate."""
        (repo / "packages" / "platform" / "server" / ".DS_Store").write_bytes(b"\x00junk")
        assert _run(repo) == 0


class TestFixWavePins:
    """Pins for the trap-48 review of the fix wave itself (D3)."""

    def test_a_tilde_fenced_example_is_documentation_too(self, repo: Path) -> None:
        """D3: CommonMark fences come in tildes as well as backticks — a tilde-fenced example
        field must neither retarget the baseline nor read as an ambiguous duplicate."""
        md = repo / "packages" / "platform" / "UPSTREAM.md"
        md.write_text(
            "~~~markdown\n- **Vendor baseline:** " + "b" * 40 + "\n~~~\n" + md.read_text()
        )
        assert _run(repo) == 0
