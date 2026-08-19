"""Phase 19.4 pins: the agent journal and one-keystroke undo (L20).

The master prompt's gate is "undo restores any state", so the centrepiece here is a property
test over randomised action sequences: whatever the agent did, undoing it all returns the tree
byte-for-byte. Everything else pins a specific promise — append-only, durable across a restart,
ordered, idempotent, and self-healing when a mutation fails halfway.
"""

import json
import random
from pathlib import Path

import pytest

from tempest.agent import journal as jr


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "work"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "a.py").write_text("A0\n")
    (root / "pkg" / "b.py").write_text("B0\n")
    return root


def _state(root: Path) -> dict[str, str]:
    """Every file under the tree except the journal itself."""
    return {
        str(p.relative_to(root)): p.read_text()
        for p in sorted(root.rglob("*"))
        if p.is_file() and ".tempest" not in p.parts
    }


def _apply(j: jr.Journal, root: Path, kind: str, ops: list[tuple[str, str | None]]) -> jr.Entry:
    """Run one journalled action: (relpath, contents) writes; contents None deletes."""
    with j.record(kind, f"{len(ops)} change(s)", [rel for rel, _ in ops]) as entry:
        for rel, contents in ops:
            target = root / rel
            if contents is None:
                if target.exists():
                    target.unlink()
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(contents)
    return entry


class TestRecording:
    def test_an_action_is_recorded_and_pending(self, repo: Path) -> None:
        j = jr.Journal(repo)
        _apply(j, repo, jr.KIND_EDIT, [("pkg/a.py", "A1\n")])
        assert [e.summary for e in j.pending()] == ["1 change(s)"]
        assert (repo / "pkg" / "a.py").read_text() == "A1\n"

    def test_an_empty_journal_is_empty_not_an_error(self, repo: Path) -> None:
        assert jr.Journal(repo).entries() == []
        assert jr.Journal(repo).pending() == []

    def test_the_log_is_append_only_across_undo(self, repo: Path) -> None:
        """Undo appends a record; it never rewrites what already happened (L14's posture)."""
        j = jr.Journal(repo)
        _apply(j, repo, jr.KIND_EDIT, [("pkg/a.py", "A1\n")])
        first = (j.root / "log.jsonl").read_text()
        j.undo_last()
        after = (j.root / "log.jsonl").read_text()
        assert after.startswith(first), "an existing log line was rewritten"
        assert json.loads(after.splitlines()[-1])["undo"]

    def test_every_kind_uses_the_same_reversal_mechanism(self, repo: Path) -> None:
        """A command's side effects are undoable exactly like an edit's (L20)."""
        j = jr.Journal(repo)
        _apply(j, repo, jr.KIND_COMMAND, [("pkg/generated.py", "GEN\n")])
        assert (repo / "pkg" / "generated.py").exists()
        j.undo_last()
        assert not (repo / "pkg" / "generated.py").exists()


class TestUndo:
    def test_undo_restores_modified_content(self, repo: Path) -> None:
        j = jr.Journal(repo)
        before = _state(repo)
        _apply(j, repo, jr.KIND_EDIT, [("pkg/a.py", "A1\n")])
        j.undo_last()
        assert _state(repo) == before

    def test_undo_deletes_a_file_the_action_created(self, repo: Path) -> None:
        j = jr.Journal(repo)
        _apply(j, repo, jr.KIND_EDIT, [("pkg/new.py", "N\n")])
        j.undo_last()
        assert not (repo / "pkg" / "new.py").exists()

    def test_undo_restores_a_file_the_action_deleted(self, repo: Path) -> None:
        j = jr.Journal(repo)
        _apply(j, repo, jr.KIND_EDIT, [("pkg/a.py", None)])
        assert not (repo / "pkg" / "a.py").exists()
        j.undo_last()
        assert (repo / "pkg" / "a.py").read_text() == "A0\n"

    def test_undo_covers_a_multi_file_action_as_one_unit(self, repo: Path) -> None:
        """L20 says undo works for multi-file edits — one keystroke, not one per file."""
        j = jr.Journal(repo)
        before = _state(repo)
        _apply(j, repo, jr.KIND_EDIT, [("pkg/a.py", "A1\n"), ("pkg/b.py", "B1\n"), ("c.py", "C\n")])
        j.undo_last()
        assert _state(repo) == before

    def test_undo_last_walks_backwards_through_the_stack(self, repo: Path) -> None:
        j = jr.Journal(repo)
        _apply(j, repo, jr.KIND_EDIT, [("pkg/a.py", "A1\n")])
        _apply(j, repo, jr.KIND_EDIT, [("pkg/a.py", "A2\n")])
        j.undo_last()
        assert (repo / "pkg" / "a.py").read_text() == "A1\n"
        j.undo_last()
        assert (repo / "pkg" / "a.py").read_text() == "A0\n"

    def test_undo_is_idempotent(self, repo: Path) -> None:
        j = jr.Journal(repo)
        entry = _apply(j, repo, jr.KIND_EDIT, [("pkg/a.py", "A1\n")])
        j.undo(entry.id)
        j.undo(entry.id)
        assert (repo / "pkg" / "a.py").read_text() == "A0\n"

    def test_undo_last_on_an_empty_stack_returns_none(self, repo: Path) -> None:
        assert jr.Journal(repo).undo_last() is None

    def test_undoing_an_unknown_entry_says_so(self, repo: Path) -> None:
        with pytest.raises(jr.JournalError, match="no journal entry"):
            jr.Journal(repo).undo("deadbeef")

    def test_out_of_order_undo_is_refused_because_it_would_lose_newer_bytes(
        self, repo: Path
    ) -> None:
        """Undoing entry 1 while entry 2 still applies would write a stale pre-image over it."""
        j = jr.Journal(repo)
        first = _apply(j, repo, jr.KIND_EDIT, [("pkg/a.py", "A1\n")])
        _apply(j, repo, jr.KIND_EDIT, [("pkg/a.py", "A2\n")])
        with pytest.raises(jr.JournalError, match="newer action"):
            j.undo(first.id)
        assert (repo / "pkg" / "a.py").read_text() == "A2\n", "the refusal changed nothing"


