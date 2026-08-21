"""Making a fixture repository first-party — and proving that it took.

TWO conditions select the trusted ProcessSandbox for a repository (ADR-0008): `TEMPEST_DEV=1` in
the environment, AND a `.tempest-first-party` file whose CONTENTS equal `FIRST_PARTY_MARKER`.
Creating that file and leaving it EMPTY satisfies neither — `select_sandbox_for_repo` falls
straight through to the user-repo tier ladder, and the ladder fails DIFFERENTLY on every machine:
macOS hands it T2 Seatbelt, which works (green, under a backend the fixture never chose); an
ubuntu CI runner hands it T1 Docker, whose `tempest-sandbox:latest` image nothing in this
repository builds, so the container never starts and nothing executes; a machine with neither is
refused outright by Law L6. Only the first of those three is quiet.

Eleven fixture builders did exactly that: six integration modules and the five gate harnesses in
this package. The tests were green on the author's Mac for twelve commits and produced
thirty-seven failures the first time they ran on Linux, every one of them a verdict of `UNPROVEN`
with an empty divergence list (ADR-0058, trap 56).

So this does not merely write the marker: it CHECKS that the repository it was handed now selects
the backend the caller is claiming for it, and refuses loudly on every platform if it does not. A
fixture that does not establish the condition it names is measuring something else (trap 47), and
"it passed on my machine" is exactly the report that mistake produces.

It lives here, in shipped dev tooling, rather than in the test tree, for the same reason
`_fake_peer` does: the gate harnesses are shipped modules and a shipped module cannot import from
the tests. `packages/engine/tests/helpers_first_party.py` is a thin alias over this.
"""

from __future__ import annotations

from pathlib import Path

from tempest.prove import FIRST_PARTY_MARKER, select_sandbox_for_repo

MARKER_FILENAME = ".tempest-first-party"


def mark_first_party(repo: Path) -> None:
    """Mark `repo` as our own code, and refuse to continue if the selection did not change.

    The caller supplies the other half of the condition — `TEMPEST_DEV=1` — which every caller
    does explicitly rather than inheriting it from whatever the ambient shell happened to export.
    """
    (repo / MARKER_FILENAME).write_text(FIRST_PARTY_MARKER, encoding="utf-8")
    selection = select_sandbox_for_repo(repo)
    if selection.kind != "process-first-party":
        raise RuntimeError(
            f"{repo} is NOT first-party: the tier ladder chose {selection.kind!r} "
            f"(tier {selection.tier!r}). Wherever a tier happens to exist this still runs while "
            f"measuring the wrong backend; where none exists every verdict becomes "
            f"UNPROVEN(SANDBOX_UNAVAILABLE). Check the marker contents and TEMPEST_DEV=1."
        )
