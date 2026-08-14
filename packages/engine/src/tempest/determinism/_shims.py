"""The record/replay shim layer. STDLIB-ONLY — copied into the sandbox scratch beside the worker.

Concept (master spec §4.4): a cassette is an ordered ledger of every nondeterministic interaction.
Record mode taps the live surface and logs; replay mode serves the logged values with the real
surface gone. Keying is (surface, normalized_call, per-key ordinal); the global ledger order is
what effect-sequence comparison consumes. A cassette miss means head did something base never
did — that is evidence (DIVERGENT), and an un-interceptable surface refuses loudly (UNPROVEN),
never silently passes (Law L2/L3).
"""

import base64
import builtins
import datetime as _dt_module
import io
import os
import os.path as _os_path
import random as _random_module
import socket as _socket_module
import subprocess as _subprocess_module
import threading
import time as _time_module
from dataclasses import dataclass, field
from typing import Any

_MISS = object()


class CassetteMiss(Exception):
    """Head requested an interaction base never made — a first-class divergence, not an error."""


class UninterceptableEffect(Exception):
    """The target reached a surface the determinism layer cannot intercept — UNPROVEN, loudly."""


@dataclass
class Entry:
    surface: str
    call: str
    ordinal: int
    payload: Any


@dataclass
class Session:
    mode: str = "record"  # "record" | "replay"
    cassette: list[dict[str, Any]] | None = None
    ledger: list[Entry] = field(default_factory=list)
    misses: list[str] = field(default_factory=list)
    _queues: dict[tuple[str, str], list[Any]] = field(default_factory=dict)
    _cursors: dict[tuple[str, str], int] = field(default_factory=dict)
    _env_overlay: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.mode == "replay" and self.cassette:
            for raw in self.cassette:
                key = (raw["surface"], raw["call"])
                self._queues.setdefault(key, []).append(_decode(raw["payload"]))

    def interact(self, surface: str, call: str, live: Any) -> Any:
        if _internal():
            return live()
        key = (surface, call)
        if self.mode == "record":
            value = live()
            ordinal = self._cursors.get(key, 0)
            self._cursors[key] = ordinal + 1
            self.ledger.append(Entry(surface, call, ordinal, value))
            return value
        cursor = self._cursors.get(key, 0)
        queue = self._queues.get(key, [])
        if cursor >= len(queue):
            self.misses.append(f"{surface} {call} (ordinal {cursor})")
            raise CassetteMiss(
                f"{surface} {call}: head requested ordinal {cursor} but base recorded "
                f"only {len(queue)} interaction(s)"
            )
        self._cursors[key] = cursor + 1
        value = queue[cursor]
        self.ledger.append(Entry(surface, call, cursor, value))
        return value

    def open_entry(self, surface: str, call: str) -> Entry:
        """Append a ledger entry now (order = open order); payload is filled at close."""
        key = (surface, call)
        ordinal = self._cursors.get(key, 0)
        self._cursors[key] = ordinal + 1
        entry = Entry(surface, call, ordinal, None)
        self.ledger.append(entry)
        return entry

    def replay_for(self, surface: str, call: str) -> Any:
        key = (surface, call)
        cursor = self._cursors.get(key, 0)
        queue = self._queues.get(key, [])
        if cursor >= len(queue):
            self.misses.append(f"{surface} {call} (ordinal {cursor})")
            raise CassetteMiss(f"{surface} {call}: no recorded interaction at ordinal {cursor}")
        return queue[cursor]

    def cassette_data(self) -> list[dict[str, Any]]:
        return [
            {
                "surface": e.surface,
                "call": e.call,
                "ordinal": e.ordinal,
                "payload": _encode(e.payload),
            }
            for e in self.ledger
        ]


def _encode(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"__b64": base64.b64encode(value).decode("ascii")}
    if isinstance(value, list):
        return [_encode(v) for v in value]
    if isinstance(value, dict):
        return {k: _encode(v) for k, v in value.items()}
    return value


