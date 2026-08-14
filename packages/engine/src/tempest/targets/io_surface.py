"""The IO allowlist (master spec stage 1): a symbol whose body reaches any of these surfaces is
IMPURE_RECORDABLE — it needs the determinism layer. Everything else is PURE_CANDIDATE by the
spec's definition; the record pass and the net/fs guards catch any classification lie at runtime.
"""

IO_MODULES: frozenset[str] = frozenset(
    {
        "os",
        "io",
        "sys",
        "time",
        "datetime",
        "random",
        "secrets",
        "uuid",
        "socket",
        "ssl",
        "select",
        "selectors",
        "http",
        "urllib",
        "requests",
        "httpx",
        "aiohttp",
        "subprocess",
        "shutil",
        "tempfile",
        "pathlib",
        "glob",
        "sqlite3",
        "threading",
        "multiprocessing",
        "asyncio",
        "logging",
        "signal",
    }
)

IO_BUILTINS: frozenset[str] = frozenset({"open", "input", "exec", "eval", "__import__"})
