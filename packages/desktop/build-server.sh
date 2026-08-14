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

# Fast sanity only (arg parsing + one full self-extraction of the frozen bundle); the real
# proof — health, ingest, and a frozen-worker local prove — is the API smoke test.
"$DEST/$NAME" --help >/dev/null

echo "sidecar staged: $DEST/$NAME ($(du -h "$DEST/$NAME" | cut -f1))"
