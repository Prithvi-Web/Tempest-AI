/**
 * The settings-home manifest (ADR-0082) — the net that holds the contract the vendored `tsc`
 * cannot.
 *
 * The seam declares its own copies of upstream's `TabMeta`/`SettingEntry` shapes rather than
 * importing them, because one `import type` from `client/src` drags a tree whose own tsc is
 * RED at baseline into the seam's project and destroys the only type signal this surface has
 * (`tabs.tsx` says so at length). That decision buys a green gate and owes three checks in
 * return — the same three upstream's own `registry.spec.ts` makes over its registry:
 *
 *   1. every `labelKey` exists in the English locale (upstream: `expect(en).toHaveProperty`)
 *   2. every entry names a section its tab actually declares
 *   3. ids are unique
 *
 * Plus two this seam owes specifically: the section ids the seam uses must be the ones
 * `Nav/Settings/types.ts` widened `SectionId` with, and the tab ids must be the ones it
 * widened `SettingsTab` with. Both are read out of the vendored source as TEXT — deliberately,
 * because reading them as types is the thing that cannot be done here.
 */
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import {
  TEMPEST_ENGINE_TAB,
  TEMPEST_MODELS_TAB,
  TEMPEST_SETTINGS_TAB_IDS,
} from "../../platform/client/tempest/settings/tabIds";
import {
  TEMPEST_SETTINGS_ENTRIES,
  TEMPEST_SETTINGS_TABS,
} from "../../platform/client/tempest/settings/tabs";

const CLIENT = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
  "..",
  "platform",
  "client",
);

const locale = JSON.parse(
  readFileSync(path.join(CLIENT, "src/locales/en/translation.json"), "utf8"),
) as Record<string, string>;

const vendoredTypes = readFileSync(
  path.join(CLIENT, "src/components/Nav/Settings/types.ts"),
  "utf8",
);
const vendoredRegistry = readFileSync(
  path.join(CLIENT, "src/components/Nav/Settings/registry.tsx"),
  "utf8",
);

describe("the settings home's Tempest manifest", () => {
  it("names a real English string for every tab, section and entry", () => {
    for (const tab of TEMPEST_SETTINGS_TABS) {
      expect(locale, `tab ${tab.id}`).toHaveProperty(tab.labelKey);
      for (const section of tab.sections) {
        expect(locale, `section ${section.id}`).toHaveProperty(section.labelKey);
      }
    }
    for (const entry of TEMPEST_SETTINGS_ENTRIES) {
      expect(locale, `entry ${entry.id}`).toHaveProperty(entry.labelKey);
    }
  });

  it("puts every entry in a section its own tab declares", () => {
    const declared = new Map(
      TEMPEST_SETTINGS_TABS.map((tab) => [tab.id, new Set(tab.sections.map((s) => s.id))]),
    );
    for (const entry of TEMPEST_SETTINGS_ENTRIES) {
      const sections = declared.get(entry.tab);
      expect(sections, `entry ${entry.id} names tab ${entry.tab}`).toBeDefined();
      expect(sections?.has(entry.section), `entry ${entry.id} → ${entry.section}`).toBe(true);
    }
  });

  it("has unique ids, and does not collide with an upstream entry id", () => {
    const ids = TEMPEST_SETTINGS_ENTRIES.map((e) => e.id);
    expect(new Set(ids).size).toBe(ids.length);
    // Upstream's own entry ids, read as text. A collision would silently shadow one of theirs
    // in a `find`-by-id, and the registry is one flat array once the seam is spread into it.
    const upstream = [...vendoredRegistry.matchAll(/^\s{4}id: '([^']+)',$/gm)].map((m) => m[1]);
    expect(upstream.length).toBeGreaterThan(20); // the regex still matches something
    const ours = new Set(ids);
    // The three provider-key entries are upstream's, re-addressed rather than re-declared.
    expect([...ours].filter((id) => upstream.includes(id))).toEqual([]);
  });

  it("uses exactly the section ids the vendored SectionId union was widened with", () => {
    const used = new Set(
      TEMPEST_SETTINGS_TABS.flatMap((tab) => tab.sections.map((section) => section.id)),
    );
    for (const id of used) {
      expect(
        vendoredTypes.includes(`| '${id}'`),
        `SectionId in Nav/Settings/types.ts is missing '${id}'`,
      ).toBe(true);
    }
    // And the three moved provider-key entries point at a section this seam declares.
    expect(used.has("tempestProviderKeys")).toBe(true);
    expect(vendoredRegistry).toContain("section: 'tempestProviderKeys'");
  });

  it("declares every tab id the seam exports, and the vendored union carries them", () => {
    expect(TEMPEST_SETTINGS_TABS.map((t) => t.id).sort()).toEqual(
      [...TEMPEST_SETTINGS_TAB_IDS].sort(),
    );
    expect(vendoredTypes).toContain("TempestSettingsTab");
    expect(vendoredTypes).toContain("...TEMPEST_SETTINGS_TABS");
    expect(vendoredRegistry).toContain("...TEMPEST_SETTINGS_ENTRIES");
  });

  it("keeps local models and provider keys in ONE tab — the owner's requirement", () => {
    const modelsTabEntries = TEMPEST_SETTINGS_ENTRIES.filter((e) => e.tab === TEMPEST_MODELS_TAB);
    expect(modelsTabEntries.map((e) => e.id)).toContain("tempestLocalModels");
    // Upstream's provider keys were re-addressed into the same tab, by name.
    for (const id of ["providerApiKeys", "agentApiKeys", "revokeKeys"]) {
      const block = vendoredRegistry.slice(vendoredRegistry.indexOf(`id: '${id}'`));
      expect(block.slice(0, 220), `${id} moved to the Models tab`).toContain(
        "tab: TEMPEST_MODELS_TAB",
      );
    }
    expect(TEMPEST_SETTINGS_ENTRIES.some((e) => e.tab === TEMPEST_ENGINE_TAB)).toBe(true);
  });

  it("loads every panel lazily, so the tauri bindings stay out of the main chunk", () => {
    // `registry.tsx` is in the client's MAIN bundle and these panels reach the host through
    // `views/hooks.ts`. A static import would put `@tauri-apps/api` into every build,
    // including the browser harness and server mode — the trap `streamHost.ts` documents.
    const source = readFileSync(
      path.join(CLIENT, "tempest/settings/tabs.tsx"),
      "utf8",
    );
    expect(source).not.toMatch(/^import .*from "\.\/(ModelsPanel|EngineKeyPanel|EnginePanels)"/m);
    for (const module of ["./ModelsPanel", "./EngineKeyPanel", "./EnginePanels"]) {
      expect(source).toContain(`import("${module}")`);
    }
  });
});
