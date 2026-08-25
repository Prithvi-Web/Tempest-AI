/**
 * The model-world query keys (ADR-0085) — the copy that must not drift.
 *
 * `ModelsPanel` invalidates the CLIENT's endpoints and models caches after the local model
 * server starts or stops. Those two keys belong to the vendored data-provider's `QueryKeys`
 * enum, and the seam writes them out as literals rather than importing them, because an
 * `import` from the vendored tree drags a baseline-red project into this seam's tsconfig
 * (`tabs.tsx` explains at length).
 *
 * That copy is only safe if something checks it. **A wrong key fails SILENTLY**:
 * `invalidateQueries` on a key nothing uses does nothing, and the symptom — a picker that
 * never notices a model appeared — is identical to not calling it at all. So this reads the
 * enum out of the provider package and asserts the two strings still agree with it.
 */
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import {
  ENDPOINTS_KEY,
  MODELS_KEY,
  MODEL_WORLD_KEYS,
} from "../../platform/client/tempest/settings/modelWorld";

const PROVIDER_KEYS = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
  "..",
  "platform",
  "provider",
  "src",
  "keys.ts",
);

/** `  models = 'models',` → { models: 'models' }, read out of upstream's own enum source. */
function upstreamQueryKeys(): Record<string, string> {
  const source = readFileSync(PROVIDER_KEYS, "utf8");
  const body = source.slice(source.indexOf("export enum QueryKeys {"));
  const out: Record<string, string> = {};
  for (const match of body.matchAll(/^\s{2}(\w+)\s*=\s*'([^']+)',$/gm)) {
    const [, name, value] = match;
    if (name !== undefined && value !== undefined) {
      out[name] = value;
    }
  }
  return out;
}

describe("the model-world query keys", () => {
  it("matches upstream's QueryKeys enum", () => {
    const keys = upstreamQueryKeys();
    // The parse itself is load-bearing: a regex that matched nothing would make every
    // assertion below vacuously pass against `undefined === undefined` (trap 60).
    expect(Object.keys(keys).length).toBeGreaterThan(10);
    expect(keys.endpoints).toBeDefined();
    expect(keys.models).toBeDefined();

    expect(ENDPOINTS_KEY).toBe(keys.endpoints);
    expect(MODELS_KEY).toBe(keys.models);
  });

  it("invalidates both halves of the model world, providers first", () => {
    expect([...MODEL_WORLD_KEYS]).toEqual([ENDPOINTS_KEY, MODELS_KEY]);
  });

  it("is actually used by the panel that serves a model", () => {
    // The keys being correct is worth nothing if nobody invalidates them. This is the other
    // half of the same claim, and it is the half that regressed into existence.
    const panel = readFileSync(
      path.resolve(
        path.dirname(fileURLToPath(import.meta.url)),
        "..",
        "..",
        "platform",
        "client",
        "tempest",
        "settings",
        "ModelsPanel.tsx",
      ),
      "utf8",
    );
    expect(panel).toContain("MODEL_WORLD_KEYS");
    expect(panel).toMatch(/for \(const key of MODEL_WORLD_KEYS\)/);
  });
});
