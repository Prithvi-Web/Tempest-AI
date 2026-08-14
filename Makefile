# Tempest verification. Steps activate as phases land (docs/PLAN.md); the full CLAUDE.md §13
# list is the v1 done bar. Never claim completion without pasting real output of `make verify`.

SHELL := /bin/bash
export PATH := $(HOME)/.local/bin:$(PATH)

.PHONY: verify verify-python verify-node verify-contract verify-grep-safe sync

sync:
	uv sync --all-packages
	pnpm install --frozen-lockfile

verify: verify-python verify-node verify-contract verify-grep-safe
	@echo "── verify: all live steps green ──"

verify-python:
	uv run ruff check
	uv run ruff format --check
	uv run mypy --strict packages/engine/src packages/api/src
	uv run pytest packages/engine packages/api -q --cov --cov-fail-under=85

verify-node:
	pnpm -r typecheck
	pnpm -r test
	pnpm --filter @tempest/web build

verify-contract:
	pnpm gen:api
	git diff --exit-code packages/shared-schema packages/web/src/generated

verify-grep-safe:
	@! grep -rn --include='*.py' --include='*.ts' --include='*.tsx' -w 'SAFE' packages/ \
		|| (echo 'forbidden verdict string found'; exit 1)
