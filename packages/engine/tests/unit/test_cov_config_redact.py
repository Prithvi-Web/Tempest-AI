"""Config load failures over the real filesystem, and redaction guard branches whose failure
would either corrupt outbound text (empty-string replacement) or leak an identity."""

from pathlib import Path

import pytest

from tempest.config import TempestConfig, TempestConfigError
from tempest.redact import RedactionContext, redact_text, scrub_traceback


class TestConfigErrors:
    def test_unreadable_config_file_is_actionable(self, tmp_path: Path) -> None:
        # tempest.toml exists but cannot be read as a file (here: it is a directory) —
        # the error must say so instead of surfacing a raw OSError traceback.
        (tmp_path / "tempest.toml").mkdir()
        with pytest.raises(TempestConfigError, match="could not be read"):
            TempestConfig.load(tmp_path)

    def test_non_numeric_tolerance_is_rejected(self, tmp_path: Path) -> None:
        (tmp_path / "tempest.toml").write_text('[compare]\nfloat_rel_tol = "tight"\n')
        with pytest.raises(TempestConfigError, match="must be a number"):
            TempestConfig.load(tmp_path)

    def test_boolean_wall_seconds_is_rejected_not_coerced(self, tmp_path: Path) -> None:
        (tmp_path / "tempest.toml").write_text("[budgets]\nmax_wall_seconds = true\n")
        with pytest.raises(TempestConfigError, match="must be a number"):
            TempestConfig.load(tmp_path)


class TestRedactGuardBranches:
    def test_empty_secret_and_repo_entries_do_not_corrupt_text(self) -> None:
        # str.replace("") would inject a marker between every character — the empty-value
        # guards are load-bearing, so both directions (empty and real) are exercised.
        ctx = RedactionContext(
            repo_names=("", "secret-repo"), env_secret_values=("", "hunter42seekrit")
        )
        out = redact_text("token hunter42seekrit lives in secret-repo", ctx)
        assert out == "token [REDACTED:env] lives in [REPO]"

    def test_root_home_dir_yields_no_username_scrub(self) -> None:
        # home_dir="/" has no username component; nothing must be marked [USER].
        out = redact_text("hello world", RedactionContext(home_dir="/"))
        assert "[USER]" not in out

    def test_home_dir_username_is_scrubbed_outside_home_paths(self) -> None:
        ctx = RedactionContext(home_dir="/home/carol")
        out = redact_text("/var/folders/xy/carol-cache/blob", ctx)
        assert "carol" not in out
        assert "[USER]" in out


class TestScrubTracebackNewline:
    _TB_BODY = (
        "Traceback (most recent call last):\n"
        '  File "/home/carol/app/x.py", line 3, in fn\n'
        "    boom()\n"
        "ValueError: no"
    )

    def test_trailing_newline_is_preserved(self) -> None:
        out = scrub_traceback(self._TB_BODY + "\n", RedactionContext(home_dir="/home/carol"))
        assert out.endswith("ValueError: no\n")
        assert "[source line removed]" in out
        assert "in [symbol]" in out
        assert "boom()" not in out

    def test_absent_trailing_newline_is_not_invented(self) -> None:
        out = scrub_traceback(self._TB_BODY, RedactionContext(home_dir="/home/carol"))
        assert out.endswith("ValueError: no")
        assert not out.endswith("\n")
