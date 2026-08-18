"""LLM constructor synthesis — the proof-rate lever (HANDOFF-WORLD-CLASS 2.1, ADR-0024).

An instance method is UNPROVEN(TARGET_UNREACHABLE) because nothing can construct its
receiver. When the user has configured their own Anthropic key (BYOK, ADR-0006), this
stage asks a model to write ONLY the missing piece: a module-level `adapter(...)` that
constructs the class deterministically and delegates to the method. The differential
runner still computes every verdict (non-goal #1: no LLM-authored verdicts, ever).

Honesty invariants:
- The adapter is accepted ONLY by real sandboxed execution on BASE (the same probe
  machinery as every deterministic adapter — `harness.synth.synthesize`). A failing
  adapter is `SYNTHESIS_DECLINED`, stated plainly, never silently degraded.
- Validated adapters are cached in the user's repo (`.tempest/adapters/`, keyed by the
  module source hash) so later runs replay OFFLINE (L8) — the key is needed once per
  target shape. Cache hits still re-validate by execution; the cache only ever saves the
  network call, never the proof.
- Egress: exactly one call surface, active only when `ANTHROPIC_API_KEY` is set and
  `TEMPEST_NO_SYNTHESIS` is not — the keyless egress gate stays at zero (L10).
- The adapter executes inside the run's sandbox tier like all harness code (L6), and the
  determinism gate (Law L3) rejects adapters that smuggle in nondeterminism.
"""

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path

from tempest.execute.sandbox import Sandbox
from tempest.harness.synth import SynthesisFailure, synthesize

_DEFAULT_MODEL = "claude-sonnet-5"
_MAX_ADAPTER_TOKENS = 2048
_CODE_FENCE = re.compile(r"```(?:python)?\s*\n(.*?)```", re.DOTALL)

_SYSTEM_PROMPT = (
    "You write test harness adapters for a differential execution engine. Given a Python "
    "module containing a class, write a NEW standalone module that makes one instance "
    "method invocable in isolation.\n"
    "Rules, all mandatory:\n"
    "- Define exactly one module-level function named `adapter` whose parameters mirror "
    "the target method's parameters (excluding `self`), with the same annotations.\n"
    "- Inside, construct the class with FIXED, deterministic constructor arguments (plain "
    "literals a typical caller would use), call the method, and return its result.\n"
    "- Import only from the target module and the standard library.\n"
    "- No randomness, no time, no network, no filesystem access, no global state.\n"
    "- Output ONLY the Python code for the module, in a single code block. No prose."
)


@dataclass(frozen=True)
class InstanceAdapter:
    """A model-written, execution-validated adapter, present in both worktrees."""

    module: str  # importable adapter module name, e.g. _tempest_adapter_ab12cd34
    qualname: str  # always "adapter"
    from_cache: bool


@dataclass(frozen=True)
class KeyCheck:
    """The result of the Settings "Test key" ping: valid or not, and why. Nothing is stored —
    the check is one request whose only product is this sentence."""

    ok: bool
    detail: str
    model: str | None


@dataclass(frozen=True)
class SynthesisDeclined:
    """The model was consulted but its adapter did not survive validation (or the call
    itself failed). Reported as UNPROVEN(SYNTHESIS_DECLINED) — never a lesser claim."""

    detail: str


def synthesis_enabled() -> bool:
    return (
        bool(os.environ.get("ANTHROPIC_API_KEY")) and os.environ.get("TEMPEST_NO_SYNTHESIS") != "1"
    )