def _decode(value: Any) -> Any:
    if isinstance(value, dict) and set(value) == {"__b64"}:
        return base64.b64decode(value["__b64"])
    if isinstance(value, list):
        return [_decode(v) for v in value]
    if isinstance(value, dict):
        return {k: _decode(v) for k, v in value.items()}
    return value


_active: Session | None = None
_saved: dict[str, Any] = {}
_allow_internal = threading.local()


def _session() -> Session:
    assert _active is not None
    return _active


def _internal() -> bool:
    """True while an intercepting shim's own live() machinery is running — lower-level
    surfaces pass through unrecorded, because they are invisible at replay too."""
    return bool(getattr(_allow_internal, "value", False))


def set_session(session: Session) -> None:
    """Swap the active session without repatching — patches must be installed BEFORE the target
    module is imported so that `from x import y` bindings capture the shims, and stay installed
    for the whole batch while each input gets its own fresh session."""
    global _active
    assert _saved, "set_session requires install() to have run"
    _active = session


# --------------------------------------------------------------------------- clock


def _shim_time() -> float:
    return float(_session().interact("CLOCK", "time.time", _saved["time.time"]))


def _shim_time_ns() -> int:
    return int(_session().interact("CLOCK", "time.time_ns", _saved["time.time_ns"]))


def _shim_monotonic() -> float:
    return float(_session().interact("CLOCK", "time.monotonic", _saved["time.monotonic"]))


def _shim_monotonic_ns() -> int:
    return int(_session().interact("CLOCK", "time.monotonic_ns", _saved["time.monotonic_ns"]))


class _ShimDateTime(_dt_module.datetime):
    @classmethod
    def now(cls, tz: Any = None) -> "_ShimDateTime":
        iso = _session().interact(
            "CLOCK",
            f"datetime.now(tz={tz is not None})",
            lambda: _saved["datetime"].now(tz).isoformat(),
        )
        return cls.fromisoformat(str(iso))

    @classmethod
    def utcnow(cls) -> "_ShimDateTime":
        iso = _session().interact(
            "CLOCK", "datetime.utcnow", lambda: _saved["datetime"].utcnow().isoformat()
        )
        return cls.fromisoformat(str(iso))

    @classmethod
    def today(cls) -> "_ShimDateTime":
        iso = _session().interact(
            "CLOCK", "datetime.today", lambda: _saved["datetime"].today().isoformat()
        )
        return cls.fromisoformat(str(iso))


# --------------------------------------------------------------------------- randomness


def _shim_urandom(n: int) -> bytes:
    value = _session().interact("RANDOM", f"os.urandom({n})", lambda: _saved["os.urandom"](n))
    return bytes(value)


def _shim_random() -> float:
    return float(_session().interact("RANDOM", "random.random", _saved["random.random"]))


def _shim_randint(a: int, b: int) -> int:
    return int(
        _session().interact(
            "RANDOM", f"random.randint({a},{b})", lambda: _saved["random.randint"](a, b)
        )
    )


def _shim_randrange(*args: int) -> int:
    call = f"random.randrange{args!r}"
    return int(_session().interact("RANDOM", call, lambda: _saved["random.randrange"](*args)))


def _shim_uniform(a: float, b: float) -> float:
    call = f"random.uniform({a!r},{b!r})"
    return float(_session().interact("RANDOM", call, lambda: _saved["random.uniform"](a, b)))


def _shim_getrandbits(k: int) -> int:
    return int(
        _session().interact(
            "RANDOM", f"random.getrandbits({k})", lambda: _saved["random.getrandbits"](k)
        )
    )


def _shim_choice(seq: Any) -> Any:
    index = _session().interact(
        "RANDOM",
        f"random.choice(len={len(seq)})",
        lambda: seq.index(_saved["random.choice"](seq)),
    )
    return seq[int(index)]


def _shim_shuffle(seq: Any) -> None:
    def live() -> list[int]:
        order = list(range(len(seq)))
        _saved["random.shuffle"](order)
        return order

    order = _session().interact("RANDOM", f"random.shuffle(len={len(seq)})", live)
    seq[:] = [seq[i] for i in order]


