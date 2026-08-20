"""Phase 21: tool dispatch, and the boundary-D drift gate extended to cover DISPATCH.

The property that matters most here is not that each tool works — it is that the set of tools
the model is told about and the set the orchestrator can execute are the same set. A model handed
a tool it cannot call, or an orchestrator holding a tool nobody declared, is boundary D failing
in exactly the way §9c exists to prevent, and neither shows up as a type error.

States enumerated before the tests (trap 43).
  Manifest:      every declared tool has a handler · every handler is declared · the file parses ·
                 a malformed manifest raises rather than defaulting to an improvised one.
  Containment:   ordinary relative path · absolute · `~` · `..` escape · a symlink pointing out ·
                 a HARD LINK (the same bytes under an innocent name) · `.env` by segment ·
                 `.ssh/id_rsa` by segment · `server.pem` by suffix · a legitimate file whose name
                 merely contains a denied word.
  Budgets:       read truncation · a caller asking for MORE than the cap · a caller asking for
                 less · directory entry cap · walk depth cap · search match cap · command timeout ·
                 calls-per-turn cap.
  Approval:      an `auto` tool runs ungranted · a `prompt_once_per_project` tool is refused
                 ungranted · the same tool runs once granted.
  Refusals:      come back as `ok=False` results, never as exceptions, and never look like success.
  L16:           `prove` is declared (so the manifest stays whole) but refuses to be a step.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from tempest.agent import tools
from tempest.agent.tools import Budgets, Dispatcher, ToolError, ToolResult


@pytest.fixture
def shadow(tmp_path: Path) -> Path:
    root = tmp_path / "shadow"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "app.py").write_text("def total(xs):\n    return sum(xs)\n", encoding="utf-8")
    (root / "README.md").write_text("# demo\nnothing to see\n", encoding="utf-8")
    return root


def _d(root: Path, **kw: object) -> Dispatcher:
    return Dispatcher(root=root, **kw)  # type: ignore[arg-type]


class TestTheManifestIsTheOnlyDeclaration:
    def test_every_declared_tool_has_a_handler(self) -> None:
        """Adding a tool in `agent_tools.rs` must break this suite until it is implemented.
        That is the drift gate reaching dispatch, not only shape."""
        declared = set(tools.load_manifest())
        assert declared == set(tools.HANDLERS), (
            f"declared but unhandled: {sorted(declared - set(tools.HANDLERS))}; "
            f"handled but undeclared: {sorted(set(tools.HANDLERS) - declared)}"
        )

    def test_the_six_tools_are_the_ones_boundary_d_declares(self) -> None:
        assert set(tools.load_manifest()) == {
            "read_file",
            "list_dir",
            "search_text",
            "write_file",
            "run_command",
            "prove",
        }

    def test_policies_are_read_from_the_manifest_not_restated(self) -> None:
        """`run_command` is `prompt_once_per_project` in Rust; nothing in Python may soften it."""
        manifest = tools.load_manifest()
        assert manifest["run_command"].policy.needs_grant
        assert not manifest["read_file"].policy.needs_grant
        assert manifest["write_file"].policy.writes_shadow
        assert not manifest["read_file"].policy.writes_shadow

    def test_a_malformed_manifest_raises_rather_than_improvising(self, tmp_path: Path) -> None:
        bad = tmp_path / "agent-tools.json"
        bad.write_text(json.dumps({"protocol_version": 1}), encoding="utf-8")
        with pytest.raises(ToolError, match="not a tool manifest"):
            tools.load_manifest(bad)

    def test_the_committed_manifest_is_what_is_loaded_by_default(self) -> None:
        assert tools.MANIFEST_PATH.name == "agent-tools.json"
        assert tools.MANIFEST_PATH.is_file(), "the committed boundary-D artifact must exist"


class TestContainment:
    def test_an_ordinary_relative_path_reads(self, shadow: Path) -> None:
        got = _d(shadow).call("read_file", {"path": "pkg/app.py"})
        assert got.ok and "def total" in got.content

    @pytest.mark.parametrize("bad", ["/etc/passwd", "~/.ssh/id_rsa"])
    def test_absolute_and_home_paths_are_refused(self, shadow: Path, bad: str) -> None:
        got = _d(shadow).call("read_file", {"path": bad})
        assert not got.ok and "repository-relative" in got.content

    def test_dot_dot_traversal_is_refused(self, shadow: Path) -> None:
        (shadow.parent / "outside.txt").write_text("secret", encoding="utf-8")
        got = _d(shadow).call("read_file", {"path": "../outside.txt"})
        assert not got.ok and "escapes" in got.content

    def test_a_symlink_pointing_out_of_the_worktree_is_refused(self, shadow: Path) -> None:
        (shadow.parent / "outside.txt").write_text("secret", encoding="utf-8")
        (shadow / "link.txt").symlink_to(shadow.parent / "outside.txt")
        got = _d(shadow).call("read_file", {"path": "link.txt"})
        assert not got.ok and "escapes" in got.content
        assert "secret" not in got.content

    def test_a_hard_link_is_refused_because_no_name_rule_can_see_it(self, shadow: Path) -> None:
        """Trap 45, in the agent's tool surface. A hard link IS the file: one inode, two
        directory entries, nothing to follow, and `resolve()` answers the innocent name. The
        only sound rule is that a file with more than one name cannot be judged by the name it
        was requested under."""
        secret = shadow / ".env"
        secret.write_text("SECRET=hunter2\n", encoding="utf-8")
        os.link(secret, shadow / "notes.txt")
        got = _d(shadow).call("read_file", {"path": "notes.txt"})
        assert not got.ok
        assert "hunter2" not in got.content
        assert "more than one name" in got.content

    @pytest.mark.parametrize(
        "path,body",
        [(".env", "SECRET=1"), (".ssh/id_rsa", "PRIVATE"), ("server.pem", "PRIVATE")],
    )
    def test_credential_paths_are_refused(self, shadow: Path, path: str, body: str) -> None:
        target = shadow / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
        got = _d(shadow).call("read_file", {"path": path})
        assert not got.ok and "credential" in got.content
        assert body not in got.content

    def test_a_legitimate_file_whose_name_merely_contains_a_denied_word_is_allowed(
        self, shadow: Path
    ) -> None:
        """`environment.py` is not `.env`. A denylist matched on substrings would refuse half a
        repository and teach the model that the tool is broken."""
        (shadow / "environment.py").write_text("X = 1\n", encoding="utf-8")
        got = _d(shadow).call("read_file", {"path": "environment.py"})
        assert got.ok and "X = 1" in got.content

    def test_writes_land_in_the_shadow_and_nowhere_else(self, shadow: Path) -> None:
        got = _d(shadow).call("write_file", {"path": "pkg/new.py", "contents": "A = 1\n"})
        assert got.ok
        assert (shadow / "pkg" / "new.py").read_text(encoding="utf-8") == "A = 1\n"

    def test_a_write_cannot_escape_the_shadow(self, shadow: Path) -> None:
        got = _d(shadow).call("write_file", {"path": "../escaped.py", "contents": "A = 1\n"})
        assert not got.ok and "escapes" in got.content
        assert not (shadow.parent / "escaped.py").exists()

    def test_the_dispatcher_has_no_second_root_to_reach(self) -> None:
        """L19 as a property of the type, not of a reviewer's attention: there is exactly one
        root field, so the user's checkout cannot be passed in even by mistake."""
        roots = [f for f in Dispatcher.__dataclass_fields__ if "root" in f]
        assert roots == ["root"]


