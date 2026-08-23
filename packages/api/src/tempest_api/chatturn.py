"""Streamed platform chat turns — the C5 generation job manager (ADR-0078).

One turn = one job, keyed by `streamId == conversationId` (the vendored client's hard
assumption). The POST answers immediately with the ack; a background thread runs the model
via `tempest.inference.stream_events` and appends wire frames (chatwire.py) to the job's
ledger; the host (or the e2e harness) polls `events_after` and emits them as SSE verbatim.

Durability holds this repo's hardest-won ordering lesson (the run-events race, fix 52e18fd)
in BOTH directions: terminal state commits to the store FIRST and is published to readers
after, and a new turn's opening commit atomically retires the previous turn's ledger — so a
reader can never see a finished status with a truncated timeline, an unsaved message, or two
generations interleaved under one stream id. Mid-stream deltas batch (a lost delta is
replayable noise; the memory ledger serves live reads); terminal state never batches.

What this module is NOT: an agent loop. No tools, no repo, no proof — nothing here can
construct a `ProvenChange` or reach a working tree, so L28 has nothing to gate (there is no
agent-authored change). Tool-bearing agent turns are `run_task`'s, re-targeted later in C5.
"""

import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from tempest.inference import cost
from tempest.inference import providers as registry
from tempest.inference.client import (
    Cancelled,
    Message,
    ModelError,
    StreamUsage,
    TextDelta,
    UpstreamError,
    stream,
    stream_events,
)
from tempest.obslog import get_logger
from tempest_api import agentturn, chatwire
from tempest_api.agentstore import AgentStore
from tempest_api.platformstore import PlatformStore

#: Streamed deltas flush to the store in batches; the memory ledger is the live source.
_FLUSH_EVERY_FRAMES = 25
_FLUSH_EVERY_SECONDS = 0.25
#: History handed to the model is capped; the context-usage gauge arrives later in C5.
_HISTORY_CAP = 40
_DEFAULT_MAX_TOKENS = 4096
_MAX_TOKENS_CEILING = 32_768
#: A cold local model can take minutes to load before its first token; the agent loop's 60s
#: default would blame Tempest for a slow runner (L15.3 — errors must name the real cause).
_CHAT_TIMEOUT_S = 300.0
#: Settled jobs kept in memory for fast replay; older ones serve from the store.
_SETTLED_JOBS_KEPT = 8
#: How long a cancel waits for the stream loop to observe the event and land the abort-final
#: before answering anyway. The C5 run-control item closed the trap-58 gap this comment used
#: to queue: the READ itself is now bounded (`inference.client._cancel_guard` shuts the socket
#: down at the fd when the cancel fires), so even a SILENT upstream settles within the guard's
#: poll interval — this wait is generous slack, not the bound.
_CANCEL_SETTLE_WAIT_S = 2.0

GENERATION_PROTOCOL_VERSION = 1


def _now_rfc3339() -> str:
    return datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")


def _now_ms() -> int:
    return int(time.time() * 1000)


class TurnConflict(Exception):
    """A generation is already active for this conversation."""


class TurnRejected(Exception):
    """The request cannot start a turn (unknown endpoint, blank text) — a 400, not a 500."""


@dataclass
class _Job:
    stream_id: str
    conversation_id: str
    generation_created_at: int
    user_message_id: str
    response_message_id: str
    status: str = "active"  # active | complete | aborted | error
    frames: list[dict[str, Any]] = field(default_factory=list)
    cancel: threading.Event = field(default_factory=threading.Event)
    #: Set by the AGENT-turn worker (C5): the runtime's cancellation scope, so an abort can
    #: kill registered children through `scope.cancel()` rather than only flag the event.
    cancel_scope: Any = None
    settled: threading.Event = field(default_factory=threading.Event)
    lock: threading.Lock = field(default_factory=threading.Lock)
    #: Ledger rows not yet flushed to the store, id → doc.
    pending: dict[str, dict[str, Any]] = field(default_factory=dict)
    last_flush: float = field(default_factory=time.monotonic)

    def append(self, frame: dict[str, Any]) -> None:
        """Add a frame to the memory ledger and the pending batch."""
        with self.lock:
            seq = len(self.frames) + 1
            self.frames.append(frame)
            self.pending[_event_key(self.stream_id, seq)] = {
                "streamId": self.stream_id,
                "seq": seq,
                "frame": frame,
            }


