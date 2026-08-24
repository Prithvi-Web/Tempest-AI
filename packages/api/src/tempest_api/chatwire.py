"""The platform chat wire vocabulary — every SSE frame a streamed turn emits (PLAN-V3 C5).

These builders are the ONE place the vendored client's generation protocol is spelled in
engine territory. The shapes are upstream LibreChat's (v0.8.8-rc1 at the vendored commit):
the start ack, then `created` → `on_run_step` → `on_message_delta`* → `on_token_usage`? →
`title`? → `final`, with the abort- and error-finals as the honest terminal variants. Field
names are upstream's contract, not ours to improve — the e2e suite drives the REAL vendored
client against these frames, which is the net that catches a wrong name (a schema we invented
here could only agree with itself).

Two ordering rules are load-bearing and carried by the caller (`chatturn.py`):

- `created` precedes every delta — the client keys everything off it, and a bare
  `on_message_delta` without its `on_run_step` slot is dropped by `useStepHandler`.
- `final` is a PERSISTENCE RECEIPT, not a terminator: both messages are durably saved before
  it is emitted, because the client immediately treats them as authoritative parents for the
  next turn.
"""

from typing import Any

#: Upstream `Constants.NO_PARENT` — the parentMessageId of a conversation's first message.
NO_PARENT = "00000000-0000-0000-0000-000000000000"


#: The one run-step this surface emits per turn: plain text generation. Tool-bearing agent
#: turns (the run_task re-target) add tool_calls steps with their own ids when they land.
def step_id(response_message_id: str) -> str:
    return f"step_{response_message_id}_0"


def created_frame(
    *,
    stream_id: str,
    user_message: dict[str, Any],
) -> dict[str, Any]:
    """The first frame: the persisted user message, echoed so the client anchors the turn."""
    return {"created": True, "message": dict(user_message), "streamId": stream_id}


def run_step_frame(*, response_message_id: str) -> dict[str, Any]:
    """The message_creation step that opens the response's content slot (before any delta)."""
    return {
        "event": "on_run_step",
        "data": {
            "id": step_id(response_message_id),
            "index": 0,
            "type": "message_creation",
            "runId": response_message_id,
            "usage": None,
            "stepDetails": {
                "type": "message_creation",
                "message_creation": {"message_id": response_message_id},
            },
        },
    }


def message_delta_frame(*, response_message_id: str, text: str) -> dict[str, Any]:
    return message_delta_frame_for_step(step_id=step_id(response_message_id), text=text)


def message_delta_frame_for_step(*, step_id: str, text: str) -> dict[str, Any]:
    """The delta shape addressed by its STEP id directly — what the read-side delta
    coalescing (LC06) rebuilds, since a merged frame keeps its run's step, not a new one."""
    return {
        "event": "on_message_delta",
        "data": {
            "id": step_id,
            "delta": {"content": [{"type": "text", "text": text}]},
        },
    }


def token_usage_frame(
    *,
    response_message_id: str,
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    seq: int = 0,
) -> dict[str, Any]:
    """Measured usage, straight from the provider's own stream (L21: never estimated).

    `seq` is the per-run emission counter, and it is load-bearing for exactly the shape C5
    introduced: ONE `runId` (the response message id) now spans MANY model calls, because a
    tool-bearing turn loops. The vendored client folds usage under
    `runId != null && seq != null ? `${runId}:${seq}` : JSON.stringify(data)`
    (`useUsageHandler.ts`), and the field's own upstream doc says what it is for — "keeps
    identical payloads from distinct model calls unique".

    Without it the key degrades to the payload itself, so two calls in one turn that happen
    to report the same counts fold into ONE and the turn under-reports its own spend. Two
    identical counts is not a corner case: it is what a scripted peer produces every time,
    and small tool-loop turns land on the same numbers routinely.
    """
    return {
        "event": "on_token_usage",
        "data": {
            "runId": response_message_id,
            "seq": seq,
            "provider": provider,
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        },
    }


def final_frame(
    *,
    conversation: dict[str, Any],
    request_message: dict[str, Any],
    response_message: dict[str, Any],
    aborted: bool = False,
) -> dict[str, Any]:
    """The terminal frame. With `aborted`, the response rides out `unfinished` — the partial
    text the user watched is the truth the reload must show, never a blank."""
    frame: dict[str, Any] = {
        "final": True,
        "conversation": dict(conversation),
        "title": conversation.get("title"),
        "requestMessage": dict(request_message),
        "responseMessage": dict(response_message),
    }
    if aborted:
        frame["aborted"] = True
    return frame


def text_content_part(text: str) -> dict[str, Any]:
    """A persisted message's content part (the delta shape is flat text; the stored shape
    wraps it — upstream stores `{type, text: {value}}` on final messages)."""
    return {"type": "text", "text": {"value": text}}


def error_content_part(message: str) -> dict[str, Any]:
    """An in-band error the client renders inside the message, preserving any partial text
    part beside it — the content-part route, which keeps what already streamed."""
    return {"type": "error", "error": message}
