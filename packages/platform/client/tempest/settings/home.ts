/**
 * The one settings home, addressable from anywhere (ADR-0082).
 *
 * The owner's requirement, in their words: *"i want the settings of the tempest tool and the
 * Tempest AI to also be fully integrated into one spot."* One spot means one dialog — the
 * app's own settings, which is already searchable, already localised, and already where a
 * person looks. What was missing was a way to ASK for it: upstream opens it from a `useState`
 * inside `AccountSettings.tsx`, so the rail, an error message, and the proof surface had no
 * way to say "open settings, on that tab".
 *
 * This module is that way. A request is a value in a Jotai atom — non-null means "the home
 * should be open, on this tab" — written by anyone and read by the two vendored files that
 * own the dialog's open state and its active tab. Two one-line deltas instead of threading a
 * prop through three components (`UPSTREAM.md`).
 *
 * `getDefaultStore()` rather than a hook for the writer, on purpose: the callers are a nav
 * link's `onClick` and a `<Link>`'s handler, neither of which is a component that wants to
 * subscribe to this state. Jotai's default store is the one a `Provider`-less tree already
 * uses, which is what this client is.
 */

import { atom, getDefaultStore, useAtomValue } from "jotai";

import type { TempestSettingsTab } from "./tabIds";

/** A live request to show the settings home, or `null` when nobody has asked. */
export type SettingsHomeRequest = { readonly tab: TempestSettingsTab } | null;

export const settingsHomeAtom = atom<SettingsHomeRequest>(null);

/** Ask for the settings home, on this tab. Idempotent; safe from any event handler. */
export function openSettingsHome(tab: TempestSettingsTab): void {
  getDefaultStore().set(settingsHomeAtom, { tab });
}

/**
 * Withdraw the request — called when the dialog closes, whichever way it was opened.
 *
 * Without this, a request would outlive its dialog: the next person to open settings from the
 * account menu would land on the tab someone asked for minutes ago, which is a small, baffling
 * bug of exactly the kind that makes software feel haunted.
 */
export function closeSettingsHome(): void {
  getDefaultStore().set(settingsHomeAtom, null);
}

/** The live request, for the dialog's active-tab effect. */
export function useSettingsHomeRequest(): SettingsHomeRequest {
  return useAtomValue(settingsHomeAtom);
}

/** Whether something has asked for the home to be open. */
export function useSettingsHomeOpen(): boolean {
  return useAtomValue(settingsHomeAtom) !== null;
}
