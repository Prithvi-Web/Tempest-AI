/**
 * The "Get a local model" affordance, rendered beside the keyless-turn error it answers
 * (ADR-0080 §8). The decision to show it is `hasLocalModelRemedy` in `remedy.ts`, which the
 * vitest gate measures; this file is the markup, e2e-pinned like every other view.
 *
 * The two files are NOT named as a case pair. `localModelRemedy.ts` beside
 * `LocalModelRemedy.tsx` resolves to whichever the filesystem feels like on macOS, and the
 * client build failed on exactly that — the bundler took the `.ts` and reported the component
 * as a missing export.
 *
 * **Styled with the vendored client's own utilities, not the seam stylesheet.** This is the
 * one Tempest component that renders inside the CHAT surface, and `tempest-views.css` (with
 * `theme.css` behind it) loads with the absorbed subtree's lazy chunk — so a class from there
 * would be unstyled for any user who had not yet opened the proof surface. The tokens used
 * here (`text-text-secondary`, `decoration-border-medium`) are upstream's, which is also what
 * keeps this looking like part of the message rather than an insert.
 *
 * L31 note: this is an affordance, not evidence. It carries none of the verdict vocabulary,
 * none of the verdict colours, and renders below the error text as ordinary interface.
 */

import { openSettingsHome } from "../settings/home";
import { TEMPEST_MODELS_TAB } from "../settings/tabIds";

export { hasLocalModelRemedy } from "./remedy";

/**
 * A BUTTON, not a link (ADR-0082).
 *
 * It used to navigate to `/tempest/settings`, which took a user who had just been told "no
 * API key" out of the conversation they were reading and into a different surface. The models
 * panel now lives in the app's one settings home, so the remedy opens that home on its Models
 * tab — over the conversation, which stays exactly where it was.
 */
export function LocalModelRemedy(): JSX.Element {
  return (
    <p className="my-2 text-sm text-text-secondary" data-testid="local-model-remedy">
      <button
        type="button"
        data-testid="local-model-remedy-link"
        onClick={() => openSettingsHome(TEMPEST_MODELS_TAB)}
        className="font-medium text-text-primary underline decoration-border-medium underline-offset-2 transition-colors hover:text-text-secondary"
      >
        Get a local model
      </button>{" "}
      — free, openly licensed, and no key needed. It runs on this machine and keeps working
      with the network unplugged.
    </p>
  );
}
