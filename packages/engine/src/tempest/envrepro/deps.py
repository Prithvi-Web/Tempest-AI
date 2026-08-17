"""Stage-2 environment reproduction, the security-first slice (ADR-0027).

Two facts made real repos fail wholesale (docs/METRICS.md): `importlib.metadata` lookups
on the package under test, and uninstalled third-party imports. This layer fixes both
WITHOUT ever executing repo code outside the sandbox:

- Metadata comes from STATIC `pyproject.toml` parsing — a `.dist-info` shim satisfies
  `importlib.metadata` while the code itself keeps importing from the worktree.
- Dependencies install as WHEELS ONLY (`uv pip install --target … --only-binary :all:`):
  a wheel unpack runs no setup hooks, no build backends, no scripts.
- The default run is OFFLINE (`--offline` against uv's cache). Fetching is an explicit
  opt-in (`--fetch-deps` / `TEMPEST_FETCH_DEPS=1`), and the fingerprint-keyed cache makes
  every later run offline again (L8) — the same once-then-offline shape as the adapter
  cache (ADR-0024).

Failure is stated, never hidden: an incomplete materialization returns the exact
remediation, and the prove pipeline attaches it to the import-failure UNPROVEN.
"""

import ast
import hashlib
import os
import shutil
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

_SHIM_VERSION_FALLBACK = "0.0.0+tempest-unresolved"


@dataclass(frozen=True)
class ProjectMetadata:
    name: str | None  # None = statically unresolvable (never guessed, never executed)
    version: str
    dependencies: tuple[str, ...]


@dataclass(frozen=True)
class DepsResult:
    site_dir: Path | None  # append to worker sys.path when set
    detail: str | None  # why materialization is incomplete (with the fix), else None
    fetched: bool = False


def fetch_enabled() -> bool:
    return os.environ.get("TEMPEST_FETCH_DEPS") == "1"


def project_metadata(worktree: Path) -> ProjectMetadata | None:
    """Static read of `[project]` (setup.py AST as fallback) — repo code is never
    imported or executed here."""
    pyproject = worktree / "pyproject.toml"
    if not pyproject.exists():
        return _setup_py_metadata(worktree)
    try:
        raw = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError):
        return None  # unreadable metadata → nothing to materialize; imports tell the truth
    project = raw.get("project")
    if not isinstance(project, dict):
        return _setup_py_metadata(worktree)
    name = project.get("name")
    if not isinstance(name, str) or not name:
        return None
    version = project.get("version")
    if not isinstance(version, str) or not version:
        # dynamic version: a stable placeholder still satisfies metadata LOOKUPS while
        # being self-evidently synthetic in any displayed string.
        version = _SHIM_VERSION_FALLBACK
    deps_raw = project.get("dependencies")
    dependencies = (
        tuple(d for d in deps_raw if isinstance(d, str)) if isinstance(deps_raw, list) else ()
    )
    return ProjectMetadata(name=name, version=version, dependencies=dependencies)


def materialize_deps(
    worktree: Path,
    cache: Path,
    *,
    fetch: bool,
    find_links: Path | None = None,
) -> DepsResult:
    """Build (or reuse) the fingerprint-keyed site dir for this worktree's declared deps."""
    meta = project_metadata(worktree)
    if meta is None:
        return DepsResult(site_dir=None, detail=None)
    if meta.version == _SHIM_VERSION_FALLBACK:
        # A dynamic version's honest source is the vcs itself — the same place hatch-vcs
        # and setuptools-scm read from at build time.
        described = _git_describe_version(worktree)
        if described is not None:
            meta = ProjectMetadata(meta.name, described, meta.dependencies)
    _write_version_file_shims(worktree, meta.version)

    key_material = "\n".join(
        [meta.name or "?", meta.version, *sorted(meta.dependencies), sys.version.split()[0]]
    )
    key = hashlib.sha256(key_material.encode()).hexdigest()[:16]
    site_dir = cache / "deps" / key
    done_marker = site_dir / ".tempest-deps-complete"
    if done_marker.exists():
        return DepsResult(site_dir=site_dir, detail=None)

    site_dir.mkdir(parents=True, exist_ok=True)
    if meta.name is not None:
        _write_dist_info_shim(site_dir, meta)

    detail: str | None = None
    if meta.dependencies:
        detail = _install_wheels(site_dir, meta.dependencies, fetch=fetch, find_links=find_links)
    if detail is None:
        done_marker.write_text("ok", encoding="utf-8")
    return DepsResult(site_dir=site_dir, detail=detail, fetched=fetch and not detail)


def _write_dist_info_shim(site_dir: Path, meta: ProjectMetadata) -> None:
    dist_info = site_dir / f"{meta.name}-{meta.version}.dist-info"
    dist_info.mkdir(parents=True, exist_ok=True)
    (dist_info / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: {meta.name}\nVersion: {meta.version}\n",
        encoding="utf-8",
    )
    (dist_info / "INSTALLER").write_text("tempest-shim\n", encoding="utf-8")
    (dist_info / "RECORD").write_text("", encoding="utf-8")


