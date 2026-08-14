"""Emit the OpenAPI document deterministically (sorted keys, stable separators, trailing newline).

Step 1 of the `pnpm gen:api` zero-drift pipeline (CLAUDE.md §9). Determinism matters: the file is
committed, and CI fails on any diff — so identical schemas must serialize to identical bytes.
"""

import json
import sys
from pathlib import Path

from tempest_api.app import create_app


def dump(out_path: Path) -> None:
    spec = create_app().openapi()
    out_path.write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    dump(Path(sys.argv[1]))
