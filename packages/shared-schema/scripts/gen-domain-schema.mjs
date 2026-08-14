// Boundary A input (CLAUDE.md §9b): extract the OpenAPI component schemas — already JSON
// Schema 2020-12 under OpenAPI 3.1 — into one deterministic $defs document that `cargo typify`
// compiles to packages/desktop/src-tauri/src/generated/domain.rs. Pydantic stays the single
// source of truth; this file only re-roots the refs.
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const spec = JSON.parse(readFileSync(join(here, "..", "openapi.json"), "utf8"));

// Multipart upload body is CLI/CI surface, not desktop domain — binary formats stay out.
const EXCLUDE = new Set(["Body_uploadRunBundle"]);

const rewriteRefs = (node) => {
  if (Array.isArray(node)) return node.map(rewriteRefs);
  if (node && typeof node === "object") {
    const out = {};
    for (const [key, value] of Object.entries(node)) {
      out[key] =
        key === "$ref" && typeof value === "string"
          ? value.replace("#/components/schemas/", "#/$defs/")
          : rewriteRefs(value);
    }
    // Desktop boundary decision: every integer here is a local SQLite id or a per-run count —
    // int32 bounds make typify emit i32/u32, which cross to TypeScript as `number` without
    // BigInt precision hazards. A `minimum` of 1+ would become NonZeroU64 (a BigInt type), so
    // positivity constraints stay where they are enforced — in the Pydantic source of truth —
    // and the boundary type stays structural.
    if (out.type === "integer") {
      if (typeof out.exclusiveMinimum === "number" || out.minimum >= 1) {
        delete out.minimum;
        delete out.exclusiveMinimum;
      }
      out.minimum ??= -2147483648;
      out.maximum ??= 2147483647;
    }
    return out;
  }
  return node;
};

const defs = {};
for (const [name, schema] of Object.entries(spec.components.schemas)) {
  if (!EXCLUDE.has(name)) defs[name] = rewriteRefs(schema);
}

const sortDeep = (node) => {
  if (Array.isArray(node)) return node.map(sortDeep);
  if (node && typeof node === "object") {
    return Object.fromEntries(
      Object.keys(node)
        .sort()
        .map((key) => [key, sortDeep(node[key])]),
    );
  }
  return node;
};

const document = sortDeep({
  $schema: "https://json-schema.org/draft/2020-12/schema",
  title: "TempestDomain",
  description: "Generated from openapi.json — do not edit; run `make gen-contracts`.",
  type: "object",
  additionalProperties: false,
  $defs: defs,
});

const target = join(here, "..", "domain-schema.json");
writeFileSync(target, JSON.stringify(document, null, 2) + "\n");
console.log(`gen-domain-schema: ${Object.keys(defs).length} schemas -> domain-schema.json`);