# --------------------------------------------------------------------------- environment


class _EnvironProxy:
    def __init__(self, real: Any) -> None:
        self._real = real

    def get(self, key: str, default: Any = None) -> Any:
        if _internal():
            return self._real.get(key, default)
        session = _session()
        if key in session._env_overlay:
            return session._env_overlay[key]
        value = session.interact("ENV", f"environ.get({key})", lambda: self._real.get(key))
        return default if value is None else value

    def __getitem__(self, key: str) -> str:
        value = self.get(key, _MISS)
        if value is _MISS or value is None:
            raise KeyError(key)
        return str(value)

    def __contains__(self, key: object) -> bool:
        return self.get(str(key), None) is not None

    def __setitem__(self, key: str, value: str) -> None:
        session = _session()
        session.open_entry("ENV", f"environ.set({key})").payload = value
        session._env_overlay[key] = value
        if session.mode == "record":
            self._real[key] = value

    def __delitem__(self, key: str) -> None:
        session = _session()
        session.open_entry("ENV", f"environ.del({key})").payload = None
        session._env_overlay.pop(key, None)
        if session.mode == "record":
            del self._real[key]

    def __iter__(self) -> Any:
        return iter(self._real)

    def __len__(self) -> int:
        return len(self._real)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real, name)


# --------------------------------------------------------------------------- filesystem

_READ_MODES = {"r", "rb", "rt"}
_WRITE_MODES = {"w", "wb", "wt", "a", "ab", "x", "xb"}


def _normalize_path(path: Any) -> str:
    text = os.fspath(path)
    if isinstance(text, bytes):
        text = text.decode("utf-8", "replace")
    try:
        cwd = _saved["os.getcwd"]()
        if text.startswith(cwd):
            return "./" + text[len(cwd) :].lstrip("/")
    except OSError:
        pass
    return text


