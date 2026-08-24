/** Byte and size wording shared by the settings panels (ADR-0082).
 *
 * Lifted verbatim from `views/SettingsView.tsx` when those panels moved into the app's one
 * settings home, and put in a module of its own because two panels now need them and a copy
 * in each is how two panels start disagreeing about what a gigabyte is.
 */

const MIB = 1024 * 1024;

/** The bundle-budget slider's stops, in MiB. Index 0 is "unlimited". */
export const BUDGET_STEPS_MIB = [0, 100, 250, 500, 1000, 2000] as const;

/** The slider position for a stored budget: the first step that covers it, or the top step
 * when a hand-edited file (or an environment override) asks for more than the slider offers. */
export function budgetIndex(bytes: number): number {
  const mib = Math.round(bytes / MIB);
  const found = BUDGET_STEPS_MIB.findIndex((step) => step >= mib);
  return found === -1 ? BUDGET_STEPS_MIB.length - 1 : found;
}

export function budgetBytesAt(index: number): number {
  return (BUDGET_STEPS_MIB[index] ?? 0) * MIB;
}

export function bytesLabel(bytes: number): string {
  if (bytes < 1024) return `${bytes} bytes`;
  if (bytes < MIB) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * MIB) return `${(bytes / MIB).toFixed(1)} MB`;
  return `${(bytes / (1024 * MIB)).toFixed(2)} GB`;
}

/** Bytes as a person reads them, for model sizes. `sizeBytes` arrives as `number | null`
 * because specta maps an f64 that way (JSON cannot carry NaN); it is never actually null,
 * and `?? 0` costs less than a 4.29 GB ceiling waiting to overflow in a `u32`. */
export function gb(bytes: number | null): string {
  return `${((bytes ?? 0) / 1e9).toFixed(1)} GB`;
}

/** The environment variable forcing a field, or null. A setting the process ENVIRONMENT is
 * forcing is shown as forced — a toggle that silently disagrees with reality is a lie. */
export function forcedBy(
  overrides: readonly { field: string; variable: string }[],
  field: string,
): string | null {
  return overrides.find((o) => o.field === field)?.variable ?? null;
}
