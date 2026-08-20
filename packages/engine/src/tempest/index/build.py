"""Building the index: structure, then terms, then execution — in that order and for a reason.

Structure first because everything else keys off a symbol id. Terms next because they are derived
from the parsed symbol and cost nothing extra while it is in hand. Execution last because it is
the only step that RUNS anything, is thousands of times more expensive than the other two, and is
the one a caller may legitimately want to skip.

**Execution is opt-in and bounded.** `build_index(..., observe=False)` gives a structural and
lexical index in milliseconds; `observe=True` executes generated inputs against the indexed
functions in the repository's sandbox tier, and `only=` narrows that to a named set — which is
what a caller recording what a REAL run touched wants, as against a caller sweeping the whole
repository to synthesise specs (F4). That is a real cost and a real risk surface, so it is a
parameter rather than a default, and it goes through the same tier ladder every other execution in
this product goes through (L6).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from tempest.execute.sandbox import SandboxSelection
from tempest.index import execution, lexical, structure
from tempest.index.store import SymbolRow, symbol_rows
from tempest.prove import select_sandbox_for_repo


@dataclass(frozen=True)
class BuildReport:
    structural: structure.IndexStats
    executed: execution.ExecutionStats | None
    #: Why execution did not run, when it did not. Empty when it did, or when nobody asked.
    execution_skipped: str = ""

    def render(self) -> str:
        lines = [
            f"index: {self.structural.symbols} symbols in {self.structural.files_seen} files "
            f"({self.structural.files_reparsed} re-parsed), {self.structural.calls} call edges",
        ]
        for path in self.structural.unreadable:
            lines.append(f"index: could not read {path} — its symbols are NOT in the index")
        if self.executed is not None:
            lines.append(
                f"index: executed {self.executed.symbols_observed}/"
                f"{self.executed.symbols_attempted} symbols over {self.executed.inputs_run} "
                f"inputs, {self.executed.behaviours} behaviour classes recorded"
            )
            for qualname, reason in self.executed.unreachable:
                lines.append(f"index: {qualname} not observed — {reason}")
        elif self.execution_skipped:
            lines.append(f"index: no execution recorded — {self.execution_skipped}")
        return "\n".join(lines)


def _function_targets(
    conn: sqlite3.Connection, only: frozenset[str] | None = None
) -> list[execution.SymbolTarget]:
    """Only functions and methods. A class has no inputs to generate and no return to observe;
    asking the runner to invoke one would produce an instance, which is not a behaviour."""
    rows: list[SymbolRow] = symbol_rows(conn, "s.kind IN ('function', 'async function', 'method')")
    if only is not None:
        rows = [r for r in rows if r.qualname in only]
    return [
        execution.SymbolTarget(symbol_id=r.id, module=r.module, qualname=r.qualname) for r in rows
    ]


def build_index(
    conn: sqlite3.Connection,
    repo: Path,
    *,
    observe: bool = False,
    revision: str = "working-tree",
    max_inputs: int = 24,
    seed: int = 0,
    only: frozenset[str] | None = None,
    select: Callable[[Path], SandboxSelection] | None = None,
) -> BuildReport:
    """Bring the index up to date. Returns what it did, including what it could not do."""
    repo = Path(repo)

    def on_symbol(symbol_id: int, parsed: structure.ParsedSymbol) -> None:
        lexical.index_symbol(
            conn,
            symbol_id,
            lexical.document_terms(
                qualname=parsed.qualname,
                module=parsed.module,
                signature=parsed.signature,
                doc=parsed.doc,
                text=parsed.text,
            ),
        )

    stats = structure.build(conn, repo, on_symbol=on_symbol)
    if not observe:
        return BuildReport(structural=stats, executed=None)

    selection = (select or select_sandbox_for_repo)(repo)
    if selection.sandbox is None:
        # L6: no tier, no execution. The index is still useful and now says exactly which half
        # of it is missing, rather than answering execution questions with silence.
        return BuildReport(
            structural=stats,
            executed=None,
            execution_skipped=selection.reason or "no sandbox tier is available",
        )
    observed = execution.observe(
        conn,
        repo,
        _function_targets(conn, only),
        selection.sandbox,
        revision=revision,
        max_inputs=max_inputs,
        seed=seed,
    )
    return BuildReport(structural=stats, executed=observed)
