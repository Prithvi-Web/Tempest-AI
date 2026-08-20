"""P2 — a task that was interrupted does not start over.

The point of a durable turn log is what a RESTARTED process does with it, and until something
consumed `plan_resume` the log was a diary nobody read. These tests drive the whole thing: a real
repository, a real shadow worktree, a real proof, a real crash inside the proof, and a second
`run_task` that has to finish the work without asking the model anything.

States enumerated before the tests (trap 43): no history · a crash between the model turns and
the proof · a crash after the model turns but before the proof started · a task that already
finished · a resumed task whose shadow was deleted underneath it · a log written by a version
that recorded only the counters · a caller that explicitly wants a fresh run.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from tempest.agent import shadow as shadow_mod
from tempest.agent import turnlog as turnlog_mod
from tempest.agent.orchestrator import TaskAlreadyFinished, TaskSpec, run_task
from tempest.inference.providers import get
from tempest.model import Verdict

from ..helpers_fake_anthropic import FakeAnthropic, fake_anthropic_server

_BASE = "def total(xs):\n    return sum(xs)\n"
_CHANGED = "def total(xs):\n    return sum(xs) + 1\n"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        env={
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
            "PATH": "/usr/bin:/bin",
            "HOME": str(repo),
        },
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-b", "main")
    (root / "app.py").write_text(_BASE, encoding="utf-8")
    (root / ".tempest-first-party").write_text("", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "base")
    return root


def _env(url: str) -> dict[str, str]:
    provider = get("anthropic")
    return {provider.env_var: "sk-test-not-a-real-key", provider.base_url_env(): url}


def _write(contents: str) -> dict[str, Any]:
    return {"name": "write_file", "input": {"path": "app.py", "contents": contents}}


class _OneEdit:
    """A model that writes once and then says it is done."""

    def __init__(self, fake: FakeAnthropic, contents: str = _CHANGED) -> None:
        self.fake = fake
        fake.tool_uses = [_write(contents)]

    def __call__(self, kind: str, _detail: str) -> None:
        if kind == "tool":
            self.fake.tool_uses = []
            self.fake.reply_text = "done"


def _spec(repo: Path, task_id: str = "t", **kw: Any) -> TaskSpec:
    base: dict[str, Any] = {
        "repo": repo,
        "task_id": task_id,
        "prompt": "add one to total",
        "provider": "anthropic",
        "max_inputs": 6,
        "max_turns": 2,
        "max_repair_attempts": 0,
    }
    base.update(kw)
    return TaskSpec(**base)


class TestAFreshTaskIsUnchanged:
    def test_it_records_the_baseline_it_started_from(self, repo: Path) -> None:
        fake = FakeAnthropic()
        with fake_anthropic_server(fake) as url:
            run = run_task(_spec(repo), env=_env(url), on_event=_OneEdit(fake))
        log = turnlog_mod.TurnLog(repo)
        started = [c for c in log.history("t") if c.stage == turnlog_mod.STARTED]
        assert len(started) == 1
        assert started[0].payload["baseline"] == run.change.baseline
        assert not [c for c in log.history("t") if c.stage == turnlog_mod.RESUMED]


class TestACrashInsideTheProof:
    """The expensive gap. The model work is paid for and recorded; the verdict is not."""

    def _crash_once(self, repo: Path, monkeypatch: pytest.MonkeyPatch) -> FakeAnthropic:
        def boom(_cfg: Any) -> Any:
            raise KeyboardInterrupt("the process died inside the proof")

        monkeypatch.setattr("tempest.agent.orchestrator.run_prove", boom)
        fake = FakeAnthropic()
        with fake_anthropic_server(fake) as url, pytest.raises(KeyboardInterrupt):
            run_task(_spec(repo), env=_env(url), on_event=_OneEdit(fake))
        monkeypatch.undo()
        return fake

    def test_the_log_stops_at_proving(self, repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self._crash_once(repo, monkeypatch)
        stages = [c.stage for c in turnlog_mod.TurnLog(repo).history("t")]
        assert stages == [turnlog_mod.STARTED, turnlog_mod.TURNS_DONE, turnlog_mod.PROVING]

    def test_the_restart_finishes_without_asking_the_model_again(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The whole of P2 in one assertion pair: a verdict comes out, and the model — which is
        the part that costs money and cannot be repeated identically — is never called."""
        self._crash_once(repo, monkeypatch)

        fresh = FakeAnthropic()
        with fake_anthropic_server(fresh) as url:
            run = run_task(_spec(repo), env=_env(url), on_event=_OneEdit(fresh))

        assert fresh.requests == [], "a resumed task must not pay for the model twice"
        assert run.change.bundle_id, "it still ends on a verdict backed by a bundle (L16)"
        assert run.change.verdict is Verdict.DIVERGENT
        assert run.turns_used == 2, "the recorded turn count survives the restart"

    def test_the_restart_keeps_the_same_shadow_and_baseline(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A new baseline would silently re-point the proof at a different starting state — the
        agent's own edits would drop out of the diff and prove nothing at all."""
        self._crash_once(repo, monkeypatch)
        before = shadow_mod.attach(repo, "t")
        assert before is not None

        fresh = FakeAnthropic()
        with fake_anthropic_server(fresh) as url:
            run = run_task(_spec(repo), env=_env(url), on_event=_OneEdit(fresh))

        after = shadow_mod.attach(repo, "t")
        assert after is not None and after.baseline == before.baseline
        assert run.change.baseline == before.baseline
        assert len(shadow_mod.list_shadows(repo)) == 1, "no second worktree for one task"

    def test_the_narration_and_tool_calls_survive_the_restart(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ "Nothing already established may be forgotten" is the promise. A resumed run that
        returned an empty call list would have forgotten the only record of what was done."""
        self._crash_once(repo, monkeypatch)
        fresh = FakeAnthropic()
        with fake_anthropic_server(fresh) as url:
            run = run_task(_spec(repo), env=_env(url), on_event=_OneEdit(fresh))
        assert [c.name for c in run.calls] == ["write_file"]
        assert run.narration, "the model's own words are part of the record"

    def test_the_restart_says_it_is_resuming_and_why(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._crash_once(repo, monkeypatch)
        seen: list[tuple[str, str]] = []
        fresh = FakeAnthropic()
        edit = _OneEdit(fresh)

        def on_event(kind: str, detail: str) -> None:
            seen.append((kind, detail))
            edit(kind, detail)

        with fake_anthropic_server(fresh) as url:
            run_task(_spec(repo), env=_env(url), on_event=on_event)

        resumed = [d for k, d in seen if k == "resume"]
        assert any("interrupted inside the proof" in d for d in resumed)
        assert any("replayed 2 recorded turn(s)" in d for d in resumed)
        rows = [c for c in turnlog_mod.TurnLog(repo).history("t") if c.stage == turnlog_mod.RESUMED]
        assert len(rows) == 1 and rows[0].payload["redo_turns"] is False


class TestATaskThatAlreadyFinished:
    def test_running_it_again_is_refused_with_the_recorded_answer(self, repo: Path) -> None:
        fake = FakeAnthropic()
        with fake_anthropic_server(fake) as url:
            first = run_task(_spec(repo), env=_env(url), on_event=_OneEdit(fake))

        fresh = FakeAnthropic()
        with fake_anthropic_server(fresh) as url, pytest.raises(TaskAlreadyFinished) as caught:
            run_task(_spec(repo), env=_env(url), on_event=_OneEdit(fresh))

        assert caught.value.verdict == first.change.verdict.value
        assert caught.value.bundle_id == first.change.bundle_id
        assert fresh.requests == [], "a finished task costs nothing to not-re-run"
        assert "new task id" in str(caught.value)

    def test_a_finished_row_with_nothing_in_it_still_refuses(self, repo: Path) -> None:
        """Defensive: a FINISHED row written by an older version carries no verdict. The refusal
        is about the STAGE, not about how much the row happens to say."""
        log = turnlog_mod.TurnLog(repo)
        log.checkpoint("bare", turnlog_mod.FINISHED)
        fake = FakeAnthropic()
        with fake_anthropic_server(fake) as url, pytest.raises(TaskAlreadyFinished) as caught:
            run_task(_spec(repo, "bare"), env=_env(url), on_event=_OneEdit(fake))
        assert caught.value.verdict == ""


class TestTheAwkwardStates:
    def test_a_resume_whose_shadow_was_deleted_starts_a_fresh_one_at_the_same_baseline(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Someone cleaned out `.tempest/`. The log still knows what the task started from, and
        that recorded baseline is what the fresh shadow is built on — not a new reading of the
        user's tree, which has moved on since."""

        def boom(_cfg: Any) -> Any:
            raise KeyboardInterrupt("died in the proof")

        fake = FakeAnthropic()
        monkeypatch.setattr("tempest.agent.orchestrator.run_prove", boom)
        with fake_anthropic_server(fake) as url, pytest.raises(KeyboardInterrupt):
            run_task(_spec(repo), env=_env(url), on_event=_OneEdit(fake))
        monkeypatch.undo()

        recorded = shadow_mod.attach(repo, "t")
        assert recorded is not None
        baseline = recorded.baseline
        shadow_mod.discard(recorded)
        assert shadow_mod.attach(repo, "t") is None

        # The user has kept working. A baseline read from the tree NOW would be a different
        # commit, and proving against it would answer a question nobody asked — so this edit is
        # what makes the assertion below load-bearing rather than incidentally true.
        (repo / "app.py").write_text(_BASE + "\n\ndef extra():\n    return 1\n", encoding="utf-8")

        fresh = FakeAnthropic()
        with fake_anthropic_server(fresh) as url:
            run = run_task(_spec(repo), env=_env(url), on_event=_OneEdit(fresh))
        assert run.change.baseline == baseline, "the recorded baseline is the one that binds"
        rebuilt = shadow_mod.attach(repo, "t")
        assert rebuilt is not None
        assert "def extra" not in (rebuilt.path / "app.py").read_text(), (
            "the rebuilt shadow starts from what the task started from, not from today's tree"
        )

    def test_a_log_that_records_only_the_counters_replays_what_it_has(self, repo: Path) -> None:
        """Forward compatibility, stated rather than assumed: a TURNS_DONE row from before the
        transcript was recorded still tells the restart not to call the model, and the run says
        so with a smaller answer instead of pretending to a transcript it does not have."""
        shadow = shadow_mod.create(repo, "old")
        shadow_mod.write(shadow, "app.py", _CHANGED)
        log = turnlog_mod.TurnLog(repo)
        log.checkpoint("old", turnlog_mod.STARTED, prompt="p", baseline=shadow.baseline)
        log.checkpoint("old", turnlog_mod.TURNS_DONE, turns=3, stopped="the model finished")

        fake = FakeAnthropic()
        with fake_anthropic_server(fake) as url:
            run = run_task(_spec(repo, "old"), env=_env(url), on_event=_OneEdit(fake))

        assert fake.requests == []
        assert run.turns_used == 3
        assert run.stopped_because == "the model finished"
        assert run.calls == () and run.narration == ()
        assert run.change.verdict is Verdict.DIVERGENT

    def test_a_caller_can_demand_a_fresh_run_and_is_told_the_shadow_is_in_the_way(
        self, repo: Path
    ) -> None:
        """`resume=False` means "ignore the log", not "delete my work". Discarding a shadow is a
        destructive act and belongs to the caller who knows whether the staged edits matter."""
        fake = FakeAnthropic()
        with fake_anthropic_server(fake) as url:
            run_task(_spec(repo), env=_env(url), on_event=_OneEdit(fake))

        fresh = FakeAnthropic()
        with (
            fake_anthropic_server(fresh) as url,
            pytest.raises(shadow_mod.ShadowError, match="already exists"),
        ):
            run_task(_spec(repo), env=_env(url), on_event=_OneEdit(fresh), resume=False)

    def test_a_fresh_run_after_discarding_starts_over_completely(self, repo: Path) -> None:
        fake = FakeAnthropic()
        with fake_anthropic_server(fake) as url:
            run_task(_spec(repo), env=_env(url), on_event=_OneEdit(fake))
        recorded = shadow_mod.attach(repo, "t")
        assert recorded is not None
        shadow_mod.discard(recorded)

        fresh = FakeAnthropic()
        with fake_anthropic_server(fresh) as url:
            run = run_task(_spec(repo), env=_env(url), on_event=_OneEdit(fresh), resume=False)
        assert fresh.requests, "a fresh run asks the model"
        assert run.change.bundle_id


class TestOrphansAndRebuilds:
    """Two states the first version of the resume path got wrong, both found by review.

    An ORPHAN is a shadow with no log behind it — a process killed between creating the worktree
    and writing its first checkpoint. The old code wedged that task id forever. A REBUILD is the
    opposite: a log with no worktree, where replaying the recorded conversation would report a
    transcript full of work over a tree that has none of it.
    """

    def test_a_shadow_with_no_log_behind_it_is_adopted_rather_than_wedging_the_task(
        self, repo: Path
    ) -> None:
        """The crash window is one line wide and it closed the task id permanently: the log said
        "fresh", `create` said "already exists", and every later attempt died the same way."""
        orphan = shadow_mod.create(repo, "t")
        assert not turnlog_mod.TurnLog(repo).history("t"), "the crash was before the first row"

        fake = FakeAnthropic()
        with fake_anthropic_server(fake) as url:
            run = run_task(_spec(repo), env=_env(url), on_event=_OneEdit(fake))

        assert run.change.bundle_id
        assert fake.requests, "there was nothing to resume, so the model runs"
        after = shadow_mod.attach(repo, "t")
        assert after is not None and after.path == orphan.path
        assert len(shadow_mod.list_shadows(repo)) == 1

    def test_a_rebuilt_shadow_re_runs_the_turns_instead_of_replaying_them(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Replaying here would prove an EMPTY change while reporting a full transcript — a
        resume that looks like it worked and did not."""

        def boom(_cfg: Any) -> Any:
            raise KeyboardInterrupt("died in the proof")

        fake = FakeAnthropic()
        monkeypatch.setattr("tempest.agent.orchestrator.run_prove", boom)
        with fake_anthropic_server(fake) as url, pytest.raises(KeyboardInterrupt):
            run_task(_spec(repo), env=_env(url), on_event=_OneEdit(fake))
        monkeypatch.undo()

        recorded = shadow_mod.attach(repo, "t")
        assert recorded is not None
        shadow_mod.discard(recorded)

        fresh = FakeAnthropic()
        with fake_anthropic_server(fresh) as url:
            run = run_task(_spec(repo), env=_env(url), on_event=_OneEdit(fresh))

        assert fresh.requests, "the edits are gone, so the conversation is re-run, not replayed"
        assert "app.py" in run.change.changed_files, "and the change is really there again"
        rows = [c for c in turnlog_mod.TurnLog(repo).history("t") if c.stage == turnlog_mod.RESUMED]
        assert rows and rows[-1].payload["redo_turns"] is True
        assert "rebuilt" in str(rows[-1].payload["reason"])
