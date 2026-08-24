#!/usr/bin/env bash
# Build the tempest-server sidecar (PyInstaller ONEFILE — see tempest-server.spec for why)
# and stage it where the Tauri shell's externalBin contract expects it:
#   packages/desktop/src-tauri/binaries/tempest-server-<triple>   (a single executable file)
# Requires uv and a synced workspace; run from anywhere.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../.."
export PATH="$HOME/.local/bin:$PATH"

case "$(uname -m)" in
  arm64)  TRIPLE="aarch64-apple-darwin" ;;
  x86_64) TRIPLE="x86_64-apple-darwin" ;;
  *) echo "unsupported architecture: $(uname -m)" >&2; exit 1 ;;
esac
NAME="tempest-server-$TRIPLE"

rm -rf "packages/desktop/dist/$NAME"   # a stale ONEDIR directory here would shadow the new file
uv run pyinstaller --noconfirm \
  --distpath packages/desktop/dist \
  --workpath packages/desktop/build \
  packages/desktop/tempest-server.spec

DEST="packages/desktop/src-tauri/binaries"
mkdir -p "$DEST"
rm -rf "${DEST:?}/$NAME"
cp "packages/desktop/dist/$NAME" "$DEST/$NAME"

# Fast sanity (arg parsing + one full self-extraction of the frozen bundle); the deeper
# proof — health, ingest, and a frozen-worker local prove — is the API smoke test.
"$DEST/$NAME" --help >/dev/null

# …and one thing --help cannot see: DATA files resolve inside the bundle.
#
# The engine reads the committed boundary-D manifest at runtime. Nothing in the source tree
# notices when it is missing from the frozen bundle — the repo, the e2e harness and both 100%
# coverage gates all run from the checkout — so the app shipped with `listAgentTools`
# answering FileNotFoundError: an EMPTY Tool Library in the builder, and a failure at the top
# of every tool-bearing agent turn. The whole C5 surface was dark in the binary while every
# gate was green.
#
# Loading the manifest THROUGH the frozen binary is the cheapest check that could have caught
# it, so it runs here, on every build, before anything is staged for the shell.
"$DEST/$NAME" --print-tool-manifest >/dev/null || {
  echo "FATAL: the frozen sidecar cannot read its own tool manifest — boundary D's" >&2
  echo "artifacts are missing from the bundle (see \`datas\` in tempest-server.spec)." >&2
  exit 1
}

echo "sidecar staged: $DEST/$NAME ($(du -h "$DEST/$NAME" | cut -f1))"
