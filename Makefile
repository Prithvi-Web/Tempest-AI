# Tempest verification. Steps activate as phases land (docs/PLAN.md); the full CLAUDE.md §13
# list is the v1 done bar. Never claim completion without pasting real output of `make verify`.

SHELL := /bin/bash
export PATH := $(HOME)/.local/bin:$(HOME)/.cargo/bin:$(PATH)

DESKTOP_MANIFEST := packages/desktop/src-tauri/Cargo.toml

.PHONY: verify verify-python verify-agent verify-node verify-desktop verify-contract verify-grep-safe \
	gen-contracts ensure-sidecar sync bench bench-editor perf-gate

sync:
	uv sync --all-packages
	pnpm install --frozen-lockfile

# The LINUX run, simulated locally (traps 15/21/56): the exact suite Linux CI runs (macOS-only
# tests deselected) must also reach 100%. Run before pushing. CI's python job is this run on real
# Linux.
#
# TEMPEST_NO_SEATBELT=1 is the half that was missing, and it cost thirty-seven tests (ADR-0058).
# The target simulated Linux's test SET but not Linux's ENVIRONMENT: a macOS run still had T2
# Seatbelt underneath it, so a fixture that quietly needed a sandbox tier passed here and then
# executed NOTHING on the runner, where the ladder picks T1 Docker and no `tempest-sandbox:latest`
# image is ever built. This flag forces the ladder to its weakest rung — no tier at all — which is
# not a byte-faithful copy of CI's failure but a STRICT SUPERSET of it: anything that needs any
# rung of the ladder fails here first, loudly, on a laptop.
#
# This is defence in depth, not the primary guard: `mark_first_party` asserts that each fixture
# repository actually selected the trusted backend, and that fires in every run on every OS.
verify-linux-denominator:
	TEMPEST_DEV=1 TEMPEST_NO_POWER_PAUSE=1 TEMPEST_NO_SEATBELT=1 \
		uv run pytest packages/engine packages/api -q --cov \
		--deselect packages/engine/tests/integration/test_escape_suite.py \
		--deselect "packages/engine/tests/unit/test_report_and_cli.py::TestCliProve::test_user_repo_runs_under_t2_seatbelt_on_macos" \
		--deselect "packages/engine/tests/unit/test_fix_exec_kill_discipline.py::TestRunnerKill::test_kill_of_an_exited_unreaped_child_falls_back_to_direct_kill" \
		--deselect "packages/engine/tests/unit/test_fix_exec_kill_discipline.py::TestCancelKillGroup::test_kill_group_on_an_exited_unreaped_child_falls_back_to_direct_kill"

# Phase 20.1b: the WEBVIEW half of the §5 table — open-file and keystroke→render, measured by
# the desktop E2E leg against a real CodeMirror instance and written to bench/editor-metrics.json
# for `make bench` to merge. Deliberately NOT in `make verify`: these are timings, and a
# correctness suite that fails because a laptop was busy stops being trusted (the same reasoning
# that keeps perf-gate out). Run it before `make bench` when you want the editor budgets armed.
bench-editor:
	cd packages/desktop && TEMPEST_NO_POWER_PAUSE=1 npx playwright test --grep @bench

# Phase 11 perf bench. Gate: make bench && uv run python -m tempest.dev.bench_guard --max-regression 15
# Merges bench/editor-metrics.json when `make bench-editor` has produced it; when it has not, the
# editor rows stay NOT-YET-MEASURED rather than quietly reading as met.
bench:
	uv run python -m tempest.dev.bench

# Phase 19.7 (L22): the master prompt's §5 budget table as a gate. Deliberately NOT in
# `make verify` — it needs a fresh `make bench` and its numbers depend on machine load, and
# `make verify` must stay deterministic.
#
# WHERE IT RUNS, stated exactly: locally, by hand, after `make bench`. It does NOT run in CI —
# `grep -rn "perf_suite\|perf-gate" .github/` is empty. This comment used to claim it "belongs
# to the perf flow and the CI bench job"; the CI bench job runs `make bench` and `bench_guard`,
# which judge the v1 five metrics, and never invokes this target. Arming it in CI needs two
# things first: a committed `bench/baseline-linux.json` (without one the regression bar prints
# PENDING and never binds), and a decision about cold_launch, which is deliberately RED here on
# environment drift. Queued in HANDOFF-NEXT §4, not silently implied by a Makefile comment.
perf-gate:
	uv run python -m tempest.dev.perf_suite --enforce-budgets

verify: verify-python verify-agent verify-node verify-desktop verify-contract verify-grep-safe
	@echo "── verify: all live steps green ──"

