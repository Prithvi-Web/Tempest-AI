"""Phase 21: structured tool calling, on BOTH wires, against real loopback peers (L4).

Fifteen of Tempest's sixteen providers speak the OpenAI shape and one speaks Anthropic's, so a
parser exercised on one wire is a parser exercised on a minority of the fleet. Both are driven
here over real HTTP against a real socket — nothing monkeypatched, because the thing under test
IS the wire format.

The two shapes disagree in exactly the ways that bite:
  * Anthropic returns `tool_use` blocks inside `content` with `input` already an OBJECT;
    OpenAI nests under `function` and sends `arguments` as a JSON **string**.
  * Anthropic says `stop_reason: "tool_use"`; OpenAI says `finish_reason: "tool_calls"`.
A turn loop written against either spelling would be a per-provider branch, which §7 forbids in
feature code — so `Completion.stop_reason` is normalised and this file pins that.

States enumerated before the tests (trap 43): no tool call · one · several · arguments that are
an object · arguments that are a JSON string · arguments that are malformed JSON · arguments
that decode to a non-object · a text answer alongside a call · the request actually CARRYING the
committed tool definitions · a peer that returns calls without the matching stop label.
"""

from __future__ import annotations

from typing import Any

import pytest

from tempest.agent.tools import model_facing_catalog
from tempest.inference.client import Message, ToolCall, complete
from tempest.inference.providers import get

from ..helpers_fake_anthropic import (
    FakeAnthropic,
    FakeOpenAI,
    fake_anthropic_server,
    fake_openai_server,
)

_ASK = [Message(role="user", content="read the readme")]


def _env(url: str, *, anthropic: bool) -> dict[str, str]:
    """Point the provider at the loopback peer.

    The override name comes from `Provider.base_url_env()` rather than a literal: an earlier
    draft guessed `ANTHROPIC_BASE_URL`, which the client does not read, so every Anthropic test
    silently went to the REAL api.anthropic.com and failed with a 401. A test that reaches the
    public internet is a test that can pass for the wrong reason, cost money, and leak — asking
    the provider row for the name it actually honours makes that unrepresentable.
    """
    provider = get("anthropic" if anthropic else "openai")
    return {provider.env_var: "sk-test-not-a-real-key", provider.base_url_env(): url}


#: OpenAI ships no default model on purpose (model ids change faster than a pinned table stays
#: honest), so every call names one.
_OPENAI_MODEL = "gpt-fake"


class TestTheAnthropicWire:
    def test_a_tool_use_block_becomes_a_structured_call(self) -> None:
        fake = FakeAnthropic()
        fake.tool_uses = [{"name": "read_file", "input": {"path": "README.md"}}]
        with fake_anthropic_server(fake) as url:
            got = complete("anthropic", _ASK, env=_env(url, anthropic=True))
        assert len(got.tool_calls) == 1
        call = got.tool_calls[0]
        assert call.name == "read_file"
        assert call.arguments == {"path": "README.md"}
        assert got.stop_reason == "tool_use"

    def test_several_calls_arrive_in_order(self) -> None:
        fake = FakeAnthropic()
        fake.tool_uses = [
            {"name": "list_dir", "input": {"path": "."}},
            {"name": "read_file", "input": {"path": "a.py"}},
        ]
        with fake_anthropic_server(fake) as url:
            got = complete("anthropic", _ASK, env=_env(url, anthropic=True))
        assert [c.name for c in got.tool_calls] == ["list_dir", "read_file"]

    def test_prose_alongside_a_call_is_kept_as_text(self) -> None:
        """The model's narration and its request are different fields and must not merge —
        L17: model text is narration, never evidence, and never an instruction to the host."""
        fake = FakeAnthropic()
        fake.reply_text = "Let me look at the readme first."
        fake.tool_uses = [{"name": "read_file", "input": {"path": "README.md"}}]
        with fake_anthropic_server(fake) as url:
            got = complete("anthropic", _ASK, env=_env(url, anthropic=True))
        assert got.text == "Let me look at the readme first."
        assert got.tool_calls[0].name == "read_file"

    def test_a_plain_answer_carries_no_calls_and_ends_the_turn(self) -> None:
        fake = FakeAnthropic()
        fake.reply_text = "done"
        with fake_anthropic_server(fake) as url:
            got = complete("anthropic", _ASK, env=_env(url, anthropic=True))
        assert got.tool_calls == ()
        assert got.stop_reason == "end"


