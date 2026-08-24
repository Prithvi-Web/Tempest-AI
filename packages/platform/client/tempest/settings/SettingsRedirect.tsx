/**
 * `/tempest/settings` — kept as a DEEP LINK into the one settings home, not as a second one
 * (ADR-0082).
 *
 * The proof surface used to carry its own settings page. It does not any more: the owner's
 * requirement is one spot, and the app's own settings dialog is that spot. This route stays
 * because a URL that used to work should keep working — bookmarks, the e2e suite, and every
 * link written before the move — and because "one home" is a claim about homes, not about
 * doors. It opens the home on the proof-engine tab and sends the view back to the runs list,
 * which is where the person was going anyway.
 *
 * `replace` on the redirect, so Back does not bounce the user straight back here.
 */

import { useEffect } from "react";
import { Navigate } from "react-router-dom";

import { runsPath } from "../views/routes";
import { openSettingsHome } from "./home";
import { TEMPEST_ENGINE_TAB } from "./tabIds";

export default function SettingsRedirect(): JSX.Element {
  useEffect(() => {
    openSettingsHome(TEMPEST_ENGINE_TAB);
  }, []);
  return <Navigate to={runsPath()} replace />;
}
