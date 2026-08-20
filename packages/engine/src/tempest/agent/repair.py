"""F3 — Proof-Guided Repair: the minimized repro as a fitness function.

When a change diverges in a way the user did not ask for, the agent gets the *evidence* — the
minimized failing input, both observations, the divergence class, and the contract clause it
violated — and tries again. The loop re-proves after every attempt, and stops when the divergence
set matches the contract or the budget is spent (default 4 attempts).

**The hard part is not the loop. It is what "succeeded" means.**

A repair loop that measures success as "no unintended divergences remain" can be satisfied three
ways, and only one of them is a repair:

| how the divergence went away | is it a repair? |
|---|---|
| the behaviour was corrected | **yes** |
| the contract was edited to permit it | no — the claim was moved, not met |
| the divergent function was deleted | no — nothing diverges because nothing runs |
| the target stopped being provable | no — the evidence was destroyed, not the defect |

So `RepairOutcome.succeeded` requires all of:

* no `UNINTENDED` and no `UNCLASSIFIED` divergences remain;
* the contract is byte-identical to the one the loop started with;
* **every file the change touches still loads**;
* **every target that produced a verdict before still produces one**, and the proven set did not
  shrink.

The last condition is what makes deletion and unreachability fail closed. It is deliberately
stricter than the run-level verdict: `bundle.run_verdict` answers EQUIVALENT when *any* target is
equivalent even if others went UNPROVEN, which is right for a run and useless as a repair
criterion. F3 compares **per target**.

**Why "still loads" is a separate condition, and why it has to be EXECUTED** (ADR-0051). A bundle
carries only CHANGED symbols, so a symbol put back stops being a target and vanishes — exactly as
a deleted one does. `reverted_symbols` tells those apart by comparing the symbol's source, and an
agent that restores a function byte-for-byte while adding `import no_such_module_xyz` at the top
of the file defeats it: the source really is identical, the module is broken anyway by a statement
that belongs to no symbol, and with no changed symbol the engine has nothing to target either. No
static check closes it — `import no_such_module_xyz` parses perfectly. So the loop runs the
import, in the same sandbox everything else runs in (L4), and a module that no longer loads fails
the attempt whatever the divergence count says.

**No model decides whether a repair worked.** The judgement here is a comparison of two bundles
and one file hash (L17). The model only ever receives evidence and writes code.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from tempest.agent import contracts as contracts_mod
from tempest.model import Verdict

#: The spec's default. Every attempt costs a model turn and a full proof, so this is a real budget
#: and not a formality (L15.4).
DEFAULT_MAX_ATTEMPTS = 4

#: Verdicts that mean "the engine reached a conclusion about this target". A target that held one
#: of these before a repair and does not after has had its evidence destroyed, whatever the
#: divergence count says.
_CONCLUSIVE = (Verdict.DIVERGENT, Verdict.EQUIVALENT_UNDER_BUDGET)


@dataclass(frozen=True)
class EvidencePacket:
    """What the model is given to repair from. Facts from the bundle, never a summary.

    Deliberately compact: the minimized input is the smallest thing that still fails, which is
    the whole reason minimization exists, and a model handed the full input set tends to reason
    about the wrong one.
    """

    qualname: str
    divergence_class: str
    detail: str
    minimized_args: str
    minimized_kwargs: str
    base_summary: str
    head_summary: str
    #: Which contract clause this violated, quoted, so the model repairs against the stated
    #: intent rather than against its own idea of what the user wanted.
    violated_clause: str

    def render(self) -> str:
        """The packet as the model reads it. One fact per line, no prose, no advice."""
        return "\n".join(
            [
                "A change you made diverged in a way the contract does not allow.",
                "",
                f"symbol:            {self.qualname}",
                f"contract clause:   {self.violated_clause}",
                f"divergence:        {self.divergence_class}",
                f"detail:            {self.detail}",
                "",
                "The smallest input that still shows it:",
                f"  args:            {self.minimized_args}",
                f"  kwargs:          {self.minimized_kwargs}",
                "",
                f"  before your change: {self.base_summary}",
                f"  after your change:  {self.head_summary}",
                "",
                "Repair the behaviour. Do not edit the contract, do not delete the symbol, and",
                "do not make it unreachable — each of those is detected and counts as a failure.",
            ]
        )


@dataclass(frozen=True)
class BrokenModule:
    """A file the change touches that no longer imports, and the traceback that says why."""

    path: str
    module: str
    error: str

    @property
    def first_line(self) -> str:
        """The last line of the traceback — the exception, without the frames above it."""
        lines = [line for line in self.error.splitlines() if line.strip()]
        return lines[-1].strip() if lines else "no error was reported"


@dataclass(frozen=True)
class Judgement:
    """The verdict on one repair attempt, and whether it was a cheat.

    `cheat` is not a severity label: it decides what the loop does next. A behaviour that is
    still wrong earns another attempt, because that is what the budget is for. A cheat does not —
    giving an agent three more turns to keep moving the goalposts spends budget to make the
    record worse.
    """

    succeeded: bool
    reason: str
    cheat: bool = False


@dataclass(frozen=True)
class RepairAttempt:
    """One pass. Kept and returned because F3 says never hide the loop."""

    number: int
    packet: EvidencePacket
    unintended_after: int
    unclassified_after: int
    #: Set when this attempt was rejected for a reason other than "it did not fix the behaviour".
    cheat: str = ""


@dataclass(frozen=True)
class RepairOutcome:
    succeeded: bool
    attempts: tuple[RepairAttempt, ...]
    reason: str
    #: True when the agent undid its own work: the divergence is gone because the change is, so
    #: there is nothing to present. A FLAG rather than a phrase in `reason`, because callers act
    #: on this — the gate reports it as its own outcome — and reading a caller's behaviour off a
    #: substring of a human-readable message is a rule that breaks the next time the message is
    #: reworded (found by review).
    abandoned: bool = False

    @property
    def cheated(self) -> bool:
        return any(a.cheat for a in self.attempts)


def proven_targets(bundle: Any) -> dict[str, Verdict]:
    """The targets the engine reached a conclusion about, by qualname.

    UNPROVEN and ERROR are excluded on purpose: they are the states a cheat produces. Comparing
    the *conclusive* set before and after is what makes "I deleted the function" indistinguishable
    from progress impossible.
    """
    return {t.qualname: t.verdict for t in bundle.targets if t.verdict in _CONCLUSIVE}


def evidence_for(
    target: Any, divergence: Any, contract: contracts_mod.IntentContract | None
) -> EvidencePacket:
    """Build the packet from a bundle record. Every field is copied, none is computed."""
    return EvidencePacket(
        qualname=target.qualname,
        divergence_class=str(getattr(divergence.divergence_class, "value", "")),
        detail=divergence.detail,
        minimized_args=divergence.minimized_args,
        minimized_kwargs=divergence.minimized_kwargs,
        base_summary=divergence.base_summary,
        head_summary=divergence.head_summary,
        violated_clause=_clause_for(target.qualname, contract),
    )


def _clause_for(qualname: str, contract: contracts_mod.IntentContract | None) -> str:
    """The contract line this symbol fell foul of, quoted back.

    With no contract the honest answer names the absence rather than inventing a rule — an agent
    told it violated a clause that does not exist would repair against a fiction.
    """
    if contract is None:
        return "no contract on file: every divergence is unclassified until an intent is stated"
    for pattern in contract.must_not_change:
        if contracts_mod._matches_any(qualname, (pattern,)):
            return f'must_not_change = "{pattern}"'
    return f"not listed in may_change (intent: {contract.intent!r})"


def judge(
    *,
    before: dict[str, Verdict],
    after_bundle: Any,
    divergences: tuple[Any, ...],
    contract_before: str,
    contract_after: str,
    reverted: frozenset[str] = frozenset(),
    broken: tuple[BrokenModule, ...] = (),
) -> Judgement:
    """Did this attempt repair the change?

    The order of the checks is the order of severity, so the reason a caller shows the user names
    the WORST thing that happened rather than the first one noticed.

    `cheat` is decided HERE, by which check failed, rather than inferred by the caller from the
    wording of `reason`. An earlier draft had the orchestrator test `"remain" in reason`, which
    made every future failure message a load-bearing string one word away from silently
    reclassifying a cheat as an ordinary miss.
    """
    if contract_before != contract_after:
        return Judgement(
            False, "the contract changed during the repair — the claim was moved, not met", True
        )

    if broken:
        return Judgement(
            False,
            "the change no longer loads: "
            + "; ".join(f"{b.path} ({b.first_line})" for b in broken)
            + " — a divergence that disappears because the module stopped running is not a repair",
            True,
        )

    after = proven_targets(after_bundle)
    # A symbol that was PUT BACK is not a lost target. It leaves the bundle because it is no
    # longer changed, and "no longer changed" is the correct outcome of repairing collateral
    # damage — the caller establishes this by comparing the symbol's source against the
    # baseline, which is the only way to tell a revert from a deletion: both simply vanish from
    # a bundle that only ever contains changed symbols.
    lost = sorted(set(before) - set(after) - reverted)
    if lost:
        return Judgement(
            False,
            f"targets stopped being provable: {', '.join(lost)} — a divergence that disappears "
            f"because the evidence did is not a repair",
            True,
        )

    unintended = [d for d in divergences if d.classification == contracts_mod.UNINTENDED]
    unclassified = [d for d in divergences if d.classification == contracts_mod.UNCLASSIFIED]
    if unintended:
        return Judgement(False, f"{len(unintended)} unintended divergence(s) remain", False)
    if unclassified:
        return Judgement(
            False,
            f"{len(unclassified)} unclassified divergence(s) remain — nobody predicted these, so "
            f"they are shown rather than assumed harmless",
            False,
        )
    return Judgement(True, "the divergence set matches the contract", False)


def reverted_symbols(
    *,
    lost: set[str],
    first_bundle: Any,
    read_source: Any,
    baseline: str,
    head: str,
) -> frozenset[str]:
    """Of the targets that left the bundle, which were PUT BACK rather than destroyed.

    A bundle contains only CHANGED symbols, so a target disappears for two opposite reasons: the
    agent reverted it (the right way to undo collateral damage) or the agent removed it (a cheat).
    Both look identical in the bundle, which is why the answer has to come from the source.

    `read_source(sha, path)` returns the file's text at a revision, or None. A symbol whose text
    is byte-identical at baseline and head was reverted. A symbol that is absent from head was
    deleted. A symbol still present and still different is changed-but-unprovable — the shape a
    broken import makes — and is not reverted.
    """
    paths = {t.qualname: t.file_path for t in first_bundle.targets}
    put_back: set[str] = set()
    for qualname in lost:
        path = paths.get(qualname)
        if path is None:
            continue
        base_src = _symbol_source(read_source(baseline, path), qualname)
        head_src = _symbol_source(read_source(head, path), qualname)
        if base_src is not None and base_src == head_src:
            put_back.add(qualname)
    return frozenset(put_back)


def _symbol_source(text: str | None, qualname: str) -> str | None:
    """The source of one top-level function or class, or None when it is not there.

    Deliberately narrow: it answers "is this symbol byte-identical to before", and nothing else.
    A parse failure answers None, which is the conservative direction — an unparseable head is
    not evidence that anything was put back.
    """
    if text is None:
        return None
    import ast

    try:
        tree = ast.parse(text)
    except SyntaxError:
        return None
    wanted = qualname.split(".")[-1]
    for node in ast.iter_child_nodes(tree):
        if (
            isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
            and node.name == wanted
        ):
            return ast.get_source_segment(text, node)
    return None
