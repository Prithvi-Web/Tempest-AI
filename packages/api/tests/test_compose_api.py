"""`POST /v1/local/compose` end to end — real repo, real hunks, real proof (L4).

The composer's third column is the reason F12 is not a diff viewer, so the tests are about the
column rather than the plumbing: that a row's verdict is about THAT row, that a row the engine
could not speak about says so in words, and that accepting a subset is answered by proving the
subset rather than by filtering the whole change's evidence.

States enumerated before the tests (trap 43): every hunk accepted · a subset accepted · nothing
accepted · an id that does not exist · a repo that is not a repo · a ref that does not resolve ·
a hunk that changes no executable symbol.
"""

import subprocess
from pathlib import Path
from typing import Any

import pytest

# Two changes, far enough apart that `git diff --unified=3` does not coalesce them into one
# hunk (trap 59): a function whose behaviour really moves, and a constant that nothing executes.
_BASE = """def total(xs):
    return sum(xs)


def spacer_one():
    return 1


def spacer_two():
    return 2


def spacer_three():
    return 3


CONSTANT = 1
"""
_HEAD = _BASE.replace("return sum(xs)", "return sum(xs) + 1").replace(
    "CONSTANT = 1", "CONSTANT = 2"
)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "composed"
    root.mkdir()

    def git(*args: str) -> None:
        subprocess.run(
            ["git", "-C", str(root), *args],
            check=True,
            capture_output=True,
            env={
                "GIT_AUTHOR_NAME": "t",
                "GIT_AUTHOR_EMAIL": "t@t",
                "GIT_COMMITTER_NAME": "t",
                "GIT_COMMITTER_EMAIL": "t@t",
                "PATH": "/usr/bin:/bin",
                "HOME": str(root),
            },
        )

    git("init", "-b", "main")
    (root / ".tempest-first-party").write_text("tempest-first-party-fixture-v1\n")
    (root / "app.py").write_text(_BASE)
    git("add", "-A")
    git("commit", "-m", "base", "--no-gpg-sign")
    git("branch", "base")
    (root / "app.py").write_text(_HEAD)
    git("add", "-A")
    git("commit", "-m", "head", "--no-gpg-sign")
    git("branch", "head")
    return root


def _compose(api: Any, repo: Path, accepted: list[str] | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "repo_path": str(repo),
        "base": "base",
        "head": "head",
        "max_inputs": 8,
    }
    if accepted is not None:
        body["accepted"] = accepted
    resp = api.client.post("/v1/local/compose", json=body)
    assert resp.status_code == 200, resp.text
    return dict(resp.json())


class TestTheRowsAndTheirColumn:
    def test_every_hunk_becomes_a_row_carrying_its_own_verdict(self, api: Any, repo: Path) -> None:
        view = _compose(api, repo)
        assert len(view["hunks"]) == 2, "the function and the constant are separate rows"
        by_verdict = {row["verdict"] for row in view["hunks"]}
        assert "DIVERGENT" in by_verdict, "the behaviour change is on the record"
        diverging = [r for r in view["hunks"] if r["verdict"] == "DIVERGENT"]
        assert diverging[0]["qualnames"] == ["total"]
        assert diverging[0]["divergence_count"] >= 1

    def test_a_row_the_engine_cannot_speak_about_says_so_in_words(
        self, api: Any, repo: Path
    ) -> None:
        """A blank cell next to a code change reads as reassurance nobody produced."""
        view = _compose(api, repo)
        quiet = [r for r in view["hunks"] if not r["qualnames"]]
        assert len(quiet) == 1
        assert quiet[0]["verdict"] == "UNPROVEN"
        assert "no executable symbol" in quiet[0]["reason"]

    def test_a_row_carries_the_patch_git_itself_produced(self, api: Any, repo: Path) -> None:
        view = _compose(api, repo)
        assert all(r["patch"].startswith("diff --git ") for r in view["hunks"])

    def test_the_answer_names_the_bundle_it_came_from(self, api: Any, repo: Path) -> None:
        view = _compose(api, repo)
        assert ".." in view["bundle_id"], "L1: the claim carries its artifact"
        assert view["selection_head"]


class TestAcceptingASubset:
    def test_accepting_only_the_constant_proves_THAT_change(self, api: Any, repo: Path) -> None:
        """The reason a subset is proved rather than filtered: this tree is a change no other
        request in the session has executed (ADR-0061)."""
        everything = _compose(api, repo)
        constant = next(r for r in everything["hunks"] if not r["qualnames"])
        view = _compose(api, repo, [constant["id"]])
        assert [r["accepted"] for r in view["hunks"]].count(True) == 1
        assert all(r["verdict"] == "UNPROVEN" for r in view["hunks"]), (
            "nothing executable was accepted, so nothing was proved to change"
        )
        assert view["selection_head"] != everything["selection_head"]

    def test_accepting_nothing_is_a_real_request_not_an_empty_one(
        self, api: Any, repo: Path
    ) -> None:
        """`accepted: []` is the user rejecting everything, and is a different question from
        `accepted: null`, which is the state the composer opens in."""
        view = _compose(api, repo, [])
        assert all(not r["accepted"] for r in view["hunks"])
        assert view["hunks"], "the rows are still shown — the user has to see what they rejected"

    def test_an_id_that_does_not_exist_accepts_nothing_rather_than_guessing(
        self, api: Any, repo: Path
    ) -> None:
        view = _compose(api, repo, ["not-a-real-hunk-id"])
        assert all(not r["accepted"] for r in view["hunks"])


class TestRefusals:
    def test_a_path_that_is_not_a_repository_is_a_400_with_a_code(
        self, api: Any, tmp_path: Path
    ) -> None:
        resp = api.client.post(
            "/v1/local/compose",
            json={"repo_path": str(tmp_path / "nope"), "base": "a", "head": "b"},
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "REPO_NOT_FOUND"

    def test_a_ref_that_does_not_resolve_is_a_400_with_a_code(self, api: Any, repo: Path) -> None:
        resp = api.client.post(
            "/v1/local/compose",
            json={"repo_path": str(repo), "base": "base", "head": "no-such-ref"},
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "REF_NOT_FOUND"

    def test_a_max_inputs_of_zero_is_refused_by_the_schema(self, api: Any, repo: Path) -> None:
        resp = api.client.post(
            "/v1/local/compose",
            json={"repo_path": str(repo), "base": "base", "head": "head", "max_inputs": 0},
        )
        assert resp.status_code == 422
