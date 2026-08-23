"""The agent runtime's event union (C5, PLAN-V3) — what a turn REPORTS, typed.

Phase 21 shipped a flat `on_event(kind, detail)` — two strings, enough for a log line. The C5
surface re-target needs more: the chat frame vocabulary renders run steps per tool call
(name, arguments, result), a context gauge (real token counts), steer chips, approval parks.
Stringly-typed events made every consumer a parser; this union makes the shape the contract.

Design rules:

- **Every member is frozen and self-describing.** `kind` is a ClassVar tag for consumers that
  route by string (logs, benches); `describe()` is the human line the old `detail` used to be.
- **No verdict-shaped field a model can write** (L17): `VerdictReached.verdict` is emitted by
  the orchestrator from the ENGINE's output, after `run_verdict` — the event system carries
  it to EVIDENCE surfaces; platform chat surfaces must not render it (L31, held by
  `vocab_check` and the agent-turn forge test).
- **Unknown members must be ignorable.** Consumers match the types they know and let the rest
  pass; a new event is additive, never a break.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar


@dataclass(frozen=True)
class TurnStarted:
    """The loop is about to ask the model for turn `number` (1-based)."""

    number: int
    kind: ClassVar[str] = "turn_started"

    def describe(self) -> str:
        return f"turn {self.number}"


@dataclass(frozen=True)
class Resumed:
    """The task continued from its durable record rather than starting fresh (P2)."""

    reason: str
    kind: ClassVar[str] = "resume"

    def describe(self) -> str:
        return self.reason


@dataclass(frozen=True)
class Narration:
    """Model prose — narration, never evidence (L17)."""

    text: str
    kind: ClassVar[str] = "narration"

    def describe(self) -> str:
        return self.text


@dataclass(frozen=True)
class ToolCallStarted:
    """A tool call is about to dispatch — the run-step frame's opening half."""

    name: str
    call_id: str
    arguments: dict[str, Any] = field(default_factory=dict)
    kind: ClassVar[str] = "tool_started"

    def describe(self) -> str:
        return f"{self.name}: dispatching"


@dataclass(frozen=True)
class ToolCallFinished:
    """A tool call answered. `ok=False` means a refusal the model was shown verbatim."""

    name: str
    call_id: str
    ok: bool
    detail: str = ""
    kind: ClassVar[str] = "tool"

    def describe(self) -> str:
        return f"{self.name}: {'ok' if self.ok else 'refused'}"


@dataclass(frozen=True)
class TurnUsage:
    """One completion's token counts, AS THE PROVIDER REPORTED THEM (L21: measured, never
    estimated; zeros mean the provider said nothing, not that nothing was spent)."""

    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    kind: ClassVar[str] = "usage"

    def describe(self) -> str:
        return f"{self.input_tokens + self.output_tokens} tokens this turn"


@dataclass(frozen=True)
class CostCapReached:
    """The meter refused further spending; the loop ends and the shadow still proves."""

    message: str
    kind: ClassVar[str] = "cost"

    def describe(self) -> str:
        return self.message


@dataclass(frozen=True)
class ModelUnavailable:
    """The model failed mid-task (L23): the loop soft-breaks and the staged work proves."""

    message: str
    kind: ClassVar[str] = "model_error"

    def describe(self) -> str:
        return self.message


@dataclass(frozen=True)
class Proving:
    """The turn is over; the engine decides what it did."""

    kind: ClassVar[str] = "proving"

    def describe(self) -> str:
        return "the turn is over; the engine decides what it did"


@dataclass(frozen=True)
class VerdictReached:
    """The ENGINE's verdict, carried to evidence surfaces. Platform chat never renders it."""

    verdict: str
    bundle_id: str
    kind: ClassVar[str] = "verdict"

    def describe(self) -> str:
        return self.verdict


@dataclass(frozen=True)
class RepairAttemptStarted:
    """F3: one proof-guided repair attempt beginning."""

    number: int
    symbol: str
    kind: ClassVar[str] = "repair"

    def describe(self) -> str:
        return f"attempt {self.number}: {self.symbol}"


@dataclass(frozen=True)
class RepairRejected:
    """F3: an attempt refused for cheating; the loop stops rather than launder it."""

    number: int
    reason: str
    kind: ClassVar[str] = "repair"

    def describe(self) -> str:
        return f"attempt {self.number} rejected: {self.reason}"


@dataclass(frozen=True)
class SteerApplied:
    """A queued follow-up drained into the transcript (LC16)."""

    text: str
    kind: ClassVar[str] = "steer"

    def describe(self) -> str:
        return self.text


@dataclass(frozen=True)
class PendingApproval:
    """The turn PARKED on a human (LC18) — emitted after the durable turnlog row."""

    tool: str
    call_id: str
    ask_kind: str  # "tool_approval" | "ask_user_question"
    kind: ClassVar[str] = "pending_approval"

    def describe(self) -> str:
        return self.tool


@dataclass(frozen=True)
class ApprovalDecided:
    """The human answered a park."""

    tool: str
    call_id: str
    approved: bool
    kind: ClassVar[str] = "approval_decision"

    def describe(self) -> str:
        return f"{self.tool}: {'approved' if self.approved else 'refused'}"


@dataclass(frozen=True)
class SubagentStarted:
    """P4: a child task beginning, named by its full path id."""

    task_id: str
    depth: int
    kind: ClassVar[str] = "subagent"

    def describe(self) -> str:
        return f"{self.task_id} (depth {self.depth})"


AgentEvent = (
    TurnStarted
    | Resumed
    | Narration
    | ToolCallStarted
    | ToolCallFinished
    | TurnUsage
    | CostCapReached
    | ModelUnavailable
    | Proving
    | VerdictReached
    | RepairAttemptStarted
    | RepairRejected
    | SteerApplied
    | PendingApproval
    | ApprovalDecided
    | SubagentStarted
)