class TestBudgets:
    def test_a_large_file_is_truncated_and_says_so(self, shadow: Path) -> None:
        (shadow / "big.txt").write_text("x" * 5000, encoding="utf-8")
        got = _d(shadow, budgets=Budgets(max_read_bytes=100)).call("read_file", {"path": "big.txt"})
        assert got.ok and got.truncated and len(got.content) == 100

    def test_a_caller_cannot_raise_the_cap_only_lower_it(self, shadow: Path) -> None:
        """`max_bytes` is the model's request. A model asking for more than the budget gets the
        budget — otherwise the bound is advisory, which is not a bound."""
        (shadow / "big.txt").write_text("x" * 5000, encoding="utf-8")
        d = _d(shadow, budgets=Budgets(max_read_bytes=100))
        assert len(d.call("read_file", {"path": "big.txt", "max_bytes": 4000}).content) == 100
        d2 = _d(shadow, budgets=Budgets(max_read_bytes=100))
        assert len(d2.call("read_file", {"path": "big.txt", "max_bytes": 10}).content) == 10

    def test_directory_listings_are_capped(self, shadow: Path) -> None:
        for i in range(50):
            (shadow / f"f{i}.txt").write_text("x", encoding="utf-8")
        got = _d(shadow, budgets=Budgets(max_dir_entries=10)).call("list_dir", {"path": "."})
        assert got.truncated and len(got.content.splitlines()) == 10

    def test_a_recursive_walk_is_bounded_in_depth(self, shadow: Path) -> None:
        deep = shadow / "a" / "b" / "c" / "d" / "e"
        deep.mkdir(parents=True)
        (deep / "buried.txt").write_text("x", encoding="utf-8")
        got = _d(shadow, budgets=Budgets(max_walk_depth=2)).call(
            "list_dir", {"path": ".", "recursive": True}
        )
        assert got.ok
        assert "buried.txt" not in got.content, "depth budget must actually stop the descent"

    def test_search_matches_are_capped(self, shadow: Path) -> None:
        (shadow / "many.py").write_text("hit\n" * 100, encoding="utf-8")
        got = _d(shadow, budgets=Budgets(max_search_matches=5)).call(
            "search_text", {"pattern": "hit"}
        )
        assert got.truncated and len(got.content.splitlines()) == 5

    def test_an_invalid_regex_is_a_refusal_not_a_crash(self, shadow: Path) -> None:
        got = _d(shadow).call("search_text", {"pattern": "([unclosed"})
        assert not got.ok and "invalid pattern" in got.content

    def test_a_binary_file_is_skipped_rather_than_failing_the_search(self, shadow: Path) -> None:
        (shadow / "blob.bin").write_bytes(b"\xff\xfe\x00\x01hit")
        (shadow / "ok.py").write_text("hit\n", encoding="utf-8")
        got = _d(shadow).call("search_text", {"pattern": "hit"})
        assert got.ok and "ok.py" in got.content

    def test_the_number_of_calls_in_a_turn_is_bounded(self, shadow: Path) -> None:
        """An agent that can call tools forever is an unbounded operation (L15.4), and no
        per-call budget bounds it."""
        d = _d(shadow, budgets=Budgets(max_calls_per_turn=3))
        for _ in range(3):
            assert d.call("read_file", {"path": "README.md"}).ok
        exhausted = d.call("read_file", {"path": "README.md"})
        assert not exhausted.ok and "call budget exhausted" in exhausted.content

    def test_a_refused_call_still_counts_against_the_turn_budget(self, shadow: Path) -> None:
        """Otherwise a model can spin forever on refusals, which is the same unbounded loop
        arrived at by a different route."""
        d = _d(shadow, budgets=Budgets(max_calls_per_turn=2))
        assert not d.call("read_file", {"path": "/etc/passwd"}).ok
        assert not d.call("read_file", {"path": "/etc/passwd"}).ok
        assert "call budget exhausted" in d.call("read_file", {"path": "README.md"}).content


