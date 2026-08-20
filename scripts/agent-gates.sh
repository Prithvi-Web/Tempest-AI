#!/usr/bin/env bash
# Phase 21's exit gate (docs/PLAN-V2.md §21) plus Phase 22's — the agent benchmarks and the
# retrieval benchmark, all run for real.
#
# The first three drive the SAME corpus — 55 real git repositories, 55 real shadow worktrees, 55
# real differential proofs — and ask three different questions of it. They are independent, so
# they run concurrently: serially they cost roughly nine minutes of wall-clock inside a gate that
# already costs fifteen, and nothing about them shares state. `resume_test` runs afterwards on
# its own, because it kills a child process mid-proof and measures how long a stalled model call
# takes to give up: both are wall-clock claims, and three benchmarks saturating the CPU is not
# the condition under which to make them.
#
# Output is captured per gate and printed in a fixed order. Interleaved output from three
# concurrent benchmarks is unreadable, and a gate nobody can read is a gate nobody checks.
set -u -o pipefail

cd "$(dirname "$0")/.."
LOGS="$(mktemp -d "${TMPDIR:-/tmp}/tempest-agent-gates.XXXXXX")"
trap 'rm -rf "$LOGS"' EXIT

export TEMPEST_DEV=1
export TEMPEST_NO_POWER_PAUSE=1

run() {   # run <name> <args...>
    local name="$1"; shift
    uv run python -m "tempest.dev.$name" "$@" > "$LOGS/$name.log" 2>&1
    echo "$?" > "$LOGS/$name.exit"
}

# A gate whose exit file never appeared did not pass — it did not RUN, which is worse. Reading a
# missing file as success is how a suite goes green about something it never executed.
exit_code_of() {
    if [ -f "$LOGS/$1.exit" ]; then cat "$LOGS/$1.exit"; else echo "missing"; fi
}

# `--tasks 50` on all three, not just the one the exit gate spells out. It is a FLOOR: it
# asserts the corpus holds at least fifty tasks and then runs all of them, so a gate can never
# quietly report a rate over a smaller set than the phase requires (trap 44).
run agent_bench  --tasks 50 --require-verdict-coverage 1.0 &
run intent_bench --tasks 50 --min-accuracy 0.90 --max-false-intended 0 &
run repair_bench --tasks 50 --min-success 0.60 --check-cheats &
wait

run resume_test --kill-mid-proof --sleep-mid-stream

# Phase 22's exit gate. It builds a real index over a real fixture repository and executes it,
# so it belongs with the agent gates rather than with the unit suite — but it is fast (seconds)
# and independent, so it rides along here instead of paying for its own runner.
run retrieval_bench --questions 40 --require-citations

# F14's exit gate (Phase 23): the escape suite run through the AGENT TERMINAL rather than the
# differential worker. `terminal.run` picks the same `sandbox.popen`, so this proves the terminal
# INHERITS the tier's containment rather than resembling it — and it catches the day somebody
# adds a convenience to the terminal that widens what a command can reach.
run escape_suite --tier T2 --surface agent-terminal

# P9 + F15's security gate (Phase 23): five injection payloads, each delivered through three
# channels at once, against a model scripted as ALREADY CAPTURED. The question is not "did the
# model resist?" — it is "did anything move?".
run redteam --injection

# F16's server half (Phase 23): the MCP server driven over a REAL stdio pipe by a real JSON-RPC
# client. What it cannot prove is the recorded demo of another agent refusing to finish on
# DIVERGENT — that needs a second product and a person to watch it, and the gate says so itself.
run mcp_check --server

failed=0
for name in agent_bench intent_bench repair_bench resume_test retrieval_bench escape_suite \
            redteam mcp_check; do
    echo "── $name ──"
    cat "$LOGS/$name.log" 2>/dev/null || echo "(this gate produced no output at all)"
    code="$(exit_code_of "$name")"
    echo "$name: exit $code"
    echo ""
    [ "$code" = "0" ] || failed=1
done

if [ "$failed" != "0" ]; then
    echo "agent-gates: at least one Phase 21 gate failed — see the exit lines above" >&2
fi
exit "$failed"
