"""The load probe — F3's answer to "does the changed file still run at all?" (ADR-0051).

Every case here is a REAL subprocess importing a REAL file (L4). There is no static substitute
for this question, which is the whole reason the probe exists: `import no_such_module_xyz` parses
perfectly and `ast.parse` is happy right up to the moment the interpreter is not.

States enumerated before the tests (trap 43): a module that imports · a module whose import
raises · a module that does not exist · a module that raises SystemExit at load · a module inside
a `src/` layout · a module that kills its own process without a word · a worker that answers
nothing · a probe that times out.
"""

from pathlib import Path

import pytest

from tempest.execute.runner import LoadProbe, module_for_path, module_loads, module_name_for
from tempest.execute.sandbox import ProcessSandbox

SANDBOX = ProcessSandbox()


def _repo(tmp_path: Path, files: dict[str, str]) -> Path:
    """Paths are written literally.

    The first version took `**files` and turned `__` into `/`, which made
    `src__pkg____init__.py` mean `src/pkg//init/.py` — so the package it claimed to build had no
    `__init__.py` at all, and the test passed only because namespace packages exist. A review
    caught it: a fixture that does not build what it says is a test measuring something else.
    """
    root = tmp_path / "repo"
    root.mkdir(parents=True, exist_ok=True)
    for name, body in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    return root


class TestModulesThatLoad:
    def test_an_ordinary_module_loads(self, tmp_path: Path) -> None:
        root = _repo(tmp_path, {"app.py": "def total(xs):\n    return sum(xs)\n"})
        got = module_loads(root, "app", SANDBOX)
        assert got == LoadProbe(module="app", loads=True, error="")

    def test_a_module_under_src_loads_through_the_same_sys_path_the_workers_use(
        self, tmp_path: Path
    ) -> None:
        root = _repo(
            tmp_path,
            {
                "src/pkg/__init__.py": "PACKAGE = True\n",
                "src/pkg/app.py": "from pkg import PACKAGE\n",
            },
        )
        assert (root / "src" / "pkg" / "__init__.py").is_file(), "the fixture built what it claims"
        assert module_loads(root, "pkg.app", SANDBOX).loads

    def test_import_time_side_effects_are_allowed_to_happen(self, tmp_path: Path) -> None:
        """The probe asks whether the module loads, not whether loading it was tidy. A module
        that prints, opens a file, or computes at import time is ordinary Python."""
        root = _repo(tmp_path, {"app.py": "print('hello from import time')\nX = sum(range(10))\n"})
        assert module_loads(root, "app", SANDBOX).loads


class TestModulesThatDoNot:
    def test_a_missing_import_is_reported_with_its_exception(self, tmp_path: Path) -> None:
        """The §0 defect, at the layer that catches it: byte-identical function, broken file."""
        root = _repo(
            tmp_path,
            {"app.py": "import no_such_module_xyz\n\n\ndef total(xs):\n    return sum(xs)\n"},
        )
        got = module_loads(root, "app", SANDBOX)
        assert not got.loads
        assert "no_such_module_xyz" in got.error
        assert "ModuleNotFoundError" in got.error

    def test_a_module_that_does_not_exist_does_not_load(self, tmp_path: Path) -> None:
        root = _repo(tmp_path, {"app.py": "X = 1\n"})
        assert not module_loads(root, "nothing_here", SANDBOX).loads

    def test_a_syntax_error_does_not_load(self, tmp_path: Path) -> None:
        root = _repo(tmp_path, {"app.py": "def total(xs:\n    oops\n"})
        got = module_loads(root, "app", SANDBOX)
        assert not got.loads and "SyntaxError" in got.error

    def test_an_exception_raised_at_import_time_does_not_load(self, tmp_path: Path) -> None:
        root = _repo(tmp_path, {"app.py": "raise ValueError('nope')\n"})
        got = module_loads(root, "app", SANDBOX)
        assert not got.loads and "ValueError" in got.error

    def test_a_module_level_sys_exit_is_a_load_failure_not_a_success(self, tmp_path: Path) -> None:
        """`SystemExit` inherits from BaseException, so a narrower `except Exception` would let
        the single most destructive import-time statement through as a pass."""
        root = _repo(tmp_path, {"app.py": "import sys\nsys.exit(3)\n"})
        got = module_loads(root, "app", SANDBOX)
        assert not got.loads and "SystemExit" in got.error

    def test_a_module_that_kills_the_process_is_a_load_failure(self, tmp_path: Path) -> None:
        """No traceback, no protocol line, nothing to catch. The conservative direction is the
        only safe one: a module nobody could load is not evidence the module is fine."""
        root = _repo(tmp_path, {"app.py": "import os\nos._exit(0)\n"})
        got = module_loads(root, "app", SANDBOX)
        assert not got.loads and "no answer" in got.error