class TestApproval:
    def test_an_auto_tool_runs_without_a_grant(self, shadow: Path) -> None:
        assert _d(shadow).call("read_file", {"path": "README.md"}).ok

    def test_a_prompt_tool_is_refused_without_a_grant(self, shadow: Path) -> None:
        got = _d(shadow).call("run_command", {"argv": ["echo", "hi"]})
        assert not got.ok and "requires approval" in got.content

    def test_a_granted_command_is_still_refused_because_nothing_can_contain_it_yet(
        self, shadow: Path
    ) -> None:
        """L19, enforced rather than assumed. This handler used to call `subprocess.run` with the
        user's own uid, environment, network and filesystem, confined only by a working
        directory — while the tool contract declared `writes: shadow_worktree` and
        `touches_network: false`. The refusal is the honest state until F14 (Phase 23) provides a
        tier a shadow worktree can execute inside.
        """
        got = _d(shadow, grants=frozenset({"run_command"})).call(
            "run_command", {"argv": ["echo", "hi"]}
        )
        assert not got.ok
        assert "L19" in got.content and "F14" in got.content

    def test_the_refusal_is_not_a_silent_success(self, shadow: Path) -> None:
        """The one thing that would be worse than refusing: returning `ok` with empty output, so
        a model believes the command ran and reasons from nothing."""
        got = _d(shadow, grants=frozenset({"run_command"})).call("run_command", {"argv": ["ls"]})
        assert not got.ok and got.content.strip()

    def test_argv_is_validated_BEFORE_the_refusal(self, shadow: Path) -> None:
        """A model that hands this tool a shell string should learn that now rather than after
        the capability arrives — and argv-not-a-string is what makes an allowlist analysable."""
        got = _d(shadow, grants=frozenset({"run_command"})).call("run_command", {"argv": "echo hi"})
        assert not got.ok and "already-split" in got.content

    def test_an_empty_argv_is_refused_for_its_own_reason(self, shadow: Path) -> None:
        got = _d(shadow, grants=frozenset({"run_command"})).call("run_command", {"argv": []})
        assert not got.ok and "already-split" in got.content