class TestTheOpenAiWire:
    def test_a_function_call_becomes_the_same_structured_call(self) -> None:
        """Same `ToolCall` out of a completely different shape — that is the point of two wires
        and no per-provider branch."""
        fake = FakeOpenAI()
        fake.tool_calls = [{"name": "read_file", "arguments": {"path": "README.md"}}]
        with fake_openai_server(fake) as url:
            got = complete("openai", _ASK, env=_env(url, anthropic=False), model=_OPENAI_MODEL)
        assert len(got.tool_calls) == 1
        assert got.tool_calls[0].name == "read_file"
        assert got.tool_calls[0].arguments == {"path": "README.md"}
        assert got.stop_reason == "tool_use"

    def test_arguments_arrive_decoded_not_as_a_json_string(self) -> None:
        """OpenAI sends `arguments` as a string. Decoding it once, here, means no caller can
        forget to — and a caller that forgot would pass a string where a mapping is expected and
        dispatch it as if it were valid."""
        fake = FakeOpenAI()
        fake.tool_calls = [{"name": "write_file", "arguments": {"path": "a.py", "contents": "X"}}]
        with fake_openai_server(fake) as url:
            got = complete("openai", _ASK, env=_env(url, anthropic=False), model=_OPENAI_MODEL)
        args: Any = got.tool_calls[0].arguments
        assert isinstance(args, dict)
        assert args["contents"] == "X"

    def test_malformed_arguments_are_dropped_not_passed_on_empty(self) -> None:
        """An empty `{}` would read downstream as "this tool, with no arguments" — a DIFFERENT
        request from the one the model made, dispatched as though it were valid. Dropping leaves
        the model a turn that did nothing, which it can see."""
        fake = FakeOpenAI()
        fake.tool_calls = [{"name": "read_file", "arguments": {}}]
        fake.raw_arguments = "{not json"
        with fake_openai_server(fake) as url:
            got = complete("openai", _ASK, env=_env(url, anthropic=False), model=_OPENAI_MODEL)
        assert got.tool_calls == ()

    def test_arguments_that_decode_to_a_non_object_are_dropped(self) -> None:
        fake = FakeOpenAI()
        fake.tool_calls = [{"name": "read_file", "arguments": {}}]
        fake.raw_arguments = '"just a string"'
        with fake_openai_server(fake) as url:
            got = complete("openai", _ASK, env=_env(url, anthropic=False), model=_OPENAI_MODEL)
        assert got.tool_calls == ()

    def test_a_plain_answer_carries_no_calls_and_ends_the_turn(self) -> None:
        fake = FakeOpenAI()
        fake.reply_text = "done"
        with fake_openai_server(fake) as url:
            got = complete("openai", _ASK, env=_env(url, anthropic=False), model=_OPENAI_MODEL)
        assert got.tool_calls == ()
        assert got.stop_reason == "end"