class _RecordingWriter:
    """Wraps a real (record) or fake (replay) writable file; captures content into the entry."""

    def __init__(self, inner: Any, entry: Entry, binary: bool) -> None:
        self._inner = inner
        self._entry = entry
        self._chunks: list[Any] = []
        self._binary = binary

    def write(self, data: Any) -> int:
        self._chunks.append(data)
        return int(self._inner.write(data))

    def close(self) -> None:
        joined = (b"" if self._binary else "").join(self._chunks)
        self._entry.payload = joined
        self._inner.close()

    def __enter__(self) -> "_RecordingWriter":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def _shim_open(file: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
    if _internal():
        return _saved["open"](file, mode, *args, **kwargs)
    session = _session()
    if isinstance(file, int):  # fd-based opens are internal plumbing, pass through
        return _saved["open"](file, mode, *args, **kwargs)
    path = _normalize_path(file)
    binary = "b" in mode
    bare = mode.replace("+", "")
    if bare in _READ_MODES or mode == "r":
        call = f"open:{mode}:{path}"
        if session.mode == "record":

            def live() -> Any:
                with _saved["open"](file, mode, *args, **kwargs) as fh:
                    return fh.read()

            content = session.interact("FS", call, live)
        else:
            content = session.interact("FS", call, lambda: None)
        return io.BytesIO(content) if binary else io.StringIO(str(content))
    if bare in _WRITE_MODES:
        call = f"open:write:{mode}:{path}"
        entry = session.open_entry("FS", call)
        if session.mode == "record":
            inner = _saved["open"](file, mode, *args, **kwargs)
        else:
            inner = io.BytesIO() if binary else io.StringIO()
        return _RecordingWriter(inner, entry, binary)
    raise UninterceptableEffect(
        f"open(mode={mode!r}) on {path!r} — read/write '+' modes are not intercepted in v1; "
        "this target is UNPROVEN, not blessed"
    )


def _shim_listdir(path: Any = ".") -> list[str]:
    call = f"os.listdir({_normalize_path(path)})"
    value = _session().interact("FS", call, lambda: _saved["os.listdir"](path))
    return list(value)


def _shim_exists(path: Any) -> bool:
    call = f"os.path.exists({_normalize_path(path)})"
    return bool(_session().interact("FS", call, lambda: _saved["os.path.exists"](path)))


def _shim_getcwd() -> str:
    return str(_session().interact("FS", "os.getcwd", _saved["os.getcwd"]))


# --------------------------------------------------------------------------- process


def _completed_to_payload(result: Any) -> dict[str, Any]:
    return {
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def _shim_subprocess_run(argv: Any, *args: Any, **kwargs: Any) -> Any:
    session = _session()
    call = f"subprocess.run({argv!r})"

    def live() -> dict[str, Any]:
        _allow_internal.value = True
        try:
            return _completed_to_payload(_saved["subprocess.run"](argv, *args, **kwargs))
        finally:
            _allow_internal.value = False

    payload = session.interact("PROC", call, live)
    return _subprocess_module.CompletedProcess(
        args=argv,
        returncode=int(payload["returncode"]),
        stdout=payload["stdout"],
        stderr=payload["stderr"],
    )


def _shim_os_system(command: str) -> int:
    return int(
        _session().interact("PROC", f"os.system({command!r})", lambda: _saved["os.system"](command))
    )


class _GuardedPopen:
    def __new__(cls, *args: Any, **kwargs: Any) -> Any:
        if getattr(_allow_internal, "value", False):
            # Internal use by the shimmed subprocess.run: hand back the REAL Popen instance
            # (context-manager protocol and all).
            return _saved["subprocess.Popen"](*args, **kwargs)
        raise UninterceptableEffect(
            "direct subprocess.Popen use — v1 intercepts subprocess.run/os.system only; "
            "this target is UNPROVEN, not blessed"
        )


# --------------------------------------------------------------------------- network


class _GuardedSocket:
    def __new__(cls, *args: Any, **kwargs: Any) -> Any:
        if getattr(_allow_internal, "value", False):
            # Internal use (shimmed urlopen, loopback server): hand back a REAL socket.
            return _saved["socket.socket"](*args, **kwargs)
        raise UninterceptableEffect(
            "raw socket.socket — it opens a channel to an unrecorded host; v1 intercepts "
            "urllib.request.urlopen. This target is UNPROVEN, not blessed"
        )


def allow_internal_in_this_thread() -> None:
    """Mark the CURRENT thread as shim-internal (loopback server machinery)."""
    _allow_internal.value = True


def _shim_urlopen(url: Any, *args: Any, **kwargs: Any) -> Any:
    import email.message
    import urllib.response

    session = _session()
    url_text = url if isinstance(url, str) else getattr(url, "full_url", repr(url))
    call = f"urlopen({url_text})"

    import urllib.error

    def live() -> dict[str, Any]:
        _allow_internal.value = True
        try:
            with _saved["urlopen"](url, *args, **kwargs) as resp:
                body = resp.read()
                return {
                    "ok": True,
                    "status": resp.status,
                    "headers": list(resp.headers.items()),
                    "body": body,
                    "url": resp.url,
                }
        except urllib.error.HTTPError as exc:
            return {
                "ok": False,
                "status": exc.code,
                "reason": str(exc.reason),
                "headers": list(exc.headers.items()) if exc.headers else [],
                "body": exc.read(),
                "url": url_text,
            }
        finally:
            _allow_internal.value = False

    payload = session.interact("NET", call, live)
    headers = email.message.Message()
    for name, value in payload["headers"]:
        headers[name] = value
    fp = io.BytesIO(payload["body"])
    if not payload.get("ok", True):
        raise urllib.error.HTTPError(
            str(payload["url"]), int(payload["status"]), str(payload["reason"]), headers, fp
        )
    response = urllib.response.addinfourl(fp, headers, str(payload["url"]), int(payload["status"]))
    return response


# --------------------------------------------------------------------------- install


def install(session: Session) -> None:
    global _active
    if _active is not None:
        uninstall()
    _active = session
    import urllib.request

    _saved.update(
        {
            "time.time": _time_module.time,
            "time.time_ns": _time_module.time_ns,
            "time.monotonic": _time_module.monotonic,
            "time.monotonic_ns": _time_module.monotonic_ns,
            "datetime": _dt_module.datetime,
            "os.urandom": os.urandom,
            "random.random": _random_module.random,
            "random.randint": _random_module.randint,
            "random.randrange": _random_module.randrange,
            "random.uniform": _random_module.uniform,
            "random.getrandbits": _random_module.getrandbits,
            "random.choice": _random_module.choice,
            "random.shuffle": _random_module.shuffle,
            "os.environ": os.environ,
            "open": builtins.open,
            "io.open": io.open,
            "os.listdir": os.listdir,
            "os.path.exists": _os_path.exists,
            "os.getcwd": os.getcwd,
            "subprocess.run": _subprocess_module.run,
            "subprocess.Popen": _subprocess_module.Popen,
            "os.system": os.system,
            "socket.socket": _socket_module.socket,
            "urlopen": urllib.request.urlopen,
        }
    )
    _time_module.time = _shim_time
    _time_module.time_ns = _shim_time_ns
    _time_module.monotonic = _shim_monotonic
    _time_module.monotonic_ns = _shim_monotonic_ns
    _dt_module.datetime = _ShimDateTime  # type: ignore[misc]  # module attr swap is the mechanism
    os.urandom = _shim_urandom
    _random_module.random = _shim_random
    _random_module.randint = _shim_randint
    _random_module.randrange = _shim_randrange
    _random_module.uniform = _shim_uniform
    _random_module.getrandbits = _shim_getrandbits
    _random_module.choice = _shim_choice
    _random_module.shuffle = _shim_shuffle
    os.environ = _EnvironProxy(_saved["os.environ"])  # noqa: B003  # proxy swap, not a clear
    builtins.open = _shim_open  # type: ignore[assignment]  # module attr swap
    io.open = _shim_open  # type: ignore[assignment]  # module attr swap
    os.listdir = _shim_listdir
    _os_path.exists = _shim_exists
    os.getcwd = _shim_getcwd
    _subprocess_module.run = _shim_subprocess_run  # type: ignore[assignment]  # module attr swap
    _subprocess_module.Popen = _GuardedPopen  # type: ignore[misc,assignment]  # module attr swap
    os.system = _shim_os_system
    _socket_module.socket = _GuardedSocket  # type: ignore[misc,assignment]  # module attr swap
    urllib.request.urlopen = _shim_urlopen


def uninstall() -> None:
    global _active
    if _active is None:
        return
    import urllib.request

    _time_module.time = _saved["time.time"]
    _time_module.time_ns = _saved["time.time_ns"]
    _time_module.monotonic = _saved["time.monotonic"]
    _time_module.monotonic_ns = _saved["time.monotonic_ns"]
    _dt_module.datetime = _saved["datetime"]  # type: ignore[misc]  # module attr restore
    os.urandom = _saved["os.urandom"]
    _random_module.random = _saved["random.random"]
    _random_module.randint = _saved["random.randint"]
    _random_module.randrange = _saved["random.randrange"]
    _random_module.uniform = _saved["random.uniform"]
    _random_module.getrandbits = _saved["random.getrandbits"]
    _random_module.choice = _saved["random.choice"]
    _random_module.shuffle = _saved["random.shuffle"]
    os.environ = _saved["os.environ"]  # noqa: B003  # restoring the real mapping
    builtins.open = _saved["open"]
    io.open = _saved["io.open"]  # type: ignore[assignment]  # module attr restore
    os.listdir = _saved["os.listdir"]
    _os_path.exists = _saved["os.path.exists"]
    os.getcwd = _saved["os.getcwd"]
    _subprocess_module.run = _saved["subprocess.run"]
    _subprocess_module.Popen = _saved["subprocess.Popen"]  # type: ignore[misc]  # module attr restore
    os.system = _saved["os.system"]
    _socket_module.socket = _saved["socket.socket"]  # type: ignore[misc]  # module attr restore
    urllib.request.urlopen = _saved["urlopen"]
    _active = None
    _saved.clear()