class TestTheProbeItself:
    def test_a_timeout_is_a_load_failure_that_says_it_timed_out(self, tmp_path: Path) -> None:
        """A module that never finishes importing has not imported. Real sleep, real timeout."""
        root = _repo(tmp_path, {"app.py": "import time\ntime.sleep(30)\n"})
        got = module_loads(root, "app", SANDBOX, timeout=2.0)
        assert not got.loads and "timed out" in got.error

    def test_garbled_output_before_the_answer_is_skipped_not_believed(self, tmp_path: Path) -> None:
        """Target code can write to fd 1. The runner isolates the protocol fd, and lines that are
        not parseable protocol are stepped over rather than read as a verdict."""
        root = _repo(
            tmp_path,
            {"app.py": "import os\nos.write(1, b'{not json at all\\n')\nX = 1\n"},
        )
        assert module_loads(root, "app", SANDBOX).loads


class TestPathToModuleName:
    """One rule, one owner. Two callers now need it — the proof pipeline and this probe — and a
    second copy would be a second answer to "which module is this file"."""

    @pytest.mark.parametrize(
        ("path", "roots", "expected"),
        [
            ("app.py", (), "app"),
            ("pkg/app.py", (), "pkg.app"),
            ("src/pkg/app.py", (), "pkg.app"),
            ("lib/pkg/app.py", ("lib",), "pkg.app"),
            ("lib/deep/pkg/app.py", ("lib", "lib/deep"), "pkg.app"),
            ("lib", ("lib",), "lib"),
        ],
    )
    def test_the_layout_rules(self, path: str, roots: tuple[str, ...], expected: str) -> None:
        assert module_name_for(path, roots) == expected

    def test_the_worktree_supplies_its_own_roots(self, tmp_path: Path) -> None:
        root = _repo(tmp_path, {"lib__pkg__app.py": "X = 1\n"})
        (root / "tempest.toml").write_text('[roots]\nsource = ["lib"]\n', encoding="utf-8")
        assert module_for_path(root, "lib/pkg/app.py") == "pkg.app"

    def test_a_repo_with_no_config_gets_the_conventional_answer(self, tmp_path: Path) -> None:
        root = _repo(tmp_path, {"app.py": "X = 1\n"})
        assert module_for_path(root, "app.py") == "app"


class TestTheNameMustResolveToTheFileUnderJudGEMENT:
    """Reproduced by the review against live code, twice, and both are closed here.

    A dotted name is not a file. The scratch mount carries the worker's own modules, and
    `[roots].source` in the worktree's `tempest.toml` is a path list an AGENT can write, because
    a config file is not a credential. Either can put a healthy file ahead of the broken one and
    turn "does this module still load?" into "does something with that name still load?".
    """

    def test_a_name_that_resolves_to_a_different_file_is_a_failure(self, tmp_path: Path) -> None:
        """The §0 cheat, second edition: break `lib/app.py`, add a healthy `shim/app.py`, and
        point the repo's own source roots at the shim first."""
        root = _repo(
            tmp_path,
            {
                "lib/app.py": "import no_such_module_xyz\n\n\ndef total(xs):\n    return sum(xs)\n",
                "shim/app.py": "def total(xs):\n    return sum(xs)\n",
                "tempest.toml": '[roots]\nsource = ["shim", "lib"]\n',
            },
        )
        got = module_loads(root, "app", SANDBOX, expect_file=root / "lib" / "app.py")
        assert not got.loads
        assert "resolved to" in got.error and "shim" in got.error

    def test_the_matching_file_still_passes(self, tmp_path: Path) -> None:
        """The control. Same layout, nothing broken — the check must not refuse everything."""
        root = _repo(
            tmp_path,
            {
                "lib/app.py": "def total(xs):\n    return sum(xs)\n",
                "tempest.toml": '[roots]\nsource = ["lib"]\n',
            },
        )
        assert module_loads(root, "app", SANDBOX, expect_file=root / "lib" / "app.py").loads

    def test_a_repo_module_shadowed_by_the_scratch_mount_is_a_failure(self, tmp_path: Path) -> None:
        """`canonical` is one of the worker's own modules, copied into the scratch directory the
        worker puts on sys.path. A repo file of that name is never the one that imports."""
        root = _repo(tmp_path, {"canonical.py": "import no_such_module_xyz\n"})
        got = module_loads(root, "canonical", SANDBOX, expect_file=root / "canonical.py")
        assert not got.loads, "the repo's own canonical.py never got a chance to fail"
        assert "resolved to" in got.error

    def test_without_an_expected_file_the_probe_only_answers_about_the_name(
        self, tmp_path: Path
    ) -> None:
        """Stated so the weaker mode is a choice rather than an oversight. Nothing in the agent
        path uses it; it exists for callers whose question really is about a name."""
        root = _repo(tmp_path, {"app.py": "X = 1\n"})
        assert module_loads(root, "app", SANDBOX).loads

    def test_a_namespace_package_with_no_file_of_its_own_is_a_failure(self, tmp_path: Path) -> None:
        """`__file__` is None for a namespace package, so nothing proves the directory that
        imported is the file being judged."""
        root = _repo(tmp_path, {"pkg/app.py": "X = 1\n"})
        got = module_loads(root, "pkg", SANDBOX, expect_file=root / "pkg" / "__init__.py")
        assert not got.loads and "no file of its own" in got.error