class TestRefusalsAreValuesNotCrashes:
    def test_an_unknown_tool_is_refused_and_lists_what_exists(self, shadow: Path) -> None:
        got = _d(shadow).call("delete_everything", {})
        assert not got.ok and "unknown tool" in got.content and "read_file" in got.content

    def test_no_refusal_raises(self, shadow: Path) -> None:
        d = _d(shadow)
        for name, args in [
            ("read_file", {"path": "../x"}),
            ("read_file", {"path": "nope.py"}),
            ("list_dir", {"path": "README.md"}),
            ("search_text", {"pattern": "("}),
            ("nope", {}),
        ]:
            got = d.call(name, args)
            assert isinstance(got, ToolResult) and not got.ok

    def test_a_refusal_never_reads_as_success(self, shadow: Path) -> None:
        got = _d(shadow).call("read_file", {"path": "does-not-exist.py"})
        assert not got.ok
        assert not got.truncated, "a refusal is not a truncated success"


class TestProveIsNotAStep:
    def test_prove_is_declared_so_the_manifest_stays_whole(self) -> None:
        assert "prove" in tools.load_manifest()
        assert "prove" in tools.HANDLERS

    def test_but_calling_it_is_refused_with_the_law_named(self, shadow: Path) -> None:
        """L16: the verdict is what TERMINATES a turn. If the model could invoke proving as a
        step it could also decline to, and 'the agent may never bypass the proof gate' would be
        a request rather than a property."""
        got = _d(shadow).call("prove", {})
        assert not got.ok
        assert "L16" in got.content
        assert "never author" in got.content


