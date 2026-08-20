"""Which changed files the repair loop checks, and what it does when it cannot check them.

`test_module_load_probe.py` proves the probe itself against real subprocesses. This file is about
the SELECTION around it — which paths are asked about, and the fail-closed answer when no sandbox
is available to ask with (ADR-0051).

States enumerated before the tests (trap 43): a change with no Python in it · a healthy Python
change · a broken Python change · a Python file the agent deleted · a non-Python file alongside a
broken one · no sandbox tier at all · a sandbox refusal that carries no reason of its own.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tempest.agent import shadow as shadow_mod
from tempest.agent.orchestrator import TaskSpec, _modules_that_stopped_loading
from tempest.execute.sandbox import SandboxSelection
from tempest.prove import _FIRST_PARTY_MARKER


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        env={
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
            "PATH": "/usr/bin:/bin",
            "HOME": str(repo),
        },
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-b", "main")
    (root / "app.py").write_text("def total(xs):\n    return sum(xs)\n", encoding="utf-8")
    (root / "notes.txt").write_text("hello\n", encoding="utf-8")
    (root / ".tempest-first-party").write_text(_FIRST_PARTY_MARKER, encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "base")
    return root


@pytest.fixture(autouse=True)
def _dev_marker(monkeypatch: pytest.MonkeyPatch) -> None:
    """Select the trusted ProcessSandbox for these fixture repos.

    TWO things are required and the first draft of this fixture set only one of them: the env var
    AND a marker file whose CONTENTS match `_FIRST_PARTY_MARKER`. The empty marker the repo
    fixture writes does not match, so without this the selection fell through to the tier ladder
    and the tests were exercising whatever backend the machine happened to offer. A review caught
    it: a fixture that does not establish the condition it names is a test measuring something
    else (trap 47).
    """
    monkeypatch.setenv("TEMPEST_DEV", "1")


def _spec(repo: Path) -> TaskSpec:
    return TaskSpec(repo=repo, task_id="t", prompt="p", provider="anthropic")


class TestWhatIsChecked:
    def test_a_change_with_no_python_in_it_has_nothing_to_load(self, repo: Path) -> None:
        shadow = shadow_mod.create(repo, "t")
        shadow_mod.write(shadow, "notes.txt", "different\n")
        assert _modules_that_stopped_loading(_spec(repo), shadow) == ()

    def test_a_healthy_python_change_reports_nothing(self, repo: Path) -> None:
        shadow = shadow_mod.create(repo, "t")
        shadow_mod.write(shadow, "app.py", "def total(xs):\n    return sum(xs) + 1\n")
        assert _modules_that_stopped_loading(_spec(repo), shadow) == ()

    def test_a_broken_python_change_is_named_with_its_module_and_error(self, repo: Path) -> None:
        shadow = shadow_mod.create(repo, "t")
        shadow_mod.write(shadow, "app.py", "import no_such_module_xyz\n")
        broken = _modules_that_stopped_loading(_spec(repo), shadow)
        assert [b.path for b in broken] == ["app.py"]
        assert broken[0].module == "app"
        assert "no_such_module_xyz" in broken[0].error

    def test_a_deleted_python_file_is_reported_without_running_anything(self, repo: Path) -> None:
        """A module that is gone cannot load. Saying so beats an import traceback about a file
        the reader would then go looking for."""
        shadow = shadow_mod.create(repo, "t")
        (shadow.path / "app.py").unlink()
        broken = _modules_that_stopped_loading(_spec(repo), shadow)
        assert [b.path for b in broken] == ["app.py"]
        assert "gone" in broken[0].error

    def test_a_text_file_beside_a_broken_module_does_not_dilute_the_answer(
        self, repo: Path
    ) -> None:
        shadow = shadow_mod.create(repo, "t")
        shadow_mod.write(shadow, "notes.txt", "changed\n")
        shadow_mod.write(shadow, "app.py", "raise SystemExit(1)\n")
        broken = _modules_that_stopped_loading(_spec(repo), shadow)
        assert [b.path for b in broken] == ["app.py"]


class TestWhenNothingMayExecute:
    """L6 forbids running repo code without a sandbox tier. F3 then cannot answer its question,
    and an unanswered question is reported as a failure — never as a pass. A repair that
    succeeds *because* the machine could not look is the exact false claim this gate exists for.
    """

    def test_no_sandbox_tier_fails_closed_and_quotes_the_reason(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "tempest.agent.orchestrator.select_sandbox_for_repo",
            lambda _repo: SandboxSelection(
                None, tier="none", kind="none", assurance="none", reason="no OS-native tier"
            ),
        )
        shadow = shadow_mod.create(repo, "t")
        shadow_mod.write(shadow, "app.py", "def total(xs):\n    return sum(xs) + 1\n")
        broken = _modules_that_stopped_loading(_spec(repo), shadow)
        assert [b.path for b in broken] == ["app.py"]
        assert broken[0].error == "not checked: no OS-native tier"
        assert broken[0].module == ""

    def test_a_refusal_with_no_reason_still_says_something_useful(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "tempest.agent.orchestrator.select_sandbox_for_repo",
            lambda _repo: SandboxSelection(None, tier="none", kind="none", assurance="none"),
        )
        shadow = shadow_mod.create(repo, "t")
        shadow_mod.write(shadow, "app.py", "def total(xs):\n    return sum(xs) + 1\n")
        broken = _modules_that_stopped_loading(_spec(repo), shadow)
        assert broken[0].error == "not checked: no sandbox tier is available"


class TestOnlyWhatTheAGENTBroke:
    """The probe is differential, like everything else in this product.

    A module that does not import in this environment — a dependency nobody fetched, a file that
    was already broken when the user opened the editor — is not evidence against the attempt. The
    first version of this check was absolute and would have accused an agent of breaking a file
    that was broken before it started (found by review, ADR-0053).
    """

    def test_a_module_already_broken_at_the_baseline_is_not_the_agents_doing(
        self, tmp_path: Path
    ) -> None:
        root = tmp_path / "repo"
        root.mkdir()
        _git(root, "init", "-b", "main")
        (root / "app.py").write_text("def total(xs):\n    return sum(xs)\n", encoding="utf-8")
        # Broken BEFORE the agent ever ran, and committed that way.
        (root / "legacy.py").write_text("import a_dependency_nobody_has\n", encoding="utf-8")
        (root / ".tempest-first-party").write_text(_FIRST_PARTY_MARKER, encoding="utf-8")
        _git(root, "add", "-A")
        _git(root, "commit", "-m", "base")

        shadow = shadow_mod.create(root, "t")
        # The agent edits the broken file without fixing the import — its own change is innocent.
        shadow_mod.write(shadow, "legacy.py", "import a_dependency_nobody_has\n\nX = 1\n")
        assert _modules_that_stopped_loading(_spec(root), shadow) == ()

    def test_a_module_the_agent_broke_is_still_reported(self, tmp_path: Path) -> None:
        """The control. Same shape, except the file loaded before the agent touched it."""
        root = tmp_path / "repo"
        root.mkdir()
        _git(root, "init", "-b", "main")
        (root / "app.py").write_text("def total(xs):\n    return sum(xs)\n", encoding="utf-8")
        (root / ".tempest-first-party").write_text(_FIRST_PARTY_MARKER, encoding="utf-8")
        _git(root, "add", "-A")
        _git(root, "commit", "-m", "base")

        shadow = shadow_mod.create(root, "t")
        shadow_mod.write(shadow, "app.py", "import no_such_module_xyz\n")
        broken = _modules_that_stopped_loading(_spec(root), shadow)
        assert [b.path for b in broken] == ["app.py"]

    def test_an_ignored_path_is_never_imported(self, tmp_path: Path) -> None:
        """`[ignore].globs` is the user saying "this product does not touch that". Executing an
        ignored file to check it loads would be exactly touching it."""
        root = tmp_path / "repo"
        root.mkdir()
        _git(root, "init", "-b", "main")
        (root / "app.py").write_text("def total(xs):\n    return sum(xs)\n", encoding="utf-8")
        (root / "generated.py").write_text("X = 1\n", encoding="utf-8")
        (root / "tempest.toml").write_text('[ignore]\nglobs = ["generated.py"]\n', encoding="utf-8")
        (root / ".tempest-first-party").write_text(_FIRST_PARTY_MARKER, encoding="utf-8")
        _git(root, "add", "-A")
        _git(root, "commit", "-m", "base")

        shadow = shadow_mod.create(root, "t")
        shadow_mod.write(shadow, "generated.py", "import no_such_module_xyz\n")
        assert _modules_that_stopped_loading(_spec(root), shadow) == ()


class TestTheTwoProbesSeeTheSameWORLD:
    """The confirmed review finding the differential check alone did NOT fix (ADR-0053).

    The baseline probe runs in a `materialize`d worktree — the very one the proof just used, with
    `attach_deps` already run on it, so `.tempest-deps` is on its sys.path. The shadow never got
    that: `shadow.create` deliberately carries no `.tempest*` path across. So a changed file with
    a third-party import at module scope failed at head, loaded at baseline, and was reported as a
    cheat the agent committed — in every repository with a dependency.

    The asymmetry is in the ENVIRONMENT, not in the code, which is why a differential comparison
    of two different environments does not see it.
    """

    def _repo_with_deps(self, tmp_path: Path) -> Path:
        root = tmp_path / "repo"
        root.mkdir()
        _git(root, "init", "-b", "main")
        (root / "pyproject.toml").write_text(
            '[project]\nname = "demo"\nversion = "0.1.0"\n', encoding="utf-8"
        )
        (root / "app.py").write_text("def total(xs):\n    return sum(xs)\n", encoding="utf-8")
        (root / ".tempest-first-party").write_text(_FIRST_PARTY_MARKER, encoding="utf-8")
        _git(root, "add", "-A")
        _git(root, "commit", "-m", "base")
        return root

    def test_a_module_importable_only_through_the_deps_dir_is_not_called_broken(
        self, tmp_path: Path
    ) -> None:
        """A vendored module lives in the site dir the deps link points at — reachable from a
        worktree that has been attached, invisible to one that has not. If the shadow is not
        attached, this reads as "the agent broke app.py"."""
        root = self._repo_with_deps(tmp_path)
        shadow = shadow_mod.create(root, "t")
        shadow_mod.write(shadow, "app.py", "def total(xs):\n    return sum(xs) + 1\n")

        # One call to establish the link, then plant a module only the site dir can offer.
        _modules_that_stopped_loading(_spec(root), shadow)
        site = (shadow.path / ".tempest-deps").resolve()
        assert site.is_dir(), "the shadow must be attached at all for this test to mean anything"
        (site / "vendored_thing.py").write_text("VALUE = 1\n", encoding="utf-8")

        shadow_mod.write(
            shadow, "app.py", "import vendored_thing\n\n\ndef total(xs):\n    return sum(xs) + 1\n"
        )
        assert _modules_that_stopped_loading(_spec(root), shadow) == ()

    def test_the_shadow_is_attached_exactly_as_the_baseline_is(self, tmp_path: Path) -> None:
        """The invariant behind the case above, asserted directly: both probes run in worlds with
        the same dependency attachment, or neither comparison means anything."""
        root = self._repo_with_deps(tmp_path)
        shadow = shadow_mod.create(root, "t")
        shadow_mod.write(shadow, "app.py", "def total(xs):\n    return sum(xs) + 1\n")
        assert not (shadow.path / ".tempest-deps").exists(), "not yet — create() carries none"

        _modules_that_stopped_loading(_spec(root), shadow)
        assert (shadow.path / ".tempest-deps").is_symlink()
