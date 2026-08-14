# Tempest verification. Steps activate as phases land (docs/PLAN.md); the full CLAUDE.md §13
# list is the v1 done bar. Never claim completion without pasting real output of `make verify`.

SHELL := /bin/bash
export PATH := $(HOME)/.local/bin:$(HOME)/.cargo/bin:$(PATH)

DESKTOP_MANIFEST := packages/desktop/src-tauri/Cargo.toml

.PHONY: verify verify-python verify-node verify-desktop verify-contract verify-grep-safe \
	gen-contracts sync

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
	cargo run -q --manifest-path $(DESKTOP_MANIFEST) --bin export_bindings

verify-desktop:
	cargo clippy --manifest-path $(DESKTOP_MANIFEST) --all-targets -- -D warnings
	cargo test -q --manifest-path $(DESKTOP_MANIFEST)
	pnpm --filter @tempest/desktop typecheck

verify-python:
	uv run ruff check
	uv run ruff format --check
	uv run mypy --strict packages/engine/src packages/api/src
	TEMPEST_DEV=1 uv run pytest packages/engine packages/api -q --cov --cov-fail-under=85
	uv run python -m tempest.dev.corpus_check --min-pass 24 --repeats 5

verify-node:
	pnpm -r typecheck
	pnpm -r test
	pnpm --filter @tempest/web build

verify-contract:
	$(MAKE) gen-contracts
	git diff --exit-code packages/shared-schema packages/web/src/generated \
		packages/desktop/src/generated packages/desktop/src-tauri/src/generated

verify-grep-safe:
	@! grep -rn --include='*.py' --include='*.ts' --include='*.tsx' -w 'SAFE' packages/ \
		|| (echo 'forbidden verdict string found'; exit 1)