def _install_wheels(
    site_dir: Path,
    dependencies: tuple[str, ...],
    *,
    fetch: bool,
    find_links: Path | None,
) -> str | None:
    """Wheels only, never builds. Returns the remediation detail on failure, None on success."""
    uv = shutil.which("uv")
    if uv is None:
        return (
            "dependency wheels were not installed: the `uv` executable is not on PATH. "
            "Install uv (https://docs.astral.sh/uv/) and rerun."
        )
    cmd = [
        uv,
        "pip",
        "install",
        "--target",
        str(site_dir),
        "--only-binary",
        ":all:",
        "--python",
        sys.executable,
    ]
    if find_links is not None:
        cmd += ["--no-index", "--find-links", str(find_links)]
    elif not fetch:
        cmd.append("--offline")
    cmd += list(dependencies)
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if proc.returncode == 0:
        return None
    stderr_tail = proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else "no output"
    mode = "offline (wheels must already be in the uv cache)" if not fetch else "with fetching"
    return (
        f"dependency wheels could not be installed {mode}: {stderr_tail} — run once with "
        "--fetch-deps (or TEMPEST_FETCH_DEPS=1) to download them; afterwards every run is "
        "offline again"
    )


DEPS_LINK_NAME = ".tempest-deps"
DEPS_NOTE_NAME = ".tempest-deps-note"


def attach_deps(worktree: Path, cache: Path, *, fetch: bool) -> DepsResult:
    """Materialize and SELF-DESCRIBE: the worktree gets a `.tempest-deps` symlink to its
    site dir (workers and repros find it by convention, zero parameter threading) and a
    `.tempest-deps-note` carrying the remediation when materialization is incomplete —
    the import-failure UNPROVEN attaches it verbatim."""
    result = materialize_deps(worktree, cache, fetch=fetch)
    link = worktree / DEPS_LINK_NAME
    note = worktree / DEPS_NOTE_NAME
    if link.is_symlink() or link.exists():
        link.unlink()
    if result.site_dir is not None:
        link.symlink_to(result.site_dir, target_is_directory=True)
    if note.exists():
        note.unlink()
    if result.detail is not None:
        note.write_text(result.detail, encoding="utf-8")
    return result


def deps_note(root: Path) -> str | None:
    note = root / DEPS_NOTE_NAME
    if note.exists():
        return note.read_text(encoding="utf-8").strip() or None
    return None


def _git_describe_version(worktree: Path) -> str | None:
    try:
        proc = subprocess.run(
            ["git", "-C", str(worktree), "describe", "--tags", "--always"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip().lstrip("v") or None


def _write_version_file_shims(worktree: Path, version: str) -> None:
    """The humanize failure mode: `from ._version import __version__` where the module is
    GENERATED at build time and absent from the git tree. For every shallow package whose
    __init__ references `_version` and lacks the file, write a static shim carrying the
    vcs-derived version — inert for packages that never import it, and never touching a
    file that exists in the tree."""
    numeric: list[int] = []
    for part in version.split("+")[0].split("-")[0].split("."):
        if part.isdigit():
            numeric.append(int(part))
        else:
            break
    version_tuple = tuple(numeric) or (0, 0, 0)
    for parent in (worktree, worktree / "src"):
        if not parent.is_dir():
            continue
        for pkg in parent.iterdir():
            init = pkg / "__init__.py"
            shim = pkg / "_version.py"
            if not init.is_file() or shim.exists():
                continue
            try:
                init_text = init.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if "_version" not in init_text:
                continue
            shim.write_text(
                f'__version__ = version = "{version}"\n'
                f"__version_tuple__ = version_tuple = {version_tuple!r}\n",
                encoding="utf-8",
            )


def _setup_py_metadata(worktree: Path) -> ProjectMetadata | None:
    """AST-only read of setup(...) literal kwargs — dynamic values are skipped, and the
    file is NEVER executed (executing setup.py outside the sandbox would be arbitrary
    repo code, the exact thing L6 forbids)."""
    setup_py = worktree / "setup.py"
    if not setup_py.exists():
        return None
    try:
        tree = ast.parse(setup_py.read_text(encoding="utf-8"))
    except (SyntaxError, OSError, UnicodeDecodeError):
        return None
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        callee = (
            func.id
            if isinstance(func, ast.Name)
            else (func.attr if isinstance(func, ast.Attribute) else None)
        )
        if callee != "setup":
            continue
        constants = _module_constants(tree)
        kwargs = {k.arg: _fold(k.value, constants) for k in node.keywords if k.arg}
        name_v = kwargs.get("name")
        name = name_v if isinstance(name_v, str) else None
        version_v = kwargs.get("version")
        version = version_v if isinstance(version_v, str) else _SHIM_VERSION_FALLBACK
        req = kwargs.get("install_requires")
        dependencies = tuple(req) if isinstance(req, tuple) else ()
        if name is None and not dependencies:
            return None  # nothing statically usable — imports tell the truth
        return ProjectMetadata(name=name, version=version, dependencies=dependencies)
    return None


def _module_constants(tree: ast.Module) -> dict[str, "str | tuple[str, ...]"]:
    """Module-level `var = 'literal'` / `var = ['literal', ...]` assignments — the one
    indirection real setup.py files use (slugify) that is still purely static."""
    constants: dict[str, str | tuple[str, ...]] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        folded = _fold(node.value, {})
        if folded is not None:
            constants[target.id] = folded
    return constants


def _fold(
    node: ast.expr, constants: dict[str, "str | tuple[str, ...]"]
) -> "str | tuple[str, ...] | None":
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.List):
        items = [_fold(e, constants) for e in node.elts]
        if all(isinstance(i, str) for i in items):
            return tuple(items)  # type: ignore[arg-type]  # narrowed by the all() above
        return None
    if isinstance(node, ast.Name):
        return constants.get(node.id)
    return None
