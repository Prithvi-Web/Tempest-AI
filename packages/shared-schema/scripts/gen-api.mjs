#!/usr/bin/env node
/**
 * The zero-drift generation pipeline, schema half (CLAUDE.md §9/§9b). Run as `pnpm gen:api`
 * from the root; `make gen-contracts` runs it before the Rust/TS boundary generators.
 *
 *   1. FastAPI (Pydantic schemas) → packages/shared-schema/openapi.json
 *   2. openapi-typescript          → packages/shared-schema/types.ts
 *
 * Downstream (driven by `make gen-contracts`):
 *   3. gen-domain-schema.mjs       → packages/shared-schema/domain-schema.json
 *   4. cargo typify                → packages/desktop/src-tauri/src/generated/domain.rs
 *   5. tauri-specta                → packages/desktop/src/generated/bindings.ts
 *
 * Every output is committed; CI fails on any diff. Determinism is a feature: identical schemas
 * must produce identical bytes. (The Next.js web outputs died with the web package — ADR-0014.)
 */
import { execFileSync } from "node:child_process";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const schemaDir = join(root, "packages/shared-schema");

const run = (cmd, args, cwd = root) =>
  execFileSync(cmd, args, { cwd, stdio: ["ignore", "inherit", "inherit"] });

// 1. Pydantic → openapi.json (deterministic: sorted keys, trailing newline)
run("uv", ["run", "python", "-m", "tempest_api.dev.dump_openapi", join(schemaDir, "openapi.json")]);

// 2. openapi.json → types.ts
run("pnpm", [
  "--filter",
  "@tempest/shared-schema",
  "exec",
  "openapi-typescript",
  "openapi.json",
  "-o",
  "types.ts",
]);

console.log("gen:api: openapi.json + types.ts regenerated");
