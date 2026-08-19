"""The agent journal — **every agent action is reversible** (L20).

L20 says one-keystroke undo for any agent change, "journalled, not 'hopefully git has it'". That
phrasing is precise and load-bearing: git can only restore what was committed, and the state a
user most wants back is usually the uncommitted one they had five seconds ago. So this journal
stores **pre-images**, not refs.

Three properties make it trustworthy rather than merely present:

**Append-only.** Undoing an entry does not rewrite history; it appends an `undo` record. The log
is therefore a complete account of what happened, including the undos — the same tamper-evident
posture L14 requires of the audit log. Nothing already written is ever edited.

**Durable and stateless.** The log is a JSONL file plus a directory of pre-images. Every query is
answered by reading disk, so undo still works after a crash, a restart, or a machine sleep — the
case P2 (resumable turns) cares about, and the case an in-memory undo stack fails.

**Ordered.** `undo_last()` takes the most recent *pending* entry, never an arbitrary one, because
undoing out of order resurrects stale bytes: if entry 1 and entry 2 both touched `a.py`, undoing
1 first would write the pre-image of 1 over the newer content from 2 and silently lose it.
Out-of-order undo is available by id, but only ever after the entries above it are undone.

Scope note: `record()` is the substrate the orchestrator (Phase 21) and the sandboxed terminal
(F14, Phase 23) write through. It already carries command entries so that terminal side effects
Tempest initiates are journalled the moment that surface exists, rather than retrofitted.
"""

import json
import shutil
import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_JOURNAL_DIR = Path(".tempest") / "agent" / "journal"
_LOG = "log.jsonl"
_PRE = "pre"

#: What an entry describes. Kept open deliberately — the orchestrator and terminal add kinds
#: without touching this module — but every kind carries the same reversal mechanism.
KIND_ACCEPTANCE = "acceptance"
KIND_EDIT = "edit"
KIND_COMMAND = "command"


class JournalError(Exception):
    """A journal operation could not be completed. The message names the reason."""


@dataclass(frozen=True)
class Entry:
    """One reversible agent action."""

    id: str
    seq: int
    kind: str
    summary: str
    files: list[str]
    undone: bool
    dir: Path


class Journal:
    """The append-only record of agent actions for one repository."""

    def __init__(self, repo: Path) -> None:
        self.repo = Path(repo)
        self.root = self.repo / _JOURNAL_DIR
        self._log = self.root / _LOG

    # ---------------------------------------------------------------- reading

    def _records(self) -> list[dict[str, Any]]:
        """Raw log lines. `Any` is the honest type at a JSON boundary; every field is narrowed
        where it is used, the same way `settings.py` handles its document."""
        if not self._log.is_file():
            return []
        out: list[dict[str, Any]] = []
        for raw in self._log.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line:
                continue
            parsed: Any = json.loads(line)
            if isinstance(parsed, dict):
                out.append(parsed)
        return out

    def entries(self) -> list[Entry]:
        """Every recorded action, oldest first, with its current undone state."""
        records = self._records()
        undone = {str(r["undo"]) for r in records if "undo" in r}
        out: list[Entry] = []
        for r in records:
            if "undo" in r:
                continue
            raw_files: Any = r.get("files", [])
            files = [str(f) for f in raw_files] if isinstance(raw_files, list) else []
            entry_id = str(r["id"])
            out.append(
                Entry(
                    id=entry_id,
                    seq=int(r["seq"]),
                    kind=str(r["kind"]),
                    summary=str(r["summary"]),
                    files=files,
                    undone=entry_id in undone,
                    dir=self.root / entry_id,
                )
            )
        return out

    def pending(self) -> list[Entry]:
        """Actions still in effect — what an undo stack would show the user."""
        return [e for e in self.entries() if not e.undone]

    # ---------------------------------------------------------------- writing

    def _append(self, record: dict[str, object]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        with self._log.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")

    @contextmanager
    def record(self, kind: str, summary: str, files: Sequence[str]) -> Iterator[Entry]:
        """Capture pre-images, run the caller's mutation, and make it undoable.

        On any exception the pre-images are restored and the entry is marked undone before the
        error propagates — a half-applied agent action must never survive a failure (L15.3: a
        `catch` that logs and continues is a build failure; this one recovers meaningfully).
        """
        entry_id = uuid.uuid4().hex[:12]
        seq = len(self.entries())
        entry_dir = self.root / entry_id
        (entry_dir / _PRE).mkdir(parents=True, exist_ok=True)

        selected = list(files)
        existed: dict[str, bool] = {}
        for rel in selected:
            source = self.repo / rel
            existed[rel] = source.is_file()
            if existed[rel]:
                dest = entry_dir / _PRE / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, dest)
        (entry_dir / "meta.json").write_text(
            json.dumps({"existed": existed}, indent=2, sort_keys=True), encoding="utf-8"
        )
        self._append(
            {"id": entry_id, "seq": seq, "kind": kind, "summary": summary, "files": selected}
        )

        entry = Entry(
            id=entry_id,
            seq=seq,
            kind=kind,
            summary=summary,
            files=selected,
            undone=False,
            dir=entry_dir,
        )
        try:
            yield entry
        except Exception:
            self._restore(entry)
            self._append({"undo": entry_id})
            raise

    # ---------------------------------------------------------------- undoing

    def _restore(self, entry: Entry) -> None:
        meta: Any = json.loads((entry.dir / "meta.json").read_text(encoding="utf-8"))
        raw = meta.get("existed", {}) if isinstance(meta, dict) else {}
        existed: dict[str, bool] = {str(k): bool(v) for k, v in raw.items()}
        for rel in entry.files:
            target = self.repo / rel
            if existed.get(rel):
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(entry.dir / _PRE / rel, target)
            elif target.exists():
                target.unlink()

    def undo(self, entry_id: str) -> Entry:
        """Undo one entry by id. Idempotent — undo must never become its own failure mode."""
        found = next((e for e in self.entries() if e.id == entry_id), None)
        if found is None:
            raise JournalError(f"no journal entry {entry_id!r}")
        if found.undone:
            return found
        newer = [e for e in self.pending() if e.seq > found.seq]
        if newer:
            raise JournalError(
                f"entry {entry_id} has {len(newer)} newer action(s) still applied; undo those "
                "first — restoring an older pre-image over newer content would lose it"
            )
        self._restore(found)
        self._append({"undo": entry_id})
        return found

    def undo_last(self) -> Entry | None:
        """The one-keystroke undo: reverse the most recent action still in effect."""
        outstanding = self.pending()
        if not outstanding:
            return None
        return self.undo(outstanding[-1].id)
