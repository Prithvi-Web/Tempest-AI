"""Re-export of the shared loopback model peers.

The implementation is `tempest.dev._fake_peer`, because the Phase 21 benchmark gates are shipped
dev tooling and a shipped module cannot import from the test tree. Kept as a thin alias so the
existing `from ..helpers_fake_anthropic import ...` in every test still reads naturally.
"""

from tempest.dev._fake_peer import (
    FakeAnthropic,
    FakeOpenAI,
    fake_anthropic_server,
    fake_openai_server,
)

__all__ = ["FakeAnthropic", "FakeOpenAI", "fake_anthropic_server", "fake_openai_server"]