def _event_key(stream_id: str, seq: int) -> str:
    return f"{stream_id}:{seq:08d}"


class ChatTurns:
    """The registry of live jobs over one platform store. One instance per process."""

    def __init__(
        self,
        store: PlatformStore,
        *,
        env_provider: Callable[[], dict[str, str]],
        meter: cost.Meter | None,
        agents: AgentStore | None = None,
    ) -> None:
        self._store = store
        self._env_provider = env_provider
        self._meter = meter
        self._agents = agents
        self._jobs: dict[str, _Job] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ start

    def start_turn(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Validate, persist the user message, seed the ledger, spawn the turn thread, and
        answer the ack — the client's POST body in, the client's ack body out."""
        text = str(payload.get("text") or "").strip()
        endpoint = str(payload.get("endpoint") or "").strip()
        agent_doc: dict[str, Any] | None = None
        if endpoint == "agents":
            # The AGENT resolves the provider and model (C5, ADR-0075): the client sends
            # only the agent id, and the document carries what the builder configured.
            agent_id = str(payload.get("agent_id") or "")
            agent_doc = self._agents.get(agent_id) if self._agents is not None else None
            if agent_doc is None:
                raise TurnRejected(f"unknown agent {agent_id!r} — it is not in the store")
            provider = _provider_for_endpoint(str(agent_doc.get("provider") or ""))
            if provider is None:
                raise TurnRejected(
                    f"agent {agent_doc.get('name') or agent_id} names provider "
                    f"{agent_doc.get('provider')!r}, which is not in the catalog"
                )
        else:
            provider = _provider_for_endpoint(endpoint)
            if provider is None:
                raise TurnRejected(f"unknown endpoint {endpoint!r} — not in the provider catalog")
        regenerate = bool(payload.get("isRegenerate"))
        if not text and not regenerate:
            raise TurnRejected("an empty message cannot start a turn")

        conversation_id = str(payload.get("conversationId") or "") or str(uuid.uuid4())
        stream_id = conversation_id
        model = _model_from(payload, provider)
        if agent_doc is not None:
            model = str(agent_doc.get("model") or "").strip() or model
        now = _now_rfc3339()
        conversation = self._store.get("conversations", conversation_id) or {
            "conversationId": conversation_id,
            "title": _title_from(text),
            "createdAt": now,
            "isArchived": False,
        }
        conversation["updatedAt"] = now
        conversation["endpoint"] = endpoint
        conversation["model"] = model
        if agent_doc is not None:
            # The client's mount-after-reload restores the agent context from this field.
            conversation["agent_id"] = str(agent_doc.get("id") or "")

        if regenerate:
            # The client regenerates by naming the TARGET user message in
            # overrideParentMessageId; its messageId field is a fresh placeholder that must
            # never become a stored row, and its parentMessageId is the target's own parent.
            target = str(payload.get("overrideParentMessageId") or "")
            existing = self._store.get("messages", target)
            if existing is None or not existing.get("isCreatedByUser"):
                raise TurnRejected("regenerate names a user message that does not exist")
            user_message = existing
        else:
            user_message = {
                "messageId": str(payload.get("messageId") or "") or str(uuid.uuid4()),
                "parentMessageId": str(payload.get("parentMessageId") or "") or chatwire.NO_PARENT,
                "conversationId": conversation_id,
                "sender": "User",
                "text": text,
                "isCreatedByUser": True,
                "error": False,
                "unfinished": False,
                "createdAt": now,
                "updatedAt": now,
            }
            for carried in ("quotes", "files"):
                if payload.get(carried) is not None:
                    user_message[carried] = payload[carried]

        job = _Job(
            stream_id=stream_id,
            conversation_id=conversation_id,
            generation_created_at=_now_ms(),
            user_message_id=str(user_message["messageId"]),
            response_message_id=str(uuid.uuid4()),
        )
        job.append(chatwire.created_frame(stream_id=stream_id, user_message=user_message))
        job.append(chatwire.run_step_frame(response_message_id=job.response_message_id))

        # Reserve the stream id and only then touch the store: the reservation and the
        # conflict check are ONE lock hold, so two concurrent sends cannot both start, and
        # every reader that can see the store's `active` row can already see the live job
        # (no window for the dead-turn reconciler to fire on a living turn).
        with self._lock:
            live = self._jobs.get(stream_id)
            if live is not None and live.status == "active":
                raise TurnConflict(f"a generation is already active for {conversation_id}")
            self._jobs[stream_id] = job
            self._evict_settled_locked()

        try:
            with job.lock:
                rows = [
                    ("conversations", conversation_id, dict(conversation)),
                    ("messages", str(user_message["messageId"]), dict(user_message)),
                    ("turns", stream_id, self._turn_doc(job, sender=provider.label)),
                ]
                rows.extend(("turn_events", key, doc) for key, doc in sorted(job.pending.items()))
                job.pending.clear()
            # The opening commit atomically retires the PREVIOUS generation's ledger under
            # this stream id — seq restarts at 1 every turn, and two generations must never
            # interleave in a replay.
            self._store.put_many_multi(rows, delete_equal=[("turn_events", "streamId", stream_id)])
        except BaseException:
            with self._lock:
                self._jobs.pop(stream_id, None)
            raise

        if agent_doc is not None and (agent_doc.get("tools") or []):
            # A tool-bearing agent turn dispatches through the ONE runtime (L29): the worker
            # in `agentturn` hands the job to `run_task` and streams narration back through
            # this ledger. Never a second loop.
            thread = threading.Thread(
                target=agentturn.run_agent_turn,
                args=(
                    self,
                    job,
                    dict(agent_doc),
                    provider,
                    model,
                    dict(user_message),
                    dict(conversation),
                    endpoint,
                ),
                name=f"agent-turn-{stream_id[:8]}",
                daemon=True,
            )
        else:
            system = _system_from(payload)
            if agent_doc is not None:
                # A PERSONA agent (no tools) is plain streamed chat wearing its
                # instructions as the system prompt.
                system = str(agent_doc.get("instructions") or "") or system
            thread = threading.Thread(
                target=self._run_turn,
                args=(
                    job,
                    provider,
                    model,
                    dict(user_message),
                    dict(conversation),
                    endpoint,
                    _max_tokens_from(payload),
                    system,
                ),
                name=f"chat-turn-{stream_id[:8]}",
                daemon=True,
            )
        thread.start()
        return {
            "streamId": stream_id,
            "conversationId": conversation_id,
            "generationCreatedAt": job.generation_created_at,
            "status": "started",
            "generationProtocolVersion": GENERATION_PROTOCOL_VERSION,
        }

    def _evict_settled_locked(self) -> None:
        """Drop the oldest settled jobs past the keep-window; the store serves their replay.
        Caller holds `self._lock`."""
        settled = [
            (job.generation_created_at, stream_id)
            for stream_id, job in self._jobs.items()
            if job.status != "active"
        ]
        settled.sort()
        for _, stream_id in settled[: max(0, len(settled) - _SETTLED_JOBS_KEPT)]:
            del self._jobs[stream_id]

    # ------------------------------------------------------------------- turn

    def _run_turn(
        self,
        job: _Job,
        provider: registry.Provider,
        model: str,
        user_message: dict[str, Any],
        conversation: dict[str, Any],
        endpoint: str,
        max_tokens: int,
        system: str | None,
    ) -> None:
        collected: list[str] = []
        usage: StreamUsage | None = None
        error_text: str | None = None
        aborted = False
        try:
            history = self._history_for(user_message)
            try:
                for event in stream_events(
                    provider.id,
                    history,
                    env=self._env_provider(),
                    model=model,
                    max_tokens=max_tokens,
                    timeout=_CHAT_TIMEOUT_S,
                    cancel=job.cancel,
                    system=system,
                ):
                    if isinstance(event, TextDelta):
                        collected.append(event.text)
                        job.append(
                            chatwire.message_delta_frame(
                                response_message_id=job.response_message_id, text=event.text
                            )
                        )
                        self._flush_if_due(job)
                    else:
                        usage = event
            except UpstreamError as exc:
                if "stream_options" not in str(exc) or collected:
                    raise
                # A strict OpenAI-compatible server rejected the usage knob. Losing the
                # usage report for this provider is honest; losing chat would not be.
                for delta in stream(
                    provider.id,
                    history,
                    env=self._env_provider(),
                    model=model,
                    max_tokens=max_tokens,
                    timeout=_CHAT_TIMEOUT_S,
                    cancel=job.cancel,
                    system=system,
                ):
                    collected.append(delta)
                    job.append(
                        chatwire.message_delta_frame(
                            response_message_id=job.response_message_id, text=delta
                        )
                    )
                    self._flush_if_due(job)
        except Cancelled:
            aborted = True
        except ModelError as exc:
            error_text = str(exc)
        except Exception as exc:  # a defect in us, surfaced in-band rather than swallowed
            error_text = f"the turn failed inside Tempest: {exc!r}"
        self._finish(
            job,
            conversation,
            user_message,
            collected,
            usage,
            model,
            endpoint,
            provider,
            aborted=aborted,
            error=error_text,
        )

    def _finish(
        self,
        job: _Job,
        conversation: dict[str, Any],
        user_message: dict[str, Any],
        collected: list[str],
        usage: StreamUsage | None,
        model: str,
        endpoint: str,
        provider: registry.Provider,
        *,
        aborted: bool = False,
        error: str | None = None,
    ) -> None:
        cap_note = self._record_spend(job, provider, model, usage)
        if cap_note is not None:
            collected.append(cap_note)
        text = "".join(collected)
        now = _now_rfc3339()
        content: list[dict[str, Any]] = []
        if text:
            content.append(chatwire.text_content_part(text))
        if error is not None:
            content.append(chatwire.error_content_part(error))
        response_message = {
            "messageId": job.response_message_id,
            "parentMessageId": job.user_message_id,
            "conversationId": job.conversation_id,
            "sender": provider.label,
            "text": text,
            "content": content,
            "isCreatedByUser": False,
            "error": error is not None,
            "unfinished": aborted,
            "endpoint": endpoint,
            "model": model,
            "createdAt": now,
            "updatedAt": now,
        }
        conversation = dict(conversation)
        conversation["updatedAt"] = now

        # Build the terminal tail WITHOUT publishing it: the store commit comes first, and
        # only a durable terminal becomes visible (52e18fd, this time in our own house).
        tail: list[dict[str, Any]] = []
        if cap_note is not None:
            tail.append(
                chatwire.message_delta_frame(
                    response_message_id=job.response_message_id, text=cap_note
                )
            )
        if usage is not None:
            tail.append(
                chatwire.token_usage_frame(
                    response_message_id=job.response_message_id,
                    provider=provider.id,
                    model=model,
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                )
            )
        tail.append(
            chatwire.final_frame(
                conversation=conversation,
                request_message=user_message,
                response_message=response_message,
                aborted=aborted,
            )
        )
        status = "aborted" if aborted else ("error" if error is not None else "complete")

        with job.lock:
            base_seq = len(job.frames)
            rows = [
                ("conversations", job.conversation_id, conversation),
                ("messages", job.response_message_id, response_message),
                ("turns", job.stream_id, self._turn_doc(job, sender=provider.label, status=status)),
            ]
            rows.extend(("turn_events", key, doc) for key, doc in sorted(job.pending.items()))
            pending_backup = dict(job.pending)
            job.pending.clear()
            for offset, frame in enumerate(tail):
                seq = base_seq + offset + 1
                rows.append(
                    (
                        "turn_events",
                        _event_key(job.stream_id, seq),
                        {"streamId": job.stream_id, "seq": seq, "frame": frame},
                    )
                )
        try:
            self._store.put_many_multi(rows)
        except Exception:
            # The turn happened but its terminal state could not be made durable. Publishing
            # a healthy `complete` now would be the exact lie 52e18fd unteaches — publish an
            # error terminal in memory, log the cause, and let a later read reconcile from
            # whatever the store really holds.
            get_logger("chat").exception(
                "terminal commit failed", extra={"tempest_extra": {"stream_id": job.stream_id}}
            )
            with job.lock:
                job.pending.update(pending_backup)
                job.frames.append(
                    chatwire.final_frame(
                        conversation=conversation,
                        request_message=user_message,
                        response_message={
                            **response_message,
                            "error": True,
                            "content": [
                                *content,
                                chatwire.error_content_part(
                                    "the reply could not be saved — it may be missing after "
                                    "a reload"
                                ),
                            ],
                        },
                        aborted=aborted,
                    )
                )
                job.status = "error"
                job.settled.set()
            return
        with job.lock:
            job.frames.extend(tail)
            job.status = status
            job.settled.set()

    def _record_spend(
        self, job: _Job, provider: registry.Provider, model: str, usage: StreamUsage | None
    ) -> str | None:
        if self._meter is None or usage is None:
            return None
        try:
            self._meter.spend(
                provider=provider.id,
                model=model,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                task=job.conversation_id,
                session="platform-chat",
                day=datetime.now(tz=UTC).date().isoformat(),
            )
        except cost.CostError as exc:
            # The charge was already incurred upstream; the meter refuses to bless it, and
            # the refusal reaches the user inside the reply. Refusing FUTURE turns at start
            # (and recording the overage) arrives with configurable budgets in the C5
            # run-control item.
            return f"\n\n[cost cap: {exc}]"
        except Exception:
            # The meter's ledger is disk I/O on the same volume as the store; a full disk
            # here must degrade to an unrecorded charge with a logged cause — never a dead
            # turn thread that leaves the conversation claiming active forever (L15.3).
            get_logger("chat").exception(
                "spend recording failed",
                extra={"tempest_extra": {"stream_id": job.stream_id}},
            )
            return None
        return None

    def _flush_if_due(self, job: _Job) -> None:
        with job.lock:
            due = (
                len(job.pending) >= _FLUSH_EVERY_FRAMES
                or (time.monotonic() - job.last_flush) >= _FLUSH_EVERY_SECONDS
            )
            if not due:
                return
            batch = dict(job.pending)
            job.pending.clear()
            job.last_flush = time.monotonic()
        try:
            self._store.put_many_multi(
                [("turn_events", key, doc) for key, doc in sorted(batch.items())]
            )
        except Exception:
            # The memory ledger still holds every frame; put the batch back so the next
            # flush (or the terminal commit) retries it rather than leaving a mid-text hole
            # in the durable replay.
            get_logger("chat").exception(
                "delta flush failed", extra={"tempest_extra": {"stream_id": job.stream_id}}
            )
            with job.lock:
                for key, doc in batch.items():
                    job.pending.setdefault(key, doc)

    def _history_for(self, user_message: dict[str, Any]) -> list[Message]:
        """The parent chain, root-first, ending at the new user message — branches stay
        branches: only the active chain reaches the model."""
        by_id: dict[str, dict[str, Any]] = {}
        for doc in self._store.find_equal(
            "messages",
            "conversationId",
            str(user_message["conversationId"]),
            order_by="createdAt",
        ):
            by_id[str(doc.get("messageId"))] = doc
        chain: list[dict[str, Any]] = [user_message]
        seen = {str(user_message["messageId"])}
        cursor = str(user_message.get("parentMessageId") or chatwire.NO_PARENT)
        while cursor and cursor != chatwire.NO_PARENT and cursor not in seen:
            parent = by_id.get(cursor)
            if parent is None:
                break
            chain.append(parent)
            seen.add(cursor)
            cursor = str(parent.get("parentMessageId") or chatwire.NO_PARENT)
        chain.reverse()
        return [
            Message(
                role="user" if doc.get("isCreatedByUser") else "assistant",
                content=str(doc.get("text") or ""),
            )
            for doc in chain[-_HISTORY_CAP:]
            if str(doc.get("text") or "").strip()
        ]

    # ------------------------------------------------------------------ reads

    def events_after(self, stream_id: str, after_seq: int) -> dict[str, Any]:
        after_seq = max(0, after_seq)
        job = self._job_or_reconcile(stream_id)
        if job is not None:
            with job.lock:
                frames = job.frames[after_seq:]
                status = job.status
            return {
                "streamId": stream_id,
                "status": status,
                "events": [
                    {"seq": after_seq + index + 1, "frame": frame}
                    for index, frame in enumerate(frames)
                ],
            }
        turn = self._store.get("turns", stream_id)
        if turn is None:
            return {"streamId": stream_id, "status": "unknown", "events": []}
        docs = self._store.find_equal("turn_events", "streamId", stream_id, order_by="seq")
        return {
            "streamId": stream_id,
            "status": str(turn.get("status") or "unknown"),
            "events": [
                {"seq": int(doc["seq"]), "frame": doc["frame"]}
                for doc in docs
                if int(doc.get("seq") or 0) > after_seq and isinstance(doc.get("frame"), dict)
            ],
        }

    def status(self, conversation_id: str) -> dict[str, Any]:
        job = self._job_or_reconcile(conversation_id)
        if job is not None and job.status == "active":
            return {
                "active": True,
                "status": "active",
                "streamId": job.stream_id,
                "conversationId": conversation_id,
                "generationCreatedAt": job.generation_created_at,
                # The vendored status contract names this createdAt; both names are served
                # so no host has to translate.
                "createdAt": job.generation_created_at,
                "generationProtocolVersion": GENERATION_PROTOCOL_VERSION,
            }
        return {
            "active": False,
            "conversationId": conversation_id,
            "generationProtocolVersion": GENERATION_PROTOCOL_VERSION,
        }

    def active_ids(self) -> list[str]:
        with self._lock:
            live = [job.stream_id for job in self._jobs.values() if job.status == "active"]
        return sorted(live)

    def cancel_turn(
        self, stream_id: str, *, generation_created_at: int | None = None
    ) -> dict[str, Any]:
        job = self._job_or_reconcile(stream_id)
        if job is None or job.status != "active":
            return {
                "success": True,
                "settled": True,
                "generationProtocolVersion": GENERATION_PROTOCOL_VERSION,
            }
        if generation_created_at is not None and generation_created_at != job.generation_created_at:
            # A stale tab aborting a conversation-scoped stream id must not kill the
            # SUCCESSOR turn that reused it.
            return {
                "success": True,
                "settled": True,
                "generationProtocolVersion": GENERATION_PROTOCOL_VERSION,
            }
        job.cancel.set()
        if job.cancel_scope is not None:
            # The agent-turn path: cancel through the SCOPE so registered children are
            # killed, not merely flagged (`CancelScope.cancel` sweeps process groups).
            job.cancel_scope.cancel()
        # Usually the loop observes at the very next chunk and the abort-final is durable
        # before this returns; a silent upstream is bounded by the stream timeout instead,
        # and the client's stream stays open until the final lands either way.
        job.settled.wait(timeout=_CANCEL_SETTLE_WAIT_S)
        return {
            "success": True,
            "aborted": stream_id,
            "generationProtocolVersion": GENERATION_PROTOCOL_VERSION,
        }

    def conversations(self, *, limit: int = 100) -> list[dict[str, Any]]:
        return self._store.list_ordered(
            "conversations", order_by="updatedAt", descending=True, limit=limit
        )

    def conversation(self, conversation_id: str) -> dict[str, Any] | None:
        return self._store.get("conversations", conversation_id)

    def messages_for(self, conversation_id: str) -> list[dict[str, Any]]:
        return self._store.find_equal(
            "messages", "conversationId", conversation_id, order_by="createdAt"
        )

    # ------------------------------------------------------------- reconcile

    def _job_or_reconcile(self, stream_id: str) -> _Job | None:
        with self._lock:
            job = self._jobs.get(stream_id)
        if job is not None:
            return job
        # A turns row claiming `active` with no live job is a PREVIOUS process that died
        # mid-turn (start_turn reserves the registry slot before the row exists, so a live
        # turn can never look like this). Reconcile on read: the partial reply the user
        # watched is kept, the timeline ends in an aborted final, and the status stops
        # claiming liveness.
        turn = self._store.get("turns", stream_id)
        if turn is not None and turn.get("status") == "active":
            with self._lock:
                if stream_id in self._jobs:
                    return self._jobs[stream_id]
                self._reconcile_dead(stream_id, turn)
        return None

    def _reconcile_dead(self, stream_id: str, turn: dict[str, Any]) -> None:
        docs = self._store.find_equal("turn_events", "streamId", stream_id, order_by="seq")
        text = "".join(
            str(part.get("text", ""))
            for doc in docs
            if isinstance(doc.get("frame"), dict)
            and doc["frame"].get("event") == "on_message_delta"
            for part in doc["frame"].get("data", {}).get("delta", {}).get("content", [])
            if isinstance(part, dict) and part.get("type") == "text"
        )
        conversation = self._store.get("conversations", str(turn.get("conversationId"))) or {
            "conversationId": turn.get("conversationId")
        }
        user_message = self._store.get("messages", str(turn.get("userMessageId"))) or {}
        now = _now_rfc3339()
        response_message = {
            "messageId": str(turn.get("responseMessageId")),
            "parentMessageId": str(turn.get("userMessageId")),
            "conversationId": str(turn.get("conversationId")),
            "sender": str(turn.get("sender") or "assistant"),
            "text": text,
            "content": [chatwire.text_content_part(text)] if text else [],
            "isCreatedByUser": False,
            "error": False,
            "unfinished": True,
            "createdAt": now,
            "updatedAt": now,
        }
        seq = 1 + max((int(doc.get("seq") or 0) for doc in docs), default=0)
        final = chatwire.final_frame(
            conversation=conversation,
            request_message=user_message,
            response_message=response_message,
            aborted=True,
        )
        settled = dict(turn)
        settled["status"] = "aborted"
        settled["updatedAt"] = now
        self._store.put_many_multi(
            [
                ("messages", str(response_message["messageId"]), response_message),
                ("turns", stream_id, settled),
                (
                    "turn_events",
                    _event_key(stream_id, seq),
                    {"streamId": stream_id, "seq": seq, "frame": final},
                ),
            ]
        )

    def _turn_doc(self, job: _Job, *, sender: str, status: str | None = None) -> dict[str, Any]:
        return {
            "streamId": job.stream_id,
            "conversationId": job.conversation_id,
            "status": status if status is not None else job.status,
            "generationCreatedAt": job.generation_created_at,
            "userMessageId": job.user_message_id,
            "responseMessageId": job.response_message_id,
            "sender": sender,
            "updatedAt": _now_rfc3339(),
        }


# ---------------------------------------------------------------------- helpers


def _provider_for_endpoint(endpoint: str) -> registry.Provider | None:
    for provider in registry.PROVIDERS:
        key = "anthropic" if provider.id == "anthropic" else provider.label
        if key == endpoint:
            return provider
    return None


def _model_from(payload: dict[str, Any], provider: registry.Provider) -> str:
    params = payload.get("model_parameters")
    model = params.get("model") if isinstance(params, dict) else None
    chosen = str(model or payload.get("model") or provider.default_model or "").strip()
    return chosen or "default"


def _max_tokens_from(payload: dict[str, Any]) -> int:
    """The client sends these TOP-LEVEL on this endpoint family (maxOutputTokens on the
    compact convo); model_parameters is consulted second for the agents-shaped payloads."""
    sources: list[Any] = [payload, payload.get("model_parameters")]
    for source in sources:
        if not isinstance(source, dict):
            continue
        for name in ("maxOutputTokens", "max_tokens", "maxTokens"):
            value = source.get(name)
            if isinstance(value, int) and value > 0:
                return min(value, _MAX_TOKENS_CEILING)
    return _DEFAULT_MAX_TOKENS


def _system_from(payload: dict[str, Any]) -> str | None:
    """The user's own system prompt (promptPrefix) — dropped silently nowhere (L15.3)."""
    prefix = payload.get("promptPrefix")
    if isinstance(prefix, str) and prefix.strip():
        return prefix
    return None


def _title_from(text: str) -> str:
    squeezed = " ".join(text.split())
    if len(squeezed) <= 40:
        return squeezed or "New Chat"
    return squeezed[:40].rsplit(" ", 1)[0] + "…"
