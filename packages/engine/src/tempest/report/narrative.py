"""AI divergence narratives (ADR-0029, HANDOFF-WORLD-CLASS 2.4) — evidence, made readable.

The model receives ONLY the already-recorded evidence for one divergence (target identity,
divergence class, the minimized input, and both observed outcomes) and writes a short
plain-English explanation of what changed. Hard lines, each pinned by test:

- The verdict NEVER depends on this. Narration runs after every verdict and every repro is
  final; a narrative failure degrades to None, silently and safely — absence of prose is
  not absence of evidence.
- Every surface labels it "AI narrative" — a model's reading of the evidence, never the
  evidence itself.
- Keyless runs skip entirely (no key → None, zero egress — the L10 posture is identical to
  ADR-0024's synthesis rung, sharing its kill switch and BYOK env).
"""

import os

_MODEL_ENV = "TEMPEST_SYNTHESIS_MODEL"
_BASE_URL_ENV = "TEMPEST_SYNTHESIS_BASE_URL"
_DEFAULT_MODEL = "claude-sonnet-5"
_MAX_NARRATIVE_TOKENS = 300

_SYSTEM_PROMPT = (
    "You explain code-behavior evidence to developers. Given one input and the observed "
    "behavior of two revisions of the same function, explain in 2-3 plain sentences what "
    "changed for a reader who has not seen the code. State only what the evidence shows — "
    "no speculation about intent, no judgment about whether the change is good or bad, no "
    "recommendations. Output the sentences only."
)


def narratives_enabled() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY")) and (
        os.environ.get("TEMPEST_NO_SYNTHESIS") != "1"
    )


def narrate_divergence(
    *,
    symbol: str,
    divergence_class: str,
    args_literal: str,
    kwargs_literal: str,
    base_summary: str,
    head_summary: str,
) -> str | None:
    """Plain English from the evidence, or None (keyless, disabled, or any API failure)."""
    if not narratives_enabled():
        return None
    import anthropic

    client = anthropic.Anthropic(
        base_url=os.environ.get(_BASE_URL_ENV) or None,
        max_retries=1,
        timeout=30.0,
    )
    try:
        response = client.messages.create(
            model=os.environ.get(_MODEL_ENV, _DEFAULT_MODEL),
            max_tokens=_MAX_NARRATIVE_TOKENS,
            system=_SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Function: `{symbol}`\n"
                        f"Divergence class: {divergence_class}\n"
                        f"Input: args={args_literal} kwargs={kwargs_literal}\n"
                        f"Old revision observed: {base_summary}\n"
                        f"New revision observed: {head_summary}\n"
                    ),
                }
            ],
        )
    except anthropic.APIError:
        return None  # readability must never take a run down — the evidence stands alone
    text = "".join(block.text for block in response.content if block.type == "text").strip()
    return text or None
