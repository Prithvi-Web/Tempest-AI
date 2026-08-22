/**
 * Phase 20.3b — a completion source that needs no model and no network.
 *
 * F11 promises "local-model capable (offline, air-gapped)". The model runner is 20.3c; this is
 * the source that works before it and remains the fallback after it, because a completion engine
 * that can only answer when a model is loaded is one that stops working on a plane.
 *
 * It suggests the rest of an identifier the FILE already contains. That is a real, deterministic
 * completion rather than a placeholder pretending to be intelligence — and being deterministic
 * is what lets the §5 completion budget be measured honestly before any model exists.
 */

/** Identifier characters, deliberately conservative: letters, digits, underscore, dollar. */
const WORD = /[A-Za-z0-9_$]+/g;

/** The identifier prefix immediately before the cursor, or "" when the cursor is not in one. */
export function prefixAt(textBeforeCursor: string): string {
  const match = /[A-Za-z_$][A-Za-z0-9_$]*$/.exec(textBeforeCursor);
  return match === null ? "" : match[0];
}

/**
 * Complete `prefix` from the identifiers in `document`.
 *
 * Ties break toward the identifier that occurs MOST often, then the shortest — a name the file
 * uses repeatedly is a better guess than one it mentions once, and a shorter completion is less
 * to undo when the guess is wrong.
 */
export function completeFromDocument(document: string, prefix: string): string {
  // A one-character prefix matches most of the file; suggesting from it is noise, not help.
  if (prefix.length < 2) return "";
  const counts = new Map<string, number>();
  for (const match of document.matchAll(WORD)) {
    const word = match[0];
    if (word.length > prefix.length && word.startsWith(prefix)) {
      counts.set(word, (counts.get(word) ?? 0) + 1);
    }
  }
  let best: string | null = null;
  let bestCount = 0;
  for (const [word, count] of counts) {
    if (best === null || count > bestCount || (count === bestCount && word.length < best.length)) {
      best = word;
      bestCount = count;
    }
  }
  return best === null ? "" : best.slice(prefix.length);
}

/** The `CompletionSource` shape the editor extension consumes. */
export async function documentCompletionSource(context: {
  textBeforeCursor: string;
  textAfterCursor: string;
}): Promise<string> {
  const prefix = prefixAt(context.textBeforeCursor);
  // The whole document, minus the prefix itself, is the corpus. Including the partially typed
  // word would let it complete itself with itself.
  const corpus =
    context.textBeforeCursor.slice(0, context.textBeforeCursor.length - prefix.length) +
    context.textAfterCursor;
  return completeFromDocument(corpus, prefix);
}
