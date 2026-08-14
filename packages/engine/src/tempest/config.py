"""`tempest.toml` — optional per-repo configuration (budgets, tolerances, ignore globs).

Precedence is explicit and boring: CLI flag > tempest.toml > built-in default. An absent file
means pure defaults. Unknown keys are a hard error that names every offender and the full valid
vocabulary — error messages are the product; a silently ignored typo would bless the wrong run.
"""

import tomllib
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

CONFIG_FILENAME = "tempest.toml"
DEFAULT_MAX_INPUTS = 300

_VALID_KEYS: dict[str, tuple[str, ...]] = {
    "budgets": ("max_inputs", "max_wall_seconds"),
    "compare": ("float_rel_tol",),
    "ignore": ("globs",),
}


class TempestConfigError(Exception):
    """tempest.toml exists but is unusable; the message states exactly what to fix."""


def _vocabulary() -> str:
    return " · ".join(f"[{table}] {', '.join(keys)}" for table, keys in _VALID_KEYS.items())


@dataclass(frozen=True)
class TempestConfig:
    """Parsed tempest.toml. `None` means "not set", so CLI flags can take precedence."""

    max_inputs: int | None = None
    max_wall_seconds: float | None = None
    float_rel_tol: float | None = None
    ignore_globs: tuple[str, ...] = ()

    @classmethod
    def load(cls, repo: Path) -> "TempestConfig":
        """Read `<repo>/tempest.toml`; absent file → all defaults."""
        path = repo / CONFIG_FILENAME
        if not path.exists():
            return cls()
        try:
            raw: dict[str, Any] = tomllib.loads(path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as exc:
            raise TempestConfigError(f"{path}: not valid TOML — {exc}") from exc
        except OSError as exc:
            raise TempestConfigError(f"{path}: could not be read — {exc}") from exc
        _reject_unknown_keys(path, raw)
        budgets = raw.get("budgets", {})
        compare = raw.get("compare", {})
        ignore = raw.get("ignore", {})
        return cls(
            max_inputs=_int_at_least(path, "[budgets].max_inputs", budgets.get("max_inputs"), 1),
            max_wall_seconds=_positive_number(
                path, "[budgets].max_wall_seconds", budgets.get("max_wall_seconds")
            ),
            float_rel_tol=_non_negative_number(
                path, "[compare].float_rel_tol", compare.get("float_rel_tol")
            ),
            ignore_globs=_glob_tuple(path, "[ignore].globs", ignore.get("globs")),
        )

    def effective_max_inputs(self, cli_value: int | None) -> int:
        """CLI flag > tempest.toml > built-in default (300)."""
        if cli_value is not None:
            return cli_value
        if self.max_inputs is not None:
            return self.max_inputs
        return DEFAULT_MAX_INPUTS

    def effective_float_rel_tol(self, cli_value: float | None) -> float | None:
        """CLI flag > tempest.toml > None (exact comparison — tolerance is always opt-in)."""
        return cli_value if cli_value is not None else self.float_rel_tol


def is_ignored(rel_path: str, globs: tuple[str, ...]) -> bool:
    """True when a repo-relative path matches any `[ignore].globs` pattern.

    Case-sensitive fnmatch semantics on every platform; `*` crosses `/`, so `generated/*`
    covers the whole subtree and `*_pb2.py` matches at any depth.
    """
    return any(fnmatchcase(rel_path, glob) for glob in globs)


def _reject_unknown_keys(path: Path, raw: dict[str, Any]) -> None:
    unknown: list[str] = []
    for table, value in raw.items():
        if table not in _VALID_KEYS:
            unknown.append(f"[{table}]")
            continue
        if not isinstance(value, dict):
            raise TempestConfigError(
                f"{path}: [{table}] must be a TOML table (a `[{table}]` section header, "
                f"not `{table} = ...`)"
            )
        unknown.extend(f"[{table}].{key}" for key in value if key not in _VALID_KEYS[table])
    if unknown:
        raise TempestConfigError(
            f"{path}: unknown key(s): {', '.join(sorted(unknown))}. Valid keys: {_vocabulary()}."
        )


def _int_at_least(path: Path, name: str, value: object, minimum: int) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise TempestConfigError(f"{path}: {name} must be an integer, got {value!r}")
    if value < minimum:
        raise TempestConfigError(f"{path}: {name} must be >= {minimum}, got {value}")
    return value


def _positive_number(path: Path, name: str, value: object) -> float | None:
    result = _number(path, name, value)
    if result is not None and result <= 0:
        raise TempestConfigError(f"{path}: {name} must be > 0, got {result}")
    return result


def _non_negative_number(path: Path, name: str, value: object) -> float | None:
    result = _number(path, name, value)
    if result is not None and result < 0:
        raise TempestConfigError(f"{path}: {name} must be >= 0, got {result}")
    return result


def _number(path: Path, name: str, value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TempestConfigError(f"{path}: {name} must be a number, got {value!r}")
    return float(value)


def _glob_tuple(path: Path, name: str, value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise TempestConfigError(
            f"{path}: {name} must be an array of glob strings, "
            f'e.g. globs = ["generated/*", "*_pb2.py"] — got {value!r}'
        )
    globs: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item:
            raise TempestConfigError(
                f"{path}: {name} entries must be non-empty strings, got {item!r}"
            )
        globs.append(item)
    return tuple(globs)
