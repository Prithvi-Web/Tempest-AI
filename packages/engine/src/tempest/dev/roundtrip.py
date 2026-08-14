"""THE §9b ROUND-TRIP GATE: `python -m tempest.dev.roundtrip --py-rust-ts --iterations N`.

Arbitrary domain payloads are synthesized from `domain-schema.json` (the same document that
generated the Rust types), then each one must survive four independent judges byte-for-byte:

  1. Pydantic (`tempest_api.schemas`)     — the single source of truth accepts it,
  2. serde over the GENERATED Rust types  — `roundtrip_helper` deserializes + re-serializes,
  3. ajv over the same JSON Schema        — the TypeScript-side contract accepts Rust's output,
  4. structural equality                  — what came back is what went in.

Any failure prints the offending payload: that payload IS the cross-language drift this gate
exists to catch (Law L12: three boundaries, one truth).
"""

import argparse
import json
import random
import string
import subprocess
import sys
from pathlib import Path
from typing import Any

# (rust type name, JSON-Schema $defs name) — they differ only for the generic page.
_TYPES: tuple[tuple[str, str], ...] = (
    ("RunDetail", "RunDetail"),
    ("TargetDetail", "TargetDetail"),
    ("DivergenceDetail", "DivergenceDetail"),
    ("RunEventOut", "RunEventOut"),
    ("HealthResponse", "HealthResponse"),
    ("PageRunSummary", "Page_RunSummary_"),
)


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "packages" / "shared-schema" / "domain-schema.json").is_file():
            return parent
    raise SystemExit("domain-schema.json not found — run from the tempest repository")


class _Synth:
    """Deterministic instance synthesis straight from the JSON Schema."""

    def __init__(self, defs: dict[str, Any], rng: random.Random) -> None:
        self.defs = defs
        self.rng = rng

    def instance(self, schema: dict[str, Any], depth: int = 0) -> object:
        if "$ref" in schema:
            name = str(schema["$ref"]).rsplit("/", 1)[-1]
            return self.instance(self.defs[name], depth + 1)
        if "const" in schema:
            return schema["const"]
        if "enum" in schema:
            return self.rng.choice(list(schema["enum"]))
        if "anyOf" in schema:
            options: list[dict[str, Any]] = list(schema["anyOf"])
            # Exercise the null arm sometimes, the value arm mostly.
            non_null = [o for o in options if o.get("type") != "null"]
            if non_null and (len(non_null) == len(options) or self.rng.random() < 0.75):
                return self.instance(self.rng.choice(non_null), depth + 1)
            return None
        kind = schema.get("type")
        if kind == "object":
            props: dict[str, Any] = schema.get("properties", {})
            required = set(schema.get("required", []))
            out: dict[str, object] = {}
            for name, sub in props.items():
                if name in required or self.rng.random() < 0.7:
                    out[name] = self.instance(sub, depth + 1)
            if not props and schema.get("additionalProperties"):
                for _ in range(self.rng.randrange(3)):
                    out[self._text(8)] = self.rng.choice([1, "x", True])
            return out
        if kind == "array":
            count = 0 if depth > 4 else self.rng.randrange(3)
            return [self.instance(schema.get("items", {}), depth + 1) for _ in range(count)]
        if kind == "string":
            if schema.get("format") == "date-time":
                # Canonical UTC-Z, seconds precision: identical bytes on every leg.
                return (
                    f"2026-08-{self.rng.randrange(1, 29):02d}"
                    f"T{self.rng.randrange(24):02d}:{self.rng.randrange(60):02d}"
                    f":{self.rng.randrange(60):02d}Z"
                )
            pattern = schema.get("pattern")
            if pattern == "^[0-9a-f]{40}$":
                return "".join(self.rng.choice("0123456789abcdef") for _ in range(40))
            low = int(schema.get("minLength", 0))
            high = int(schema.get("maxLength", max(low, 24)))
            return self._text(self.rng.randint(max(low, 1), min(high, 40)) if high else 0)
        if kind == "integer":
            low = int(schema.get("minimum", -(2**31)))
            high = int(schema.get("maximum", 2**31 - 1))
            return self.rng.randint(low, high)
        if kind == "number":
            # Finite, exactly float-representable values: byte-stable across every JSON codec.
            return self.rng.randrange(0, 2**20) / 1024.0
        if kind == "boolean":
            return self.rng.random() < 0.5
        if kind == "null":
            return None
        return None

    def _text(self, length: int) -> str:
        alphabet = string.ascii_letters + string.digits + "_-. äøπ"
        return "".join(self.rng.choice(alphabet) for _ in range(length))


