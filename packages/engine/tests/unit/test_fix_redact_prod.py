"""Privacy-review fixes, production surfaces: the crash writer must run the SAME redaction
context the gate proves (repo names via TEMPEST_REDACT_REPO_NAMES — finding 3), a multi-line
PEM inside an exception message must never reach the crash record (finding 1), and doctor's
OUTBOUND payload reduces data_dir to `[PATH]/<basename>` while the local report keeps the
full path (finding 6)."""

import json
from pathlib import Path

import pytest

from tempest.cli.doctor import collect_payload, outbound_payload
from tempest.crashlog import capture_crash

PEM = (
    "-----BEGIN RSA PRIVATE KEY-----\n"
    "PLANTEDCRASHKEYMATERIALPLANTEDCRASHKEYMATERIAL\n"
    "-----END RSA PRIVATE KEY-----"
)


def test_crash_record_uses_the_env_sourced_repo_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TEMPEST_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("TEMPEST_REDACT_REPO_NAMES", "planted-crash-repo")
    try:
        raise RuntimeError("clone of planted-crash-repo failed")
    except RuntimeError as exc:
        path = capture_crash(exc)
    assert path is not None
    record = json.loads(path.read_text())
    assert "planted-crash-repo" not in record["traceback"], (
        "the production crash context must wire the env-sourced repo names (finding 3)"
    )
    assert "[REPO]" in record["traceback"]


def test_multiline_pem_in_exception_message_never_reaches_the_crash_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TEMPEST_DATA_DIR", str(tmp_path / "data"))
    try:
        raise ValueError(f"could not load key:\n{PEM}")
    except ValueError as exc:
        path = capture_crash(exc)
    assert path is not None
    text = path.read_text()
    assert "PLANTEDCRASHKEYMATERIAL" not in text, "multi-line PEM survived per-line scrubbing"
    assert "BEGIN RSA PRIVATE KEY" not in text
    assert "could not load key:" in text, "the exception message frame survives"


def test_outbound_payload_reduces_data_dir_to_basename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TEMPEST_DATA_DIR", str(tmp_path / "tempest-data"))
    monkeypatch.setenv("TEMPEST_NO_POWER_PAUSE", "1")
    assert outbound_payload()["data_dir"] == "[PATH]/tempest-data", (
        "a data dir outside $HOME must not cross the outbound boundary verbatim (finding 6)"
    )
    # The LOCAL surface keeps the full path — the user debugging their own machine needs it.
    assert collect_payload()["data_dir"] == str(tmp_path / "tempest-data")
