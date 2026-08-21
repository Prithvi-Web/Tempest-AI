"""Phase 21's exit gate, part 4 of 4 — P2: a turn that survives the process running it.

    python -m tempest.dev.resume_test --kill-mid-proof --sleep-mid-stream

**Two interruptions, and they fail in opposite directions.**

`--kill-mid-proof` is the expensive one. A REAL child process runs a REAL agent task against a
real repository, and is `SIGKILL`ed — no unwinding, no `finally`, no flush — the moment the
durable log says it entered the proof. Then a second process picks the task up. What must be true
afterwards is not "it finished": it is that it finished **without asking the model anything**, on
**the same shadow worktree**, against **the same baseline**. A resume that re-runs the
conversation has not resumed; it has restarted while looking like it resumed, and the user pays
for it twice.

`--sleep-mid-stream` is the quiet one. The peer accepts the connection and then says nothing —
the shape of a model that has not refused and has not answered. The turn loop must give up on its
own wall-clock bound, and the edits already staged must still be **proved and shown with a real
verdict** (L23: degrade explicitly, never silently). A run that threw the staged work away
because the model went quiet would be discarding exactly the change a user most needs a verdict
about. Then, because the task did finish, a second run of the same task id must be REFUSED rather
than silently redone.

Everything here is real except the model (L4): real git repositories, real worktrees, a real
`SIGKILL`, a real differential proof, real sockets.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from tempest.agent import shadow as shadow_mod
from tempest.agent import turnlog as turnlog_mod
from tempest.agent.orchestrator import TaskAlreadyFinished, TaskSpec, run_task
from tempest.bundle.bundle import read_bundle, run_verdict
from tempest.dev._fake_peer import FakeAnthropic, fake_anthropic_server
from tempest.dev._first_party import mark_first_party
from tempest.inference.providers import get

#: Wide enough that the proof takes seconds rather than milliseconds — the kill has to land
#: INSIDE it, and a proof that is over before the poller looks would test nothing.
_PROOF_INPUTS = 40

_BASE = (
    "def total(xs):\n    return sum(xs)\n\n\n"
    "def biggest(xs):\n    return max(xs)\n\n\n"
    "def smallest(xs):\n    return min(xs)\n\n\n"
    "def width(xs):\n    return len(str(xs))\n"
)
_CHANGED = _BASE.replace("return sum(xs)", "return sum(xs) + 1")

_TASK_ID = "resume-under-test"


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        env={
            "GIT_AUTHOR_NAME": "tempest-bench",
            "GIT_AUTHOR_EMAIL": "bench@tempest",
            "GIT_COMMITTER_NAME": "tempest-bench",
            "GIT_COMMITTER_EMAIL": "bench@tempest",
            "PATH": "/usr/bin:/bin",
            "HOME": str(repo),
        },
    )


def _make_repo(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir(parents=True)
    _git(repo, "init", "-b", "main")
    (repo / "app.py").write_text(_BASE, encoding="utf-8")
    mark_first_party(repo)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "base")
    return repo


def _env(url: str) -> dict[str, str]:
    provider = get("anthropic")
    return {provider.env_var: "sk-resume-not-a-real-key", provider.base_url_env(): url}


def _spec(repo: Path, **kw: Any) -> TaskSpec:
    base: dict[str, Any] = {
        "repo": repo,
        "task_id": _TASK_ID,
        "prompt": "add one to total",
        "provider": "anthropic",
        "max_inputs": _PROOF_INPUTS,
        "max_turns": 1,
        "max_repair_attempts": 0,
    }
    base.update(kw)
    return TaskSpec(**base)


def _arm(fake: FakeAnthropic) -> None:
    """One write, every turn. The turn budget of 1 is what ends the conversation, so the peer
    does not have to be told when to stop — which matters because the peer lives in THIS process
    and the agent under test lives in another one."""
    fake.tool_uses = [{"name": "write_file", "input": {"path": "app.py", "contents": _CHANGED}}]


def _run_child(repo: Path, url: str) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [sys.executable, "-m", "tempest.dev.resume_test", "--child", str(repo), url],
        env={**os.environ, "TEMPEST_DEV": "1", "TEMPEST_NO_POWER_PAUSE": "1"},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        # Its own process group, so the SIGKILL reaps the sandboxed workers it spawned too. A
        # kill that leaves the children alive is not the crash it claims to simulate.
        start_new_session=True,
    )


def _verdict_on_disk(run: Any) -> str:
    """The verdict re-derived from the bundle the run wrote, or "" when it cannot be read.

    Asking the run object whether it has a verdict and a bundle id asks a type whether it is
    itself: `ProvenChange` refuses to exist without either. Reading the bundle back and applying
    the engine's own aggregation can DISAGREE, and that disagreement is L16's actual failure.
    """
    try:
        return run_verdict(read_bundle(run.change.bundle_dir).targets).value
    except (OSError, ValueError, KeyError):
        return ""


def _wait_for_stage(repo: Path, stage: str, *, timeout: float) -> bool:
    log = turnlog_mod.TurnLog(repo)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        last = log.last(_TASK_ID)
        if last is not None and last.stage == stage:
            return True
        time.sleep(0.02)
    return False


def kill_mid_proof() -> list[Check]:
    checks: list[Check] = []
    with TemporaryDirectory(prefix="tempest-resume-") as tmp:
        repo = _make_repo(Path(tmp))
        fake = FakeAnthropic()
        _arm(fake)
        with fake_anthropic_server(fake) as url:
            child = _run_child(repo, url)
            entered = _wait_for_stage(repo, turnlog_mod.PROVING, timeout=120.0)
            # A child that is already gone is not an error here — the checks below decide what
            # that means, and they can see the log it left behind.
            with contextlib.suppress(ProcessLookupError):
                os.killpg(os.getpgid(child.pid), signal.SIGKILL)
            child.wait(timeout=30)

            checks.append(
                Check(
                    "the child reached the proof before it was killed",
                    entered,
                    "the durable log recorded PROVING",
                )
            )
            stages = [c.stage for c in turnlog_mod.TurnLog(repo).history(_TASK_ID)]
            checks.append(
                Check(
                    "the kill landed inside the proof",
                    stages[-1:] == [turnlog_mod.PROVING],
                    f"last recorded stage: {stages[-1] if stages else 'NONE'}",
                )
            )
            checks.append(
                Check(
                    "the model work was recorded before the crash",
                    turnlog_mod.TURNS_DONE in stages,
                    f"stages: {' → '.join(stages)}",
                )
            )

            before = shadow_mod.attach(repo, _TASK_ID)
            requests_before = len(fake.requests)
            # A witness INSIDE the worktree. Comparing `before.path` with `after.path` proved
            # nothing: both are derived from the task id and are equal whether the directory was
            # reused or rebuilt underneath. A file only survives if the directory does.
            witness = ""
            if before is not None:
                witness_path = before.path / ".tempest-resume-witness"
                witness_path.write_text("the same worktree", encoding="utf-8")
                witness = witness_path.name
            # And the user's tree moves on, so a baseline re-derived from it NOW would differ
            # from the recorded one. Without this the baseline check compared two values that
            # agree whatever the code does.
            (repo / "note.txt").write_text("the user kept working\n", encoding="utf-8")

            try:
                run = run_task(_spec(repo), env=_env(url), on_event=None)
            except TaskAlreadyFinished as exc:
                # The child completed before the kill landed. That is a real outcome of a timing
                # test and it must be REPORTED, not raised: a traceback here would look like an
                # infrastructure fault rather than the gate's own answer.
                checks.append(
                    Check(
                        "the restart had work left to do",
                        False,
                        f"the child finished before it could be killed ({exc})",
                    )
                )
                return checks

            stored = _verdict_on_disk(run)
            checks.append(
                Check(
                    "the restart produced a verdict the STORED bundle supports",
                    stored == run.change.verdict.value,
                    f"reported {run.change.verdict.value}, bundle on disk says "
                    f"{stored or 'NOTHING'} ({run.change.bundle_id})",
                )
            )
            checks.append(
                Check(
                    "the model was NOT asked again",
                    len(fake.requests) == requests_before,
                    f"{len(fake.requests) - requests_before} extra model request(s)",
                )
            )
            after = shadow_mod.attach(repo, _TASK_ID)
            survived = bool(witness) and after is not None and (after.path / witness).is_file()
            checks.append(
                Check(
                    "the same shadow worktree was reused",
                    survived,
                    "a file written into the worktree before the restart is still there"
                    if survived
                    else "the witness file is gone: the worktree was rebuilt, not reused",
                )
            )
            checks.append(
                Check(
                    "the baseline did not move, even though the user's tree did",
                    before is not None and run.change.baseline == before.baseline,
                    f"recorded {before.baseline if before else None}, proved {run.change.baseline}",
                )
            )
            checks.append(
                Check(
                    "no second worktree was created for the task",
                    len(shadow_mod.list_shadows(repo)) == 1,
                    f"{len(shadow_mod.list_shadows(repo))} shadow(s)",
                )
            )
            checks.append(
                Check(
                    "the agent's staged edit survived the crash",
                    "app.py" in run.change.changed_files,
                    f"changed: {', '.join(run.change.changed_files) or 'nothing'}",
                )
            )
    return checks


def sleep_mid_stream() -> list[Check]:
    checks: list[Check] = []
    with TemporaryDirectory(prefix="tempest-resume-") as tmp:
        repo = _make_repo(Path(tmp))
        fake = FakeAnthropic()
        _arm(fake)
        # The FIRST request answers and stages the edit; the SECOND accepts the connection and
        # goes quiet for far longer than the turn loop's wall-clock bound — long enough that
        # simply waiting the peer out cannot pass the timing check below. An earlier version
        # stalled for 4s and allowed 7s, so a loop with no bound at all would have passed it
        # (found by review, trap 47).
        fake.stall_seconds = 30.0
        fake.stall_on_request = 2
        with fake_anthropic_server(fake) as url:
            started = time.monotonic()
            run = run_task(
                _spec(repo, max_turns=3, model_timeout_s=1.0), env=_env(url), on_event=None
            )
            elapsed = time.monotonic() - started

            checks.append(
                Check(
                    "the turn loop gave up on its own bound",
                    run.stopped_because.startswith("model unavailable"),
                    run.stopped_because or "the loop did not say why it stopped",
                )
            )
            checks.append(
                Check(
                    "it gave up on TIME, not by waiting the peer out",
                    elapsed < fake.stall_seconds,
                    f"{elapsed:.1f}s elapsed (turn loop AND proof) against a 1.0s model bound "
                    f"and a {fake.stall_seconds:.0f}s stall — passing requires the loop to have "
                    f"abandoned the call, since the peer never answers before the stall ends",
                )
            )
            checks.append(
                Check(
                    "the staged work was proved anyway",
                    _verdict_on_disk(run) == run.change.verdict.value
                    and "app.py" in run.change.changed_files,
                    f"{run.change.verdict.value} over {', '.join(run.change.changed_files)}, "
                    f"and the stored bundle agrees",
                )
            )
            checks.append(
                Check(
                    "the verdict is the engine's, not a placeholder",
                    run.change.verdict.value in {"DIVERGENT", "EQUIVALENT_UNDER_BUDGET"},
                    run.change.verdict.value,
                )
            )
            stages = [c.stage for c in turnlog_mod.TurnLog(repo).history(_TASK_ID)]
            checks.append(
                Check(
                    "the task is recorded as finished",
                    stages[-1:] == [turnlog_mod.FINISHED],
                    " → ".join(stages),
                )
            )

            refused = False
            try:
                run_task(_spec(repo), env=_env(url), on_event=None)
            except TaskAlreadyFinished:
                refused = True
            checks.append(
                Check(
                    "a finished task is refused rather than silently redone",
                    refused,
                    "running it again would build a second shadow and re-answer under one id",
                )
            )
    return checks


def _child_main(repo: str, url: str) -> int:  # pragma: no cover — runs only as a subprocess
    """The process that gets killed. It does exactly what any caller would do."""
    run_task(_spec(Path(repo)), env=_env(url), on_event=None)
    return 0


def _render(title: str, checks: list[Check]) -> str:
    lines = [title]
    for check in checks:
        lines.append(f"  {'PASS' if check.ok else 'FAIL'}  {check.name}  —  {check.detail}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kill-mid-proof", action="store_true")
    parser.add_argument("--sleep-mid-stream", action="store_true")
    parser.add_argument("--child", nargs=2, metavar=("REPO", "URL"), help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if args.child:
        return _child_main(*args.child)  # pragma: no cover — subprocess entry point

    # No flags means both. A gate whose default is "check nothing" passes for the wrong reason.
    run_kill = args.kill_mid_proof or not args.sleep_mid_stream
    run_sleep = args.sleep_mid_stream or not args.kill_mid_proof

    checks: list[Check] = []
    if run_kill:
        section = kill_mid_proof()
        print(_render("resume_test --kill-mid-proof", section))
        checks += section
    if run_sleep:
        section = sleep_mid_stream()
        print(_render("resume_test --sleep-mid-stream", section))
        checks += section

    failed = [c for c in checks if not c.ok]
    print("")
    print(f"resume_test: {len(checks) - len(failed)}/{len(checks)} checks passed")
    for check in failed:
        print(f"RESUME-TEST {check.name}: {check.detail}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
