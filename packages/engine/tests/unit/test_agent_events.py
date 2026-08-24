"""The event union's rendering contract (C5, ADR-0079 §5).

`describe()` is the human line the old flat `on_event(kind, detail)` used to carry, and it is
the text an operator reads when a turn goes wrong. Sixteen members each render one; eight of
them had never been executed by any test, which the 100% combined-coverage gate named.

Coverage is not the reason these assertions exist. Every one of these lines is a sentence a
human reads to find out what an agent did, and two of them invert their meaning on a single
wrong token: `ToolCallFinished` renders "ok"/"refused" off `self.ok`, and `ApprovalDecided`
renders "approved"/"refused" off `self.approved`. A flipped conditional there tells an
operator the user approved a call the user refused. Those two get their BOTH branches pinned
below, not just the arm that happens to appear in an integration run.
"""

from __future__ import annotations

import dataclasses
import typing

import pytest

from tempest.agent import events as events_mod
from tempest.agent.events import (
    AgentEvent,
    ApprovalDecided,
    CostCapReached,
    ModelUnavailable,
    Narration,
    PendingApproval,
    Proving,
    RepairAttemptStarted,
    RepairRejected,
    Resumed,
    SteerApplied,
    SubagentStarted,
    ToolCallFinished,
    ToolCallStarted,
    TurnStarted,
    TurnUsage,
    VerdictReached,
)

#: (event, the exact line it must render). One row per member of the union.
_RENDERINGS: list[tuple[object, str]] = [
    (TurnStarted(number=3), "turn 3"),
    (Resumed(reason="the journal had an unfinished turn"), "the journal had an unfinished turn"),
    (Narration(text="Let me look at app.py."), "Let me look at app.py."),
    (ToolCallStarted(name="read_file", call_id="c1"), "read_file: dispatching"),
    (ToolCallFinished(name="read_file", call_id="c1", ok=True), "read_file: ok"),
    (ToolCallFinished(name="write_file", call_id="c2", ok=False), "write_file: refused"),
    (
        TurnUsage(provider="anthropic", model="m", input_tokens=40, output_tokens=2),
        "42 tokens this turn",
    ),
    (CostCapReached(message="session cap reached at $5.00"), "session cap reached at $5.00"),
    (ModelUnavailable(message="anthropic: HTTP 503"), "anthropic: HTTP 503"),
    (Proving(), "the turn is over; the engine decides what it did"),
    (VerdictReached(verdict="UNPROVEN", bundle_id="b1"), "UNPROVEN"),
    (RepairAttemptStarted(number=2, symbol="app.total"), "attempt 2: app.total"),
    (
        RepairRejected(number=2, reason="the patch did not apply"),
        "attempt 2 rejected: the patch did not apply",
    ),
    (SteerApplied(text="also update the README"), "also update the README"),
    (
        PendingApproval(tool="run_command", call_id="c3", ask_kind="tool_approval"),
        "run_command",
    ),
    (ApprovalDecided(tool="run_command", call_id="c3", approved=True), "run_command: approved"),
    (ApprovalDecided(tool="run_command", call_id="c3", approved=False), "run_command: refused"),
    (SubagentStarted(task_id="t-9", depth=2), "t-9 (depth 2)"),
]


def _members() -> tuple[type, ...]:
    """The union's members, read off the alias rather than re-listed by hand — a member added
    to `AgentEvent` without a row below must fail this file, not slip past it."""
    return typing.get_args(AgentEvent)


class TestDescribe:
    @pytest.mark.parametrize(
        ("event", "expected"),
        _RENDERINGS,
        ids=[f"{type(e).__name__}-{i}" for i, (e, _) in enumerate(_RENDERINGS)],
    )
    def test_each_member_renders_its_human_line(self, event: object, expected: str) -> None:
        assert isinstance(event, _members())
        assert event.describe() == expected  # type: ignore[attr-defined]

    def test_every_member_of_the_union_is_covered_by_a_rendering_row(self) -> None:
        """The guard that keeps this file honest as the union grows.

        A seventeenth member added to `AgentEvent` with no row in `_RENDERINGS` is an event
        whose human line nobody has ever read. Without this assertion the parametrized test
        above stays green about a member it never constructs — an upper bound satisfied by
        absence (trap 60)."""
        covered = {type(event) for event, _ in _RENDERINGS}
        missing = sorted(m.__name__ for m in _members() if m not in covered)
        assert not missing, f"union members with no describe() rendering pinned: {missing}"

    def test_the_rendering_table_actually_exercised_every_row(self) -> None:
        """A lower bound beside the upper one: sixteen members, and the two boolean-rendering
        members contribute both arms, so the table must hold eighteen rows."""
        assert len(_members()) == 16
        assert len(_RENDERINGS) == 18


class TestUnionDiscipline:
    def test_every_member_is_frozen(self) -> None:
        """ADR-0079 §5: the members are frozen. A mutable event is an event a consumer can
        rewrite after the producer vouched for it — and `VerdictReached.verdict` is exactly
        the field L17 forbids anyone downstream to author."""
        for member in _members():
            params = getattr(member, "__dataclass_params__", None)
            assert params is not None, f"{member.__name__} is not a dataclass"
            assert params.frozen, f"{member.__name__} is not frozen"

    def test_a_verdict_event_refuses_mutation(self) -> None:
        event = VerdictReached(verdict="UNPROVEN", bundle_id="b1")
        with pytest.raises(dataclasses.FrozenInstanceError):
            event.verdict = "EQUIVALENT_UNDER_BUDGET"  # type: ignore[misc]
        assert event.verdict == "UNPROVEN"

    def test_every_member_carries_a_distinct_nonempty_kind_tag(self) -> None:
        """`kind` is the ClassVar tag consumers route by. Two members are DELIBERATELY allowed
        to share a tag (the two repair events are one `repair` stream), so this asserts the
        tags are present and non-empty and that the deliberate sharing is exactly that pair —
        an accidental third collision would silently merge two event streams in every log."""
        tags = {m.__name__: m.kind for m in _members()}  # type: ignore[attr-defined]
        assert all(isinstance(t, str) and t for t in tags.values())
        shared = [t for t in set(tags.values()) if list(tags.values()).count(t) > 1]
        assert shared == ["repair"], f"unexpected kind-tag collisions: {shared}"
        assert {n for n, t in tags.items() if t == "repair"} == {
            "RepairAttemptStarted",
            "RepairRejected",
        }

    def test_the_module_exports_exactly_the_union_it_documents(self) -> None:
        """Every public dataclass in the module is a member of `AgentEvent`. A dataclass that
        is an event in spirit but absent from the alias is an event no exhaustive consumer can
        be made to handle."""
        public = {
            name
            for name, obj in vars(events_mod).items()
            if isinstance(obj, type) and dataclasses.is_dataclass(obj) and not name.startswith("_")
        }
        assert public == {m.__name__ for m in _members()}