class TestTheRequestCarriesTheCommittedDefinitions:
    """What the model is TOLD is the other half of boundary D, and it is checkable here."""

    def test_the_anthropic_request_carries_the_committed_anthropic_shape(self) -> None:
        fake = FakeAnthropic()
        fake.reply_text = "ok"
        catalog = model_facing_catalog()
        with fake_anthropic_server(fake) as url:
            complete("anthropic", _ASK, env=_env(url, anthropic=True), tools=catalog)
        sent: Any = fake.requests[0]["tools"]
        assert [t["name"] for t in sent] == [t["name"] for t in catalog.anthropic]
        assert "input_schema" in sent[0], "the Anthropic envelope, verbatim"

    def test_the_openai_request_carries_the_committed_openai_shape(self) -> None:
        fake = FakeOpenAI()
        fake.reply_text = "ok"
        catalog = model_facing_catalog()
        with fake_openai_server(fake) as url:
            complete(
                "openai", _ASK, env=_env(url, anthropic=False), model=_OPENAI_MODEL, tools=catalog
            )
        sent: Any = fake.requests[0]["tools"]
        assert [t["function"]["name"] for t in sent] == [
            t["function"]["name"] for t in catalog.openai
        ]
        assert sent[0]["type"] == "function", "the OpenAI envelope, verbatim"

    def test_no_tools_means_no_tools_key(self) -> None:
        """A request that always carried the key would offer tools to a call that must not have
        them — the narrative pass (ADR-0029) explains evidence and must never be able to act."""
        fake = FakeAnthropic()
        fake.reply_text = "ok"
        with fake_anthropic_server(fake) as url:
            complete("anthropic", _ASK, env=_env(url, anthropic=True))
        assert "tools" not in fake.requests[0]

    def test_the_catalog_cross_checks_both_wires_against_the_manifest(self) -> None:
        """Three artifacts, one Rust declaration. A silent divergence between them is boundary D
        failing in the exact way §9c names, and it is not a type error."""
        catalog = model_facing_catalog()
        from tempest.agent.tools import load_manifest

        canonical = set(load_manifest())
        assert {t["name"] for t in catalog.anthropic} == canonical
        assert {t["function"]["name"] for t in catalog.openai} == canonical

    def test_a_divergent_artifact_is_refused_rather_than_used(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import json as _json

        from tempest.agent import tools as agent_tools

        short = tmp_path / "agent-tools.anthropic.json"
        full: Any = _json.loads(agent_tools.ANTHROPIC_TOOLS_PATH.read_text(encoding="utf-8"))
        short.write_text(_json.dumps(full[:-1]), encoding="utf-8")
        monkeypatch.setattr(agent_tools, "ANTHROPIC_TOOLS_PATH", short)
        with pytest.raises(agent_tools.ToolError, match="disagree with the manifest"):
            agent_tools.model_facing_catalog()


class TestToolResultsGoBackInTheRealWireShape:
    """A turn loop is only a loop if the RESULT reaches the model. Both wires reject a result
    that is not preceded by the call it answers, so the assistant turn replays its own calls —
    a 400 from that omission reads like a model error and is actually ours.
    """

    def _round_trip(self, *, anthropic: bool) -> Any:
        call = ToolCall(id="call_1", name="read_file", arguments={"path": "README.md"})
        history = [
            Message(role="user", content="read the readme"),
            Message(role="assistant", content="looking", tool_calls=(call,)),
            Message(role="user", content="# demo", tool_result_for="call_1"),
        ]
        if anthropic:
            fake = FakeAnthropic()
            fake.reply_text = "done"
            with fake_anthropic_server(fake) as url:
                complete("anthropic", history, env=_env(url, anthropic=True))
            return fake.requests[0]["messages"]
        fake_o = FakeOpenAI()
        fake_o.reply_text = "done"
        with fake_openai_server(fake_o) as url:
            complete("openai", history, env=_env(url, anthropic=False), model=_OPENAI_MODEL)
        return fake_o.requests[0]["messages"]

    def test_the_anthropic_shape(self) -> None:
        sent: Any = self._round_trip(anthropic=True)
        assistant = sent[1]
        assert assistant["role"] == "assistant"
        kinds = [b["type"] for b in assistant["content"]]
        assert kinds == ["text", "tool_use"]
        assert assistant["content"][1]["id"] == "call_1"
        assert assistant["content"][1]["input"] == {"path": "README.md"}

        result = sent[2]
        assert result["role"] == "user", "Anthropic carries a result as a USER turn"
        assert result["content"][0]["type"] == "tool_result"
        assert result["content"][0]["tool_use_id"] == "call_1"
        assert result["content"][0]["content"] == "# demo"

    def test_the_openai_shape(self) -> None:
        sent: Any = self._round_trip(anthropic=False)
        assistant = sent[1]
        assert assistant["tool_calls"][0]["id"] == "call_1"
        assert assistant["tool_calls"][0]["function"]["name"] == "read_file"
        # OpenAI carries arguments as a STRING on the way out too, not only on the way back.
        assert assistant["tool_calls"][0]["function"]["arguments"] == '{"path": "README.md"}'

        result = sent[2]
        assert result["role"] == "tool", "OpenAI carries a result under its own role"
        assert result["tool_call_id"] == "call_1"
        assert result["content"] == "# demo"

    def test_an_ordinary_conversation_is_unchanged_on_both_wires(self) -> None:
        """Every existing caller passes plain messages; none of them may change shape."""
        plain = [Message(role="user", content="hello")]
        fake = FakeAnthropic()
        fake.reply_text = "hi"
        with fake_anthropic_server(fake) as url:
            complete("anthropic", plain, env=_env(url, anthropic=True))
        assert fake.requests[0]["messages"] == [{"role": "user", "content": "hello"}]

        fake_o = FakeOpenAI()
        fake_o.reply_text = "hi"
        with fake_openai_server(fake_o) as url:
            complete("openai", plain, env=_env(url, anthropic=False), model=_OPENAI_MODEL)
        assert fake_o.requests[0]["messages"] == [{"role": "user", "content": "hello"}]


class TestAPeerThatSendsSomethingMalformed:
    """Every shape below is a real thing a proxy, a gateway or a half-implemented local runner
    emits. None of them may crash the turn loop, and none may be silently read as a valid call —
    a dropped call leaves the model a turn that did nothing, which it can see and retry.

    Driven through the parser directly: constructing these over HTTP would mean teaching the fake
    peers to be wrong in eight different ways, and the thing under test is the parser.
    """

    def _provider(self, anthropic: bool) -> Any:
        return get("anthropic" if anthropic else "openai")

    @pytest.mark.parametrize("anthropic", [True, False])
    def test_a_response_that_is_not_an_object_yields_no_calls(self, anthropic: bool) -> None:
        from tempest.inference.client import _stop_reason, _tool_calls

        for document in ("a string", ["a", "list"], None, 7):
            assert _tool_calls(self._provider(anthropic), document) == ()
            assert _stop_reason(self._provider(anthropic), document, ()) == ""

    def test_an_anthropic_tool_use_whose_input_is_not_an_object_is_dropped(self) -> None:
        from tempest.inference.client import _tool_calls

        document = {
            "content": [
                {"type": "tool_use", "id": "1", "name": "read_file", "input": "not an object"},
                {"type": "tool_use", "id": "2", "name": "read_file", "input": {"path": "a"}},
            ]
        }
        got = _tool_calls(self._provider(True), document)
        assert [c.id for c in got] == ["2"], "the malformed one is dropped, the good one survives"

    def test_an_openai_message_that_is_not_an_object_yields_no_calls(self) -> None:
        from tempest.inference.client import _tool_calls

        assert _tool_calls(self._provider(False), {"choices": [{"message": "oops"}]}) == ()

    def test_an_openai_call_that_is_not_an_object_is_dropped(self) -> None:
        from tempest.inference.client import _tool_calls

        document = {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            "not an object",
                            {"id": "2", "function": {"name": "read_file", "arguments": "{}"}},
                        ]
                    }
                }
            ]
        }
        assert [c.id for c in _tool_calls(self._provider(False), document)] == ["2"]

    def test_an_openai_call_whose_function_is_not_an_object_is_dropped(self) -> None:
        from tempest.inference.client import _tool_calls

        document = {"choices": [{"message": {"tool_calls": [{"id": "1", "function": "oops"}]}}]}
        assert _tool_calls(self._provider(False), document) == ()

    def test_an_openai_response_with_no_choices_yields_no_calls(self) -> None:
        from tempest.inference.client import _tool_calls

        assert _tool_calls(self._provider(False), {"choices": []}) == ()
        assert _tool_calls(self._provider(False), {"choices": ["not an object"]}) == ()