class TestTheCallCounterIsExact:
    """Found by mutation, not by reading. The counter was incremented before dispatch AND in the
    `except`, so a refusal raised INSIDE a handler cost two units of the turn budget instead of
    one. Every existing budget test exercised EARLY refusals (unknown tool, missing grant), which
    take the other path and hide it — the states were not enumerated, only the lines were run
    (trap 43).
    """

    def test_a_successful_call_costs_exactly_one(self, shadow: Path) -> None:
        d = _d(shadow)
        d.call("read_file", {"path": "README.md"})
        assert d.calls_made == 1

    def test_a_refusal_raised_INSIDE_a_handler_costs_exactly_one(self, shadow: Path) -> None:
        d = _d(shadow)
        assert not d.call("read_file", {"path": "../escape"}).ok
        assert d.calls_made == 1, "a path escape is refused by the handler, and costs one call"

    def test_a_refusal_raised_BEFORE_dispatch_costs_exactly_one(self, shadow: Path) -> None:
        d = _d(shadow)
        assert not d.call("no_such_tool", {}).ok
        assert d.calls_made == 1

    def test_an_ungranted_tool_costs_exactly_one(self, shadow: Path) -> None:
        d = _d(shadow)
        assert not d.call("run_command", {"argv": ["echo", "hi"]}).ok
        assert d.calls_made == 1

    def test_the_budget_admits_exactly_its_number_of_calls(self, shadow: Path) -> None:
        """Off-by-one is the whole risk in a counter that both counts and gates."""
        d = _d(shadow, budgets=Budgets(max_calls_per_turn=3))
        assert [d.call("read_file", {"path": "README.md"}).ok for _ in range(3)] == [True] * 3
        assert not d.call("read_file", {"path": "README.md"}).ok
        assert d.calls_made == 4, "the refused call is still a call"

    def test_handler_refusals_do_not_secretly_halve_the_budget(self, shadow: Path) -> None:
        """The bug in one assertion: with double counting, three in-handler refusals exhausted a
        budget of six."""
        d = _d(shadow, budgets=Budgets(max_calls_per_turn=6))
        for _ in range(3):
            assert not d.call("read_file", {"path": "../escape"}).ok
        assert d.call("read_file", {"path": "README.md"}).ok, "budget was consumed twice per call"


class TestTheStatesTheCoverageGateNamed:
    """Four branches the first draft left unexercised. Each is a real state, not a line to touch:
    a budget that bites mid-walk, a caller narrowing a cap, and a malformed artifact.
    """

    def test_a_recursive_walk_stops_once_it_has_overrun_the_entry_budget(
        self, shadow: Path
    ) -> None:
        """The walk collects breadth-first and must abandon the tree once it has enough — a wide
        repository would otherwise cost an unbounded traversal to produce a bounded answer."""
        for i in range(12):
            sub = shadow / f"dir{i}"
            sub.mkdir()
            for j in range(12):
                (sub / f"f{j}.txt").write_text("x", encoding="utf-8")
        got = _d(shadow, budgets=Budgets(max_dir_entries=5)).call(
            "list_dir", {"path": ".", "recursive": True}
        )
        assert got.ok and got.truncated
        assert len(got.content.splitlines()) == 5

    def test_a_caller_may_narrow_the_search_cap_but_not_widen_it(self, shadow: Path) -> None:
        (shadow / "many.py").write_text("hit\n" * 50, encoding="utf-8")
        narrow = _d(shadow, budgets=Budgets(max_search_matches=20)).call(
            "search_text", {"pattern": "hit", "max_results": 3}
        )
        assert len(narrow.content.splitlines()) == 3 and narrow.truncated
        wide = _d(shadow, budgets=Budgets(max_search_matches=4)).call(
            "search_text", {"pattern": "hit", "max_results": 999}
        )
        assert len(wide.content.splitlines()) == 4, "the host's budget wins"

    def test_a_model_facing_artifact_that_is_not_a_list_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        broken = tmp_path / "agent-tools.anthropic.json"
        broken.write_text(json.dumps({"tools": []}), encoding="utf-8")
        monkeypatch.setattr(tools, "ANTHROPIC_TOOLS_PATH", broken)
        with pytest.raises(ToolError, match="not lists"):
            tools.model_facing_catalog()
