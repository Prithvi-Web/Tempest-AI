"""THE PHASE 2 GATE: `python -m tempest.dev.corpus_check --min-pass 24 --repeats 5`.

For each of the 30 impure corpus functions: record once, then replay `--repeats` times; the
function is STABLE only if every replay's observation compares Equal (canonical values, effect
ledgers, streams) to the recording. Below --min-pass the exit code is nonzero and the build must
stop and report (master spec §4.4 — do not build the dashboard on sand).
"""

import argparse
import shutil
import socket
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from tempest.compare.compare import CompareConfig, Equal, compare
from tempest.execute.runner import DeterminismJob, run_batch
from tempest.execute.sandbox import ProcessSandbox

_ROUTES: dict[str, object] = {
    "/api/user": {"status": 200, "body": '{"name": "storm-rider", "id": 7}'},
    "/health": {"status": 200, "body": "ok"},
    "/robots.txt": {"status": 200, "body": "User-agent: *\nDisallow: /private\n"},
    "/items?page=1": {"status": 200, "body": '{"items": ["a", "b"]}'},
    "/items?page=2": {"status": 200, "body": '{"items": ["c"]}'},
    "/artifact.bin": {"status": 200, "body": "binary-ish-payload-0123456789"},
    "/v2/data": {"status": 200, "body": "v2-payload"},
    "/v1/data": {"status": 200, "body": "v1-payload"},
    "/config.txt": {"status": 200, "body": "alpha=1\nbeta=2\ngamma=3\n"},
    "/flaky": {"status": 404, "body": "gone"},
    "/stable": {"status": 200, "body": "stable-payload"},
    "/token": {"status": 200, "body": "tok-abc123"},
    "/echo?q=storm": {"status": 200, "body": "echo:storm"},
}


@dataclass(frozen=True)
class CorpusCase:
    module: str
    fn: str
    args_literal: str
    needs_loopback: bool = False


CASES: tuple[CorpusCase, ...] = (
    # 10 HTTP
    CorpusCase("httpfns", "fetch_user_name", "('__LOOPBACK__',)", True),
    CorpusCase("httpfns", "check_health", "('__LOOPBACK__',)", True),
    CorpusCase("httpfns", "fetch_with_user_agent", "('__LOOPBACK__',)", True),
    CorpusCase("httpfns", "paginate_two_pages", "('__LOOPBACK__',)", True),
    CorpusCase("httpfns", "download_size", "('__LOOPBACK__',)", True),
    CorpusCase("httpfns", "fetch_primary_or_fallback", "('__LOOPBACK__', True)", True),
    CorpusCase("httpfns", "count_config_lines", "('__LOOPBACK__',)", True),
    CorpusCase("httpfns", "retry_on_404", "('__LOOPBACK__',)", True),
    CorpusCase("httpfns", "double_read_same_endpoint", "('__LOOPBACK__',)", True),
    CorpusCase("httpfns", "query_echo", "('__LOOPBACK__', 'storm')", True),
    # 10 filesystem
    CorpusCase("fsfns", "read_config_key", "('data/config.json', 'name')"),
    CorpusCase("fsfns", "count_lines", "('data/notes.txt',)"),
    CorpusCase("fsfns", "read_optional_dotfile", "('data/missing.rc', 'fallback')"),
    CorpusCase("fsfns", "extension_histogram", "('data',)"),
    CorpusCase("fsfns", "magic_bytes", "('data/blob.bin',)"),
    CorpusCase("fsfns", "write_report", "('report.txt', 'four score and seven')"),
    CorpusCase("fsfns", "append_audit_line", "('audit.log', 'user logged in')"),
    CorpusCase("fsfns", "copy_text_file", "('data/notes.txt', 'notes-copy.txt')"),
    CorpusCase("fsfns", "env_or_file_setting", "('TEMPEST_UNSET_SETTING', 'data/setting.txt')"),
    CorpusCase("fsfns", "checksum_file", "('data/config.json',)"),
    # 10 time/random
    CorpusCase("timerandfns", "session_token", "(16,)"),
    CorpusCase("timerandfns", "request_id", "()"),
    CorpusCase("timerandfns", "jittered_delay", "(0.5,)"),
    CorpusCase("timerandfns", "pick_variant", "(['control', 'blue', 'green'],)"),
    CorpusCase("timerandfns", "shuffled_copy", "([1, 2, 3, 4, 5, 6],)"),
    CorpusCase("timerandfns", "cache_key_epoch", "()"),
    CorpusCase("timerandfns", "log_timestamp", "()"),
    CorpusCase("timerandfns", "monotonic_pair_ordered", "()"),
    CorpusCase("timerandfns", "roll_dice", "(5,)"),
    CorpusCase("timerandfns", "expiry_deadline", "(3600,)"),
)


def _free_port() -> int:
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return int(port)


def _corpus_source() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "corpus" / "impure"
        if candidate.is_dir():
            return candidate
    raise SystemExit("corpus/impure not found — run from the tempest repository")


def check_corpus(repeats: int, verbose: bool = True) -> tuple[int, list[str]]:
    """Returns (stable_count, failure_descriptions). Real execution only (Law L4)."""
    sandbox = ProcessSandbox()
    cfg = CompareConfig()
    failures: list[str] = []
    stable = 0

    with tempfile.TemporaryDirectory(prefix="tempest-corpus-") as workdir:
        root = Path(workdir) / "impure"
        shutil.copytree(_corpus_source(), root)

        for case in CASES:
            name = f"{case.module}.{case.fn}{case.args_literal}"
            port = _free_port() if case.needs_loopback else 0
            record_job = DeterminismJob(
                mode="record",
                loopback_routes=_ROUTES if case.needs_loopback else None,
                loopback_port=port,
            )
            inputs = [(case.args_literal, "{}")]
            (rec,) = run_batch(root, case.module, case.fn, inputs, sandbox, determinism=record_job)
            if rec.uninterceptable is not None:
                failures.append(f"{name}: uninterceptable at record — {rec.uninterceptable}")
                continue
            if rec.cassette is None:
                failures.append(f"{name}: record produced no cassette (outcome {rec.outcome})")
                continue

            replay_job = DeterminismJob(
                mode="replay", cassettes={0: rec.cassette}, loopback_port=port
            )
            ok = True
            for attempt in range(repeats):
                (rep,) = run_batch(
                    root, case.module, case.fn, inputs, sandbox, determinism=replay_job
                )
                result = compare(rec, rep, cfg)
                if not isinstance(result, Equal):
                    failures.append(f"{name}: replay #{attempt + 1} diverged — {result}")
                    ok = False
                    break
            if ok:
                stable += 1
                if verbose:
                    print(f"  STABLE   {name}")
            elif verbose:
                print(f"  UNSTABLE {name}")

    return stable, failures


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--min-pass", type=int, default=24)
    parser.add_argument("--repeats", type=int, default=5)
    args = parser.parse_args()

    print(f"tempest corpus check: {len(CASES)} impure functions x {args.repeats} replays")
    stable, failures = check_corpus(args.repeats)
    print(f"\n{stable}/{len(CASES)} stable across {args.repeats} consecutive replays")
    for failure in failures:
        print(f"  FAIL: {failure}")
    if stable < args.min_pass:
        print(
            f"\nBELOW THE BAR ({args.min_pass}). The determinism layer is not trustworthy yet — "
            "STOP and report before building anything on top of it (master spec §4.4)."
        )
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