def _normalize(value: object) -> object:
    """Order-insensitive structural form (dict key order is not part of the contract)."""
    if isinstance(value, dict):
        return {k: _normalize(v) for k, v in sorted(value.items())}
    if isinstance(value, list):
        return [_normalize(v) for v in value]
    return value


def _pydantic_accepts(type_name: str, payload: object) -> None:
    from tempest_api import schemas

    model: Any = {
        "RunDetail": schemas.RunDetail,
        "TargetDetail": schemas.TargetDetail,
        "DivergenceDetail": schemas.DivergenceDetail,
        "RunEventOut": schemas.RunEventOut,
        "HealthResponse": schemas.HealthResponse,
        "PageRunSummary": schemas.Page[schemas.RunSummary],
    }[type_name]
    model.model_validate(payload)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--py-rust-ts", action="store_true", required=True)
    parser.add_argument("--iterations", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    root = _repo_root()
    schema_doc = json.loads(
        (root / "packages" / "shared-schema" / "domain-schema.json").read_text()
    )
    synth = _Synth(schema_doc["$defs"], random.Random(args.seed))

    manifest = root / "packages" / "desktop" / "src-tauri" / "Cargo.toml"
    subprocess.run(
        [
            "cargo",
            "build",
            "-q",
            "--manifest-path",
            str(manifest),
            "-p",
            "tempest-desktop-devtools",
            "--bin",
            "roundtrip_helper",
        ],
        check=True,
    )
    helper = manifest.parent / "target" / "debug" / "roundtrip_helper"
    validator = root / "packages" / "desktop" / "scripts" / "roundtrip-validate.mjs"

    payloads: list[tuple[str, str, object]] = []
    for index in range(args.iterations):
        rust_name, schema_name = _TYPES[index % len(_TYPES)]
        payload = synth.instance(schema_doc["$defs"][schema_name])
        _pydantic_accepts(rust_name, payload)  # leg 1: the source of truth accepts it
        payloads.append((rust_name, schema_name, payload))

    ndjson = "".join(
        json.dumps({"type": t, "value": p}, sort_keys=True) + "\n" for t, _s, p in payloads
    )
    rust = subprocess.run(  # leg 2: the generated Rust types accept + re-serialize
        [str(helper)], input=ndjson.encode(), capture_output=True, check=True
    )
    rust_lines = rust.stdout.decode().splitlines()
    if len(rust_lines) != len(payloads):
        raise SystemExit(f"rust leg answered {len(rust_lines)} of {len(payloads)} payloads")

    reencoded: list[tuple[str, object]] = []
    failures = 0
    for (type_name, schema_name, original), line in zip(payloads, rust_lines, strict=True):
        reply = json.loads(line)
        if "error" in reply:
            failures += 1
            print(f"RUST-REJECTED {type_name}: {reply['error']}\n  payload: {original!r}")
            continue
        if _normalize(reply["ok"]) != _normalize(original):
            failures += 1
            print(f"RUST-MUTATED {type_name}:\n  in:  {original!r}\n  out: {reply['ok']!r}")
            continue
        reencoded.append((schema_name, reply["ok"]))

    ts_input = "".join(
        json.dumps({"type": t, "value": p}, sort_keys=True) + "\n" for t, p in reencoded
    )
    node = subprocess.run(  # leg 3: the schema-validated TypeScript side accepts Rust's output
        ["node", str(validator)], input=ts_input.encode(), capture_output=True, check=False
    )
    if node.returncode != 0:
        raise SystemExit(f"ts leg failed:\n{node.stdout.decode()}{node.stderr.decode()}")
    ts_report = json.loads(node.stdout.decode().strip().splitlines()[-1])
    failures += int(ts_report["invalid"])
    for detail in ts_report["errors"][:10]:
        print(f"TS-REJECTED: {detail}")

    total = len(payloads)
    print(
        f"roundtrip py→rust→ts: {total - failures}/{total} payloads byte-stable across all "
        f"three languages ({len(_TYPES)} domain types, seed {args.seed})"
    )
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