class TestDurability:
    def test_undo_survives_a_restart(self, repo: Path) -> None:
        """A fresh Journal object holds no memory — disk is the source of truth (P2's case)."""
        _apply(jr.Journal(repo), repo, jr.KIND_EDIT, [("pkg/a.py", "A1\n")])
        reopened = jr.Journal(repo)
        assert len(reopened.pending()) == 1
        reopened.undo_last()
        assert (repo / "pkg" / "a.py").read_text() == "A0\n"

    def test_history_is_readable_after_a_restart_including_undone_actions(self, repo: Path) -> None:
        j = jr.Journal(repo)
        _apply(j, repo, jr.KIND_EDIT, [("pkg/a.py", "A1\n")])
        j.undo_last()
        reopened = jr.Journal(repo)
        assert len(reopened.entries()) == 1
        assert reopened.entries()[0].undone is True
        assert reopened.pending() == []


class TestFailureRollback:
    def test_a_failing_action_rolls_itself_back(self, repo: Path) -> None:
        """A half-applied agent action must never survive the error that interrupted it."""
        j = jr.Journal(repo)
        before = _state(repo)
        with (
            pytest.raises(RuntimeError),
            j.record(jr.KIND_EDIT, "boom", ["pkg/a.py", "pkg/b.py"]),
        ):
            (repo / "pkg" / "a.py").write_text("HALF\n")
            raise RuntimeError("the tool died mid-write")
        assert _state(repo) == before
        assert j.pending() == [], "a failed action must not sit in the undo stack"


class TestUndoRestoresAnyState:
    """The master prompt's Phase 19 gate: *undo restores any state*.

    A randomised sequence of writes and deletes across overlapping files, then undo everything
    in order. Any pre-image bug — a missed file, a wrong existence flag, an ordering mistake —
    shows up as a tree that does not match where it started.
    """

    @pytest.mark.parametrize("seed", range(12))
    def test_random_action_sequences_undo_exactly(self, tmp_path: Path, seed: int) -> None:
        rng = random.Random(seed)
        root = tmp_path / f"r{seed}"
        (root / "pkg").mkdir(parents=True)
        names = ["pkg/a.py", "pkg/b.py", "pkg/c.py", "top.py"]
        for rel in names[: rng.randint(1, len(names))]:
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text(f"seed{seed}:{rel}\n")

        j = jr.Journal(root)
        before = _state(root)

        for step in range(rng.randint(1, 6)):
            touched = rng.sample(names, rng.randint(1, len(names)))
            ops: list[tuple[str, str | None]] = [
                (rel, None if rng.random() < 0.3 else f"s{seed}-step{step}-{rel}\n")
                for rel in touched
            ]
            _apply(j, root, jr.KIND_EDIT, ops)

        assert len(j.pending()) >= 1
        while j.undo_last() is not None:
            pass
        assert _state(root) == before, f"undo did not restore the tree for seed {seed}"
        assert j.pending() == []


class TestTolerantReader:
    """The log is a file on disk, so it can be hand-edited, truncated, or appended to.

    Trap 37's lesson applied to the journal: a stored record is a claim, not a fact. Undo must
    keep working through junk rather than crashing — a reader that throws takes the user's undo
    away at exactly the moment they need it.
    """

    def test_blank_and_non_object_lines_are_ignored(self, repo: Path) -> None:
        j = jr.Journal(repo)
        entry = _apply(j, repo, jr.KIND_EDIT, [("pkg/a.py", "A1\n")])
        with (j.root / "log.jsonl").open("a", encoding="utf-8") as fh:
            fh.write("\n")  # a stray blank line
            fh.write("   \n")  # whitespace only
            fh.write('"a bare string, not a record"\n')
            fh.write("12345\n")  # a bare number
        reopened = jr.Journal(repo)
        assert [e.id for e in reopened.pending()] == [entry.id]
        reopened.undo_last()
        assert (repo / "pkg" / "a.py").read_text() == "A0\n"