def verify_key() -> KeyCheck:
    """One minimal live request on the SAME egress surface synthesis uses (§3.2).

    `max_tokens=1` and a single literal "ping" — no source, no repo name, no diff ever rides
    this call (L9). With no key configured nothing is sent at all.
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return KeyCheck(
            ok=False,
            detail="no API key is configured — add one above, then test it.",
            model=None,
        )
    import anthropic

    model = os.environ.get("TEMPEST_SYNTHESIS_MODEL", _DEFAULT_MODEL)
    client = anthropic.Anthropic(
        base_url=os.environ.get("TEMPEST_SYNTHESIS_BASE_URL") or None,
        max_retries=0,
        timeout=20.0,
    )
    try:
        client.messages.create(
            model=model,
            max_tokens=1,
            messages=[{"role": "user", "content": "ping"}],
        )
    except anthropic.APIError as err:
        return KeyCheck(
            ok=False,
            detail=f"the key was rejected or unreachable — {err.__class__.__name__}: {err}",
            model=None,
        )
    return KeyCheck(ok=True, detail=f"the key works — {model} answered.", model=model)


def remediation_hint() -> str:
    return (
        " Configure an Anthropic API key in Settings (or export ANTHROPIC_API_KEY) and "
        "Tempest will attempt AI constructor synthesis for this target."
    )


def synthesize_instance_adapter(
    *,
    cache_dir: Path,
    base_root: Path,
    head_root: Path,
    module: str,
    owner_class: str,
    method: str,
    head_source: str,
    sandbox: Sandbox,
    seed: int = 0,
) -> InstanceAdapter | SynthesisDeclined | None:
    """None = not attempted (no key or disabled) — the caller keeps its honest reason."""
    if not synthesis_enabled():
        return None

    shape_key = hashlib.sha256(
        f"{module}.{owner_class}.{method}\n{head_source}".encode()
    ).hexdigest()[:16]
    adapter_module = f"_tempest_adapter_{shape_key}"
    cache_file = cache_dir / f"{adapter_module}.py"

    from_cache = cache_file.exists()
    if from_cache:
        code = cache_file.read_text(encoding="utf-8")
    else:
        reply = _ask_model(module, owner_class, method, head_source)
        if isinstance(reply, SynthesisDeclined):
            return reply
        extracted = _extract_adapter_code(reply)
        if isinstance(extracted, SynthesisDeclined):
            return extracted
        code = extracted

    for root in (base_root, head_root):
        (root / f"{adapter_module}.py").write_text(code, encoding="utf-8")

    # Acceptance is EXECUTION on base — the same probe every deterministic adapter passes.
    validated = synthesize(base_root, adapter_module, "adapter", sandbox=sandbox, seed=seed)
    if isinstance(validated, SynthesisFailure):
        return SynthesisDeclined(
            detail=(
                f"the AI-written adapter for `{module}.{owner_class}.{method}` failed "
                f"execution validation on the base revision: {validated.detail}"
            )
        )

    if not from_cache:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(code, encoding="utf-8")
    return InstanceAdapter(module=adapter_module, qualname="adapter", from_cache=from_cache)


def _ask_model(
    module: str, owner_class: str, method: str, head_source: str
) -> str | SynthesisDeclined:
    import anthropic

    client = anthropic.Anthropic(
        base_url=os.environ.get("TEMPEST_SYNTHESIS_BASE_URL") or None,
        max_retries=1,
        timeout=60.0,
    )
    try:
        response = client.messages.create(
            model=os.environ.get("TEMPEST_SYNTHESIS_MODEL", _DEFAULT_MODEL),
            max_tokens=_MAX_ADAPTER_TOKENS,
            system=_SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Target: method `{method}` of class `{owner_class}` in module "
                        f"`{module}`.\nModule source:\n```python\n{head_source}\n```\n"
                        f"Write the adapter module. Import the class as "
                        f"`from {module} import {owner_class}`."
                    ),
                }
            ],
        )
    except anthropic.APIError as err:
        return SynthesisDeclined(detail=f"model call failed: {err.__class__.__name__}: {err}")
    text = "".join(block.text for block in response.content if block.type == "text")
    return text


def _extract_adapter_code(reply: str) -> str | SynthesisDeclined:
    match = _CODE_FENCE.search(reply)
    code = (match.group(1) if match else reply).strip() + "\n"
    try:
        compile(code, "<adapter>", "exec")
    except SyntaxError as err:
        return SynthesisDeclined(detail=f"the model's reply is not valid Python (syntax: {err})")
    if not re.search(r"^def adapter\(", code, re.MULTILINE):
        return SynthesisDeclined(
            detail="the model's reply defines no module-level `adapter` function"
        )
    return code
