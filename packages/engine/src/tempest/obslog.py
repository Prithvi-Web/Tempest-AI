"""Structured JSON-lines observability log for the engine and sidecar.

One JSON object per line in `log_dir()/tempest.jsonl`, size-rotated with numbered backups so
disk use is bounded. The emit path must never raise: a full disk or revoked directory breaks
the log, never the prove that was writing to it. Stdlib only — the engine takes no logging
dependency.
"""

import contextlib
import json
import logging
import logging.handlers
import os
import threading
from datetime import UTC, datetime
from pathlib import Path

_LOG_FILENAME = "tempest.jsonl"
_LOGGER_PREFIX = "tempest.obslog."
_MAX_BYTES = 5 * 1024 * 1024
_BACKUP_COUNT = 5
_CORE_FIELDS = ("ts", "level", "component", "message")

# One handler per log file, shared by every component logger: two handles rotating the same
# file would race each other's renames and corrupt the backup chain.
_handlers: dict[str, "_SafeRotatingFileHandler"] = {}
_lock = threading.Lock()


def log_dir() -> Path:
    """`$TEMPEST_DATA_DIR/logs` when set, else `~/.tempest/logs` (resolved per call, so tests
    and packaged installs can repoint the data dir without restarting)."""
    data_dir = os.environ.get("TEMPEST_DATA_DIR")
    if data_dir:
        return Path(data_dir) / "logs"
    return Path.home() / ".tempest" / "logs"


class _JsonFormatter(logging.Formatter):
    """One JSON object per record; extras ride in `record.tempest_extra` and merge after the
    core fields, which stay authoritative (a forged `message` extra cannot rewrite history)."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "component": record.name.removeprefix(_LOGGER_PREFIX),
            "message": record.getMessage(),
        }
        extra: object = getattr(record, "tempest_extra", None)
        if isinstance(extra, dict):
            for key, value in extra.items():
                if str(key) not in _CORE_FIELDS:
                    payload[str(key)] = value
        # default=str: an unserializable extra degrades to its repr, never to a lost record.
        return json.dumps(payload, ensure_ascii=False, default=str)


class _SafeRotatingFileHandler(logging.handlers.RotatingFileHandler):
    """RotatingFileHandler that swallows every emit-path failure (full disk, revoked
    directory, closed stream). Losing a log line is acceptable; failing a prove is not."""

    def emit(self, record: logging.LogRecord) -> None:
        # Whatever broke — full disk, closed stream, rollover rename — the record is dropped.
        with contextlib.suppress(Exception):
            super().emit(record)

    def handleError(self, record: logging.LogRecord) -> None:
        """Stdlib default prints a traceback to stderr; the engine's stderr is product output."""


def get_logger(component: str) -> logging.Logger:
    """Logger for one engine component, writing JSON lines to `log_dir()/tempest.jsonl`.

    Idempotent: repeat calls return the same logger with exactly one handler. If
    TEMPEST_DATA_DIR changed since the last call, the stale handler is swapped for one
    pointing at the current location.
    """
    logger = logging.getLogger(_LOGGER_PREFIX + component)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    path = os.path.abspath(log_dir() / _LOG_FILENAME)
    with _lock:
        handler = _handlers.get(path)
        if handler is None:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            handler = _SafeRotatingFileHandler(
                path,
                maxBytes=_MAX_BYTES,
                backupCount=_BACKUP_COUNT,
                encoding="utf-8",
                delay=True,
            )
            handler.setFormatter(_JsonFormatter())
            _handlers[path] = handler
        for existing in list(logger.handlers):
            if isinstance(existing, _SafeRotatingFileHandler) and existing is not handler:
                logger.removeHandler(existing)
        if handler not in logger.handlers:
            logger.addHandler(handler)
    return logger


def read_records(limit: int = 200, level: str | None = None) -> list[dict[str, object]]:
    """Parsed records across current + rotated files, oldest first (newest-last).

    Corrupt or non-object lines are skipped — a torn write during rotation must not hide the
    readable history around it. `level` is a minimum (case-insensitive), matching the viewer's
    "WARNING and up" mental model.
    """
    if limit <= 0:
        return []
    minimum = _minimum_level_number(level)
    base = log_dir() / _LOG_FILENAME
    # Backup .1 is the newest rotation, .N the oldest — walk .N → .1 → current for
    # oldest-first order.
    files = [base.with_name(f"{_LOG_FILENAME}.{i}") for i in range(_BACKUP_COUNT, 0, -1)]
    files.append(base)
    records: list[dict[str, object]] = []
    for file in files:
        try:
            text = file.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            try:
                parsed: object = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(parsed, dict):
                continue
            record: dict[str, object] = {str(key): value for key, value in parsed.items()}
            if minimum and _record_level_number(record) < minimum:
                continue
            records.append(record)
    return records[-limit:]


def _minimum_level_number(level: str | None) -> int:
    if level is None:
        return 0
    mapping = logging.getLevelNamesMapping()
    number = mapping.get(level.upper())
    if number is None:
        valid = ", ".join(sorted(name for name in mapping if name != "NOTSET"))
        raise ValueError(f"unknown level {level!r} — valid levels: {valid}")
    return number


def _record_level_number(record: dict[str, object]) -> int:
    name = record.get("level")
    if not isinstance(name, str):
        return -1
    return logging.getLevelNamesMapping().get(name.upper(), -1)
