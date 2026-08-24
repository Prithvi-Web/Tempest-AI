/**
 * Whether an in-band error carries the "you could run a local model instead" remedy
 * (ADR-0080 §8).
 *
 * The contract half of this shipped and the UI half did not. `inference/client.py` gives
 * `MissingKey` a `remedy` field, `chatwire.error_content_part` carries it into the message the
 * client renders, and **nothing read it** — so a user told "no API key for Anthropic" was not
 * told the thing that makes this app different, which is that it can run a model with no key
 * at all. An ADR that describes an affordance nobody built is worse than one that defers it.
 *
 * **Why a field and not a string match.** The alternative is the client testing the error
 * PROSE for "no API key", which breaks the moment the prose improves — and improving error
 * prose is something this repository does deliberately and often. The remedy is a value, so
 * the branch is on the value.
 *
 * The predicate takes `unknown` on purpose. Its caller is `Part.tsx`, a VENDORED file, and
 * `TMessageContentParts` has no `remedy` member — reading one there would need either a cast
 * in upstream's code or a change to upstream's type, and neither belongs in a vendored file
 * for one field. The narrowing lives here, in the seam, where `make verify` typechecks it and
 * the vitest gate measures it.
 */

/** The one remedy that exists today. A union the day there is a second (client.py says so). */
export const LOCAL_MODEL_REMEDY = "local-model";

/**
 * True when this content part carries the local-model remedy.
 *
 * Structural, not a cast: an unknown value is checked for the exact shape before it is read,
 * so a frame that changes shape underneath this returns false rather than throwing inside a
 * message renderer — where an exception costs the user the whole conversation view.
 */
export function hasLocalModelRemedy(part: unknown): boolean {
  if (typeof part !== "object" || part === null) return false;
  const remedy = (part as { remedy?: unknown }).remedy;
  return remedy === LOCAL_MODEL_REMEDY;
}
