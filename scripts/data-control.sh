#!/usr/bin/env bash
# C6.0 — the CONTROL measurement: LibreChat's own 66 data-layer suites, against a real `mongod`.
#
# WHY THIS EXISTS. C6's job is a SQLite-backed document store that LibreChat's vendored Mongoose
# layer cannot tell from MongoDB. "Green against the store C1 selected" is only a claim you can
# check if you also know what green looks like against the store it is replacing: a suite that
# fails against @tempest/docstore AND against real MongoDB has found nothing, and only a suite
# that fails against exactly one of them has (trap 54 — a differential check must ask both sides
# under the same conditions). This script produces that other side.
#
# WHAT IT DOWNLOADS, AND WHERE. `mongodb-memory-server` fetches a MongoDB Community Server binary
# — SSPL, which L33 keeps out of the product. Three things keep that honest:
#   * it is a devDependency of the vendored package, never a runtime one (`store_check` check 3);
#   * its install-time postinstall is DENIED in pnpm-workspace.yaml's `allowBuilds`, so a plain
#     `pnpm install` and every CI run fetch nothing — only this script does;
#   * MONGOMS_DOWNLOAD_DIR is pinned OUTSIDE the repository below, so `store_check`'s scan for a
#     `mongod`-stemmed filename can never meet one in the tree. That is a property here, not a
#     habit that happens to hold because a library's default is currently kind.
#
# This is a measurement, not a gate — it needs a MongoDB binary and a network on first run, so it
# is deliberately not in `make verify`. C6.2's gate, which runs the same suites against
# @tempest/docstore, is the one that becomes permanent.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA="$ROOT/packages/platform/data"
LOG="${1:-/tmp/c6-control.log}"

# Pinned, so the control is a fixed point. Without this the server version is whatever
# mongodb-memory-server resolves TODAY, and the recorded baseline ("MongoDB 8.2.6") could move
# under a later run with no diff to this file — a control that can drift is not a control.
export MONGOMS_VERSION="${MONGOMS_VERSION:-8.2.6}"

MONGOMS_DOWNLOAD_DIR="${MONGOMS_DOWNLOAD_DIR:-$HOME/.cache/mongodb-binaries}"
mkdir -p "$MONGOMS_DOWNLOAD_DIR"

# RESOLVE before comparing. A `case` against the raw value is a string test, and a string test
# is not a path test: `binaries`, `./mongo-bins`, `packages/../mongo-bins` and a symlink into the
# tree all sail past it and land a 147 MB SSPL binary inside the repository. `cd && pwd -P`
# resolves relative paths against the caller's cwd exactly as the library will, and follows
# symlinks, so the comparison is between two real absolute paths.
MONGOMS_DOWNLOAD_DIR="$(cd "$MONGOMS_DOWNLOAD_DIR" && pwd -P)"
export MONGOMS_DOWNLOAD_DIR
ROOT_REAL="$(cd "$ROOT" && pwd -P)"

case "$MONGOMS_DOWNLOAD_DIR" in
  "$ROOT_REAL"|"$ROOT_REAL"/*)
    echo "refusing: MONGOMS_DOWNLOAD_DIR resolves inside the repository." >&2
    echo "  given:    ${1:-\$MONGOMS_DOWNLOAD_DIR}" >&2
    echo "  resolves: $MONGOMS_DOWNLOAD_DIR" >&2
    echo "  repo:     $ROOT_REAL" >&2
    echo "An SSPL server binary must never land in the tree — see L33 and store_check." >&2
    exit 2
    ;;
esac

echo "── C6.0 control: LibreChat's data-layer suites vs. real mongod ──"
echo "   binaries: $MONGOMS_DOWNLOAD_DIR"
echo "   log:      $LOG"

cd "$DATA"
set +e
npx jest --config tempest/jest.config.control.mjs --ci --coverage >"$LOG" 2>&1
CONTROL_EXIT=$?
set -e
echo "CONTROL_EXIT=$CONTROL_EXIT" >>"$LOG"

grep -E '^(Test Suites|Tests|Time):' "$LOG" || true
grep -E '^All files' "$LOG" || true
grep -o 'mongod-[a-z0-9]*-[a-z]*-[0-9.]*' "$LOG" | head -1 || true
echo "CONTROL_EXIT=$CONTROL_EXIT"
exit "$CONTROL_EXIT"
