"""Re-export of the shared first-party fixture marker.

The implementation is `tempest.dev._first_party`, because the Phase 21/22/23 benchmark gates are
shipped dev tooling and a shipped module cannot import from the test tree — the same reasoning as
`helpers_fake_anthropic`. Read that module for what the marker is and why writing it EMPTY cost
thirty-seven Linux CI failures (ADR-0058, trap 56).
"""

from tempest.dev._first_party import mark_first_party

__all__ = ["mark_first_party"]
