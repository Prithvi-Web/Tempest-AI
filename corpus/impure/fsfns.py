"""10 filesystem functions — real-world idioms over open/os (the v1 intercepted FS surface).

Paths are cwd-relative; the corpus harness copies this directory into a temp workdir with the
`data/` fixtures present."""

import hashlib
import json
import os


def read_config_key(path: str, key: str) -> str:
    """Pattern: JSON config loader (twelve-factor app settings file)."""
    with open(path) as fh:
        return str(json.load(fh)[key])


def count_lines(path: str) -> int:
    """Pattern: wc -l style log inspection."""
    with open(path) as fh:
        return len(fh.readlines())


def read_optional_dotfile(path: str, default: str) -> str:
    """Pattern: optional user dotfile with a fallback (git config style)."""
    if os.path.exists(path):
        with open(path) as fh:
            return fh.read().strip()
    return default


def extension_histogram(directory: str) -> dict[str, int]:
    """Pattern: build-tool source scanner grouping files by suffix."""
    histogram: dict[str, int] = {}
    for name in sorted(os.listdir(directory)):
        ext = name.rsplit(".", 1)[-1] if "." in name else ""
        histogram[ext] = histogram.get(ext, 0) + 1
    return histogram


def magic_bytes(path: str) -> str:
    """Pattern: file-type sniffing via magic numbers."""
    with open(path, "rb") as fh:
        return fh.read(8).hex()


def write_report(path: str, text: str) -> int:
    """Pattern: report emitter returning bytes written."""
    with open(path, "w") as fh:
        fh.write(text)
    return len(text)


def append_audit_line(path: str, line: str) -> None:
    """Pattern: append-only audit log."""
    with open(path, "a") as fh:
        fh.write(line + "\n")


def copy_text_file(src: str, dst: str) -> int:
    """Pattern: config templating copy (read whole, write whole)."""
    with open(src) as fh:
        content = fh.read()
    with open(dst, "w") as fh:
        fh.write(content)
    return len(content)


def env_or_file_setting(env_name: str, path: str) -> str:
    """Pattern: env-var override with file fallback (docker-secrets style)."""
    value = os.environ.get(env_name)
    if value is not None:
        return value
    with open(path) as fh:
        return fh.read().strip()


def checksum_file(path: str) -> str:
    """Pattern: lockfile/artifact integrity hash."""
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()
