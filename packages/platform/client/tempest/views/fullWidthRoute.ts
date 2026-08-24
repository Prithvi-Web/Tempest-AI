/**
 * Which routes own the whole window (ADR-0084).
 *
 * The owner's diagnosis was "it seems like two different apps", and the most literal cause was
 * on screen the whole time: standing in the proof surface, the window carried THREE columns of
 * navigation — the app's icon rail, the app's conversations panel showing "Projects / Chats",
 * and the proof surface's own sidebar. The middle one was dead space. Nothing in it applied to
 * what the user was looking at, and it was the widest of the three.
 *
 * Upstream already had the answer and applied it to exactly one route: `/insights` collapses
 * the conversations panel because insights owns the space. The proof surface owns the space in
 * the same way and for the same reason, so it joins the rule rather than getting a new one.
 *
 * A module of its own because three vendored call sites ask the question, and a predicate
 * copied three times is a predicate that will disagree with itself.
 */

import { TEMPEST_BASE } from "./routes";

/** True when the proof surface is what fills the window. */
export function isTempestRoute(pathname: string): boolean {
  return pathname === TEMPEST_BASE || pathname.startsWith(`${TEMPEST_BASE}/`);
}
