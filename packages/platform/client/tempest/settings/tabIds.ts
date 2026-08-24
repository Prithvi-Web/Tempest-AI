/**
 * The two tabs Tempest adds to the app's ONE settings home (ADR-0082).
 *
 * Deliberately a module with NO imports. The vendored `Nav/Settings/types.ts` widens its
 * `SettingsTab` union with the type below, and the seam's own manifest reads the same
 * constants — a shared identity that both sides can name without either importing the other's
 * values. Anything richer here (the icons, the labels, the panels) lives in `tabs.tsx`, which
 * may import freely because nothing type-level depends on it.
 *
 * The `tempest-` prefix is not decoration: upstream's tab ids come from `SettingsTabValues`,
 * an enum in the vendored data-provider, and a new value there would be an edit to a package
 * whose whole purpose is to be mergeable. These ids are strings the Radix `Tabs` root routes
 * on exactly like upstream's, and they cannot collide with a value upstream adds later.
 */

/** Local models and provider keys — how the assistant thinks, in one place. */
export const TEMPEST_MODELS_TAB = "tempest-models";

/** The proof engine's own settings: evidence storage, team sync, editor runners, privacy. */
export const TEMPEST_ENGINE_TAB = "tempest-engine";

export type TempestSettingsTab = typeof TEMPEST_MODELS_TAB | typeof TEMPEST_ENGINE_TAB;

/** Every tab this seam contributes, for the exhaustiveness the dialog's tests read. */
export const TEMPEST_SETTINGS_TAB_IDS: readonly TempestSettingsTab[] = [
  TEMPEST_MODELS_TAB,
  TEMPEST_ENGINE_TAB,
];
