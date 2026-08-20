"""F15 + P3 — behavioural rules, compiled into contract clauses the ENGINE enforces (Phase 23).

**The distinction the whole feature turns on.** A stylistic rule is advice: *"prefer early
returns"* is a thing you tell a model and hope. A behavioural rule is a wall: *"nothing in
`billing/` may change behaviour without an explicit intent contract"* compiles into clauses the
comparison stage consumes, and a model that is told to ignore it changes nothing, because the
model is not the thing enforcing it. F15's gate says exactly that — a rule violation is blocked
even when the model is instructed to violate it — and P3 adds that a Proof Skill's declared floor
holds under the same instruction.

**Structurally impossible, not adversarially resistant.** Prompt injection defends against nothing
here, and that is the point: the rules are read from disk by the host, merged into the
`IntentContract` the classifier uses, and consulted after the model's turn is over. Nothing the
model emits is on that path. The redteam suite proves it by trying, with the payloads in the
retrieved page, the tool result, and the prompt itself.

**Hierarchical by directory, most specific first.** `.tempest/rules/*.toml` at the repository root
applies everywhere; a `rules.toml` inside a directory applies to symbols in that subtree and
overrides the root for them. Conflicts are not silently merged: a symbol forbidden by one rule and
permitted by another resolves to FORBIDDEN, for the same reason `IntentContract.classify` resolves
that way — the honest reading of an ambiguity is the one that shows the user the divergence.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from tempest.agent import contracts as contracts_mod

RULES_DIR = Path(".tempest") / "rules"
#: A directory-local rules file, applying to symbols defined under that directory.
LOCAL_RULES_NAME = "rules.toml"

_ALLOWED_KEYS = frozenset({"name", "scope", "must_not_change", "may_change", "why"})


class RuleError(Exception):
    """A rules file could not be read. Raised, never defaulted: a behavioural rule that silently
    fails to load is worse than no rule, because the user believes the wall is there."""


@dataclass(frozen=True)
class Rule:
    name: str
    #: A repo-relative directory this rule governs; "" is the whole repository.
    scope: str
    must_not_change: tuple[str, ...]
    may_change: tuple[str, ...]
    #: The reason, quoted back to the user when the rule fires. A wall with no explanation is
    #: indistinguishable from a bug.
    why: str
    source: str

    def governs(self, file_path: str) -> bool:
        if not self.scope:
            return True
        scope = self.scope.rstrip("/")
        return file_path == scope or file_path.startswith(scope + "/")


def _parse(path: Path, source: str, default_scope: str) -> list[Rule]:
    try:
        doc = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise RuleError(f"{source}: {exc}") from exc
    entries = doc.get("rule")
    if not isinstance(entries, list):
        raise RuleError(f"{source}: expected one or more [[rule]] tables")
    out: list[Rule] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise RuleError(f"{source}: a [[rule]] entry must be a table")
        unknown = set(entry) - _ALLOWED_KEYS
        if unknown:
            raise RuleError(
                f"{source}: unknown key(s) {', '.join(sorted(unknown))} — the vocabulary is "
                f"{', '.join(sorted(_ALLOWED_KEYS))}. A typo in a rule is a wall that is not there"
            )
        out.append(
            Rule(
                name=str(entry.get("name", path.stem)),
                scope=str(entry.get("scope", default_scope)),
                must_not_change=tuple(str(p) for p in entry.get("must_not_change", ())),
                may_change=tuple(str(p) for p in entry.get("may_change", ())),
                why=str(entry.get("why", "")),
                source=source,
            )
        )
    return out


def load(repo: Path) -> list[Rule]:
    """Every rule in the repository, root rules first and directory-local rules after.

    Order is the resolution order, and it is stable: a caller comparing two runs is comparing the
    same list. A repository with no rules answers with an empty list, which is an ordinary state.
    """
    repo = Path(repo)
    rules: list[Rule] = []
    root_dir = repo / RULES_DIR
    if root_dir.is_dir():
        for path in sorted(root_dir.glob("*.toml")):
            rules.extend(_parse(path, f"{RULES_DIR}/{path.name}", default_scope=""))
    for path in sorted(repo.rglob(LOCAL_RULES_NAME)):
        if RULES_DIR.as_posix() in path.as_posix():
            continue
        rel_dir = path.parent.relative_to(repo).as_posix()
        rules.extend(
            _parse(
                path,
                f"{rel_dir}/{LOCAL_RULES_NAME}" if rel_dir != "." else LOCAL_RULES_NAME,
                default_scope="" if rel_dir == "." else rel_dir,
            )
        )
    return rules


@dataclass(frozen=True)
class Applied:
    """The contract a task actually runs under, and which rules contributed to it."""

    #: `None` only when the user stated no intent AND no rule governs the files.
    contract: contracts_mod.IntentContract | None
    applied: tuple[Rule, ...]

    def explain(self) -> str:
        if not self.applied:
            return "no behavioural rules applied to this task"
        lines = ["behavioural rules in force:"]
        for rule in self.applied:
            clause = ", ".join(rule.must_not_change) or "(nothing)"
            lines.append(f"  {rule.name} ({rule.source}) — must not change: {clause}")
            if rule.why:
                lines.append(f"    because: {rule.why}")
        return "\n".join(lines)


def apply_to(
    contract: contracts_mod.IntentContract | None,
    rules: list[Rule],
    *,
    files: tuple[str, ...],
    intent: str = "",
) -> Applied:
    """Fold the rules governing `files` into the task's contract.

    **Rules only ever ADD `must_not_change`.** A rule that could add `may_change` would be a
    mechanism for widening what an agent is allowed to alter by editing a file in the repository —
    which is the shape of every privilege-escalation bug ever written, and an agent can write
    files. So `may_change` in a rule is read and deliberately NOT applied to the effective
    contract; it exists to document intent and is reported, never enforced.

    A task with no contract still gets one when a rule governs its files: that is the whole point
    of a behavioural rule, and "the user did not state an intent" is not permission.
    """
    governing = tuple(r for r in rules if any(r.governs(f) for f in files))
    if not governing:
        # No rule reaches these files, so the task runs under exactly what the user stated —
        # including nothing at all, which stays `None` rather than becoming an empty contract.
        # An empty contract would classify every divergence UNCLASSIFIED, which is the same
        # answer, but it would also make the repair loop engage on a task nobody stated an
        # intent for (F2's whole objection).
        return Applied(contract=contract, applied=())
    forbidden = tuple(
        dict.fromkeys(
            [
                *(contract.must_not_change if contract else ()),
                *(p for r in governing for p in r.must_not_change),
            ]
        )
    )
    # A symbol a rule forbids is forbidden even if the task's own contract permits it. The rule is
    # the user's standing decision; the contract is one task's request.
    permitted = tuple(
        p for p in (contract.may_change if contract else ()) if p not in set(forbidden)
    )
    stated = (contract.intent if contract else intent).strip()
    return Applied(
        contract=contracts_mod.IntentContract(
            # A contract must record the intent it was compiled from. When the user stated none,
            # the rules ARE the intent, and naming them keeps that honest rather than inventing
            # a sentence the user never said.
            intent=stated
            or "no task intent was stated; behavioural rules apply: "
            + ", ".join(r.name for r in governing),
            may_change=permitted,
            must_not_change=forbidden,
        ),
        applied=governing,
    )
