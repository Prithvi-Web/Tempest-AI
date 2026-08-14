# Tempest verification. Steps activate as phases land (docs/PLAN.md); the full CLAUDE.md §13
# list is the v1 done bar. Never claim completion without pasting real output of `make verify`.

SHELL := /bin/bash
export PATH := $(HOME)/.local/bin:$(HOME)/.cargo/bin:$(PATH)

DESKTOP_MANIFEST := packages/desktop/src-tauri/Cargo.toml

.PHONY: verify verify-python verify-node verify-desktop verify-contract verify-grep-safe \
	gen-contracts ensure-sidecar sync

sync:
	uv sync --all-packages
	pnpm install --frozen-lockfile

verify: verify-python verify-node verify-desktop verify-contract verify-grep-safe
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

verify-python:
	uv run ruff check
	uv run ruff format --check
	uv run mypy --strict packages/engine/src packages/api/src
	TEMPEST_DEV=1 uv run pytest packages/engine packages/api -q --cov --cov-fail-under=85
	uv run python -m tempest.dev.corpus_check --min-pass 24 --repeats 5
	uv run python -m tempest.dev.escape_suite --tier T2   # Phase 10 containment (macOS T2)

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