# Tri-boundary generation (CLAUDE.md §9b): Pydantic → openapi.json → domain-schema.json →
# typify (Rust) + tauri-specta (TS bindings). Committed output, diffed by verify-contract.
gen-contracts:
	pnpm gen:api
	node packages/shared-schema/scripts/gen-domain-schema.mjs
	cargo typify packages/shared-schema/domain-schema.json \
		--additional-derive specta::Type \
		-o packages/desktop/src-tauri/src/generated/domain.rs
	cargo run -q --manifest-path $(DESKTOP_MANIFEST) -p tempest-desktop-devtools --bin export_bindings
	# Boundary D (§9c, ADR-0035): the Agent Tool Protocol. Its artifacts land inside the paths
	# verify-contract already diffs, so the fourth boundary is drift-gated by the same command.
	cargo run -q --manifest-path $(DESKTOP_MANIFEST) -p tempest-desktop-devtools --bin export_agent_tools

# tauri-build refuses to compile without the externalBin staged, and the sidecar binary never
# enters git — a clean clone must build it before any cargo step can run.
ensure-sidecar:
	@test -f "packages/desktop/src-tauri/binaries/tempest-server-$$(rustc -vV | sed -n 's/host: //p')" \
		|| ./packages/desktop/build-server.sh

verify-desktop: ensure-sidecar
	cargo clippy --manifest-path $(DESKTOP_MANIFEST) --workspace --all-targets -- -D warnings
	cargo test -q --manifest-path $(DESKTOP_MANIFEST) --workspace
	pnpm --filter @tempest/desktop typecheck
	@! grep -rn --include='*.ts' --include='*.tsx' 'from "@tauri-apps/api/core"' \
		packages/desktop/src | grep -v "src/generated/" \
		|| (echo "handwritten invoke() is banned — use the generated bindings (§9b)"; exit 1)
	# E2E: the real webview UI against the real engine (vite + stdio sidecar via e2e/bridge.mjs),
	# console-clean gate enforced. This ALSO runs in CI since b11d533 (the desktop job installs a
	# chromium and runs the same `test:e2e` script) — the comment here said the opposite for two
	# commits after that landed, which is the build file asserting against the workflow file.
	pnpm --filter @tempest/desktop test:e2e

verify-python:
	uv run ruff check
	uv run ruff format --check
	uv run mypy --strict packages/engine/src packages/api/src
	# CI type-checks on Linux, where mypy specializes sys.platform differently (trap 20) —
	# check that view locally too so local green cannot hide a Linux-only mypy failure.
	uv run mypy --strict --platform linux packages/engine/src packages/api/src
	TEMPEST_DEV=1 TEMPEST_NO_POWER_PAUSE=1 uv run pytest packages/engine packages/api -q --cov
	TEMPEST_NO_POWER_PAUSE=1 uv run python -m tempest.dev.corpus_check --min-pass 24 --repeats 5
	TEMPEST_NO_POWER_PAUSE=1 uv run python -m tempest.dev.escape_suite --tier T2   # Phase 10 containment (macOS T2)
	uv run python -m tempest.dev.redaction_check --planted-secrets   # Phase 17 (L9 proven)
	uv run python -m tempest.dev.license_check --third-party-notices  # Phase 19.1 (L25 attribution)
	uv run python -m tempest.dev.provider_matrix --min-providers 12   # Phase 19.5 (P1 breadth)

# Phase 21's exit gate (PLAN-V2 §21, ADR-0053) and Phase 22's (§22, ADR-0054): F1's verdict
# coverage, F2's classification accuracy, F3's repair rate and refused cheats, P2's survival of a
# SIGKILL mid-proof, F13's retrieval — 40 questions, 15 of which source text cannot answer — and
# F14's containment (the escape suite run through the agent terminal itself), and P9's injection
# suite — five payloads against a model scripted as already captured — and F16's MCP server,
# driven over a real stdio pipe.
# Real benchmarks over real repositories; the script runs the three corpus gates concurrently and
# prints every gate in a fixed order.
verify-agent:
	./scripts/agent-gates.sh

verify-node:
	pnpm -r typecheck
	pnpm -r test
	pnpm --filter @tempest/desktop build

verify-contract:
	$(MAKE) gen-contracts
	git diff --exit-code packages/shared-schema \
		packages/desktop/src/generated packages/desktop/src-tauri/src/generated

verify-grep-safe:
	@! grep -rn --include='*.py' --include='*.ts' --include='*.tsx' -w 'SAFE' packages/ \
		|| (echo 'forbidden verdict string found'; exit 1)
