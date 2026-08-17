# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Tempest desktop sidecar — ONEFILE.

Built by packages/desktop/build-server.sh; the single executable lands in packages/desktop/dist/ and
is staged as packages/desktop/src-tauri/binaries/tempest-server-<triple> (both gitignored).

ONEFILE, deliberately: the Tauri shell on main declares `externalBin: ["binaries/
tempest-server"]` and spawns `.sidecar("tempest-server")` — Tauri resolves that to a single
executable FILE named tempest-server-<target-triple>, so a ONEDIR bundle directory cannot
satisfy the contract without touching src-tauri config. Cost: onefile self-extracts to a temp
dir at each launch (~1s extra startup for this ~45 MB payload); measured startup-to-healthy
stays low single-digit seconds.

Why the explicit `datas`: the engine copies three source files into every run's scratch dir
at runtime via `module.__file__` (tempest.execute.runner._prepare_scratch). PyInstaller puts
pure modules in the PYZ archive but points their `__file__` at the extraction dir
(sys._MEIPASS/tempest/...), so shipping the real .py files as data at exactly those relative
paths keeps `shutil.copyfile(module.__file__, ...)` working when frozen.
"""

import platform
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

REPO = Path(SPECPATH).resolve().parents[1]  # noqa: F821 — SPECPATH is injected by PyInstaller
ENGINE_SRC = REPO / "packages" / "engine" / "src" / "tempest"

ARCH = {"arm64": "aarch64", "x86_64": "x86_64"}[platform.machine()]
NAME = f"tempest-server-{ARCH}-apple-darwin"

datas = [
    (str(ENGINE_SRC / "execute" / "_worker.py"), "tempest/execute"),
    (str(ENGINE_SRC / "compare" / "canonical.py"), "tempest/compare"),
    (str(ENGINE_SRC / "determinism" / "_shims.py"), "tempest/determinism"),
    # ADR-0028: the JS execution pair are DATA (not Python modules) — without them the
    # frozen app would fail every TS prove while parity (a pure-Python fixture) stays
    # green. ts_dual resolves them via Path(__file__).with_name(...).
    (str(ENGINE_SRC / "execute" / "ts_worker.mjs"), "tempest/execute"),
    (str(ENGINE_SRC / "execute" / "ts_shims.mjs"), "tempest/execute"),
]

hiddenimports = (
    # the API imports tempest lazily/partially; ship the whole engine so local-prove and
    # future routes resolve without a spec rebuild
    collect_submodules("tempest")
    + collect_submodules("tempest_api")
    # uvicorn resolves loops/protocols/lifespan classes from strings at runtime
    + collect_submodules("uvicorn")
    + [
        "aiosqlite",  # sqlalchemy loads the sqlite+aiosqlite dialect from a registry string
        "sqlalchemy.dialects.sqlite.aiosqlite",
        "greenlet",  # sqlalchemy's async bridge imports it dynamically
        "python_multipart",  # fastapi imports it lazily for multipart bundle uploads
    ]
)

a = Analysis(
    [str(REPO / "packages" / "desktop" / "server-entry.py")],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
