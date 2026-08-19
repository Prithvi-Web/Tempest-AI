"""The cost meter (P11) — **cost is visible before it is spent** (L21).

L21 has four clauses and each one decides a design detail here:

**"Hard caps per task, per session, per day."** Enforced in `spend()`, which is the function the
router calls — *not* in a UI layer. A cap a caller can route around is not a cap, so the check
and the recording live in the same call: you cannot spend without passing the gate, because
spending *is* passing the gate.

**"Estimates shown before any operation exceeding a threshold."** `preflight()` answers "may I,
and what will it cost" *before* a request is built, and refuses when the projected spend would
breach a budget. Refusing early is the difference between a cap and an apology.

**"A running meter."** Every charge is appended to a durable JSONL ledger, so totals survive a
crash and a restart. Same reasoning as the agent journal (19.4): an in-memory counter loses
exactly the history a user asks about after something goes wrong.

**"Never a surprise bill."** Two honesty rules fall out of that, and they are the reason this
module refuses to guess:

1. **Tokens are measured; dollars are computed from a rate the user supplies.** The token counts
   come from the provider's own `usage` field (`inference.Usage`). Prices, unlike tokens, are not
   reported in the response — they change, they differ per contract, and a hardcoded price table
   goes stale silently. So there is **no built-in price list**. With no rate configured the meter
   still counts tokens exactly and reports `dollars = None`, which reads in the UI as "not
   priced" rather than as a confident wrong number.
2. **A cap that cannot be evaluated is not silently ignored.** A dollar budget with no rate
   configured raises rather than passing, because "I could not check your limit" must never look
   like "you are within your limit".

Token budgets always work, with or without rates — so a user with no price table still gets real
hard caps.
"""

import json
import threading
from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path
from typing import Any

_LEDGER_DIR = Path(".tempest") / "agent"
_LEDGER = "cost-ledger.jsonl"

#: Scopes a budget can apply to. "day" is keyed by the caller-supplied day stamp, never by
#: reading a clock here — the engine's determinism habit (timestamps are recorded, not compared).
SCOPE_TASK = "task"
SCOPE_SESSION = "session"
SCOPE_DAY = "day"
SCOPES = (SCOPE_TASK, SCOPE_SESSION, SCOPE_DAY)


class CostError(Exception):
    """A cost-meter problem. The message always names the limit and the amount."""


class CapExceeded(CostError):
    """A hard cap would be breached. Raised BEFORE the spend, never after (L21)."""


class RateUnknown(CostError):
    """A dollar limit was set but no price is configured, so the limit cannot be evaluated."""


@dataclass(frozen=True)
class Rate:
    """Price per million tokens, supplied by the user — never shipped as a guess."""

    input_per_mtok: Decimal
    output_per_mtok: Decimal
    currency: str = "USD"

    def cost(self, input_tokens: int, output_tokens: int) -> Decimal:
        million = Decimal(1_000_000)
        return (
            Decimal(input_tokens) * self.input_per_mtok / million
            + Decimal(output_tokens) * self.output_per_mtok / million
        )


@dataclass(frozen=True)
class Budget:
    """Hard caps. `None` means unlimited; a token cap works without any price table."""

    max_input_tokens: int | None = None
    max_output_tokens: int | None = None
    max_total_tokens: int | None = None
    max_dollars: Decimal | None = None


@dataclass(frozen=True)
class Spend:
    """What has been spent in a scope. `dollars is None` means 'not priced', never 'free'."""

    input_tokens: int = 0
    output_tokens: int = 0
    dollars: Decimal | None = None
    #: True when at least one charge in this scope had no configured rate, so the dollar
    #: figure — if any — is incomplete and must be labelled as such in the UI.
    unpriced_charges: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def plus(self, input_tokens: int, output_tokens: int, dollars: Decimal | None) -> "Spend":
        if dollars is None:
            return replace(
                self,
                input_tokens=self.input_tokens + input_tokens,
                output_tokens=self.output_tokens + output_tokens,
                unpriced_charges=self.unpriced_charges + 1,
            )
        return replace(
            self,
            input_tokens=self.input_tokens + input_tokens,
            output_tokens=self.output_tokens + output_tokens,
            dollars=(self.dollars or Decimal(0)) + dollars,
        )


@dataclass(frozen=True)
class Estimate:
    """The pre-flight answer: what this would cost and whether it is allowed."""

    input_tokens: int
    output_tokens: int
    dollars: Decimal | None
    over_threshold: bool


def _check(budget: Budget, projected: Spend, scope: str, rate_known: bool) -> None:
    """Raise if `projected` breaches `budget`. Never silently passes an uncheckable limit."""
    if budget.max_input_tokens is not None and projected.input_tokens > budget.max_input_tokens:
        raise CapExceeded(
            f"{scope} input-token cap reached: {projected.input_tokens} would exceed "
            f"{budget.max_input_tokens}"
        )
    if budget.max_output_tokens is not None and projected.output_tokens > budget.max_output_tokens:
        raise CapExceeded(
            f"{scope} output-token cap reached: {projected.output_tokens} would exceed "
            f"{budget.max_output_tokens}"
        )
    if budget.max_total_tokens is not None and projected.total_tokens > budget.max_total_tokens:
        raise CapExceeded(
            f"{scope} total-token cap reached: {projected.total_tokens} would exceed "
            f"{budget.max_total_tokens}"
        )
    if budget.max_dollars is None:
        return
    if not rate_known:
        raise RateUnknown(
            f"a {scope} limit of {budget.max_dollars} was set, but no price is configured for "
            f"this provider/model, so the limit cannot be evaluated. Set a rate, or use a "
            f"token cap instead — an unevaluable limit must never read as 'within budget'."
        )
    if projected.dollars is not None and projected.dollars > budget.max_dollars:
        raise CapExceeded(
            f"{scope} spend cap reached: {projected.dollars} would exceed {budget.max_dollars}"
        )


class Meter:
    """The router's cost gate: a durable ledger plus the caps that guard it.

    Thread-safe because an agent fleet (F17) spends concurrently; without the lock two turns
    could each read a total below the cap and both proceed past it.
    """

    def __init__(
        self,
        repo: Path,
        *,
        budgets: dict[str, Budget] | None = None,
        rates: dict[str, Rate] | None = None,
        estimate_threshold_dollars: Decimal | None = None,
    ) -> None:
        self.repo = Path(repo)
        self.path = self.repo / _LEDGER_DIR / _LEDGER
        self.budgets = dict(budgets or {})
        #: Keyed "provider/model", then "provider" as a fallback. Empty by design (see module doc).
        self.rates = dict(rates or {})
        self.estimate_threshold_dollars = estimate_threshold_dollars
        self._lock = threading.Lock()

    # ----------------------------------------------------------------- rates

    def rate_for(self, provider: str, model: str) -> Rate | None:
        return self.rates.get(f"{provider}/{model}") or self.rates.get(provider)

    def price(
        self, provider: str, model: str, input_tokens: int, output_tokens: int
    ) -> Decimal | None:
        rate = self.rate_for(provider, model)
        return None if rate is None else rate.cost(input_tokens, output_tokens)

    # ---------------------------------------------------------------- ledger

    def _records(self) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        out: list[dict[str, Any]] = []
        for raw in self.path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line:
                continue
            parsed: Any = json.loads(line)
            if isinstance(parsed, dict):
                out.append(parsed)
        return out

    def totals(self, scope: str, key: str) -> Spend:
        """What has been spent so far in one scope instance (a task id, session id, or day)."""
        if scope not in SCOPES:
            raise CostError(f"unknown scope {scope!r} — scopes are {', '.join(SCOPES)}")
        spend = Spend()
        for record in self._records():
            if record.get(scope) != key:
                continue
            dollars_raw = record.get("dollars")
            spend = spend.plus(
                int(record.get("input_tokens", 0)),
                int(record.get("output_tokens", 0)),
                None if dollars_raw is None else Decimal(str(dollars_raw)),
            )
        return spend

    # ------------------------------------------------------------- the gate

    def _scopes_for(self, task: str, session: str, day: str) -> list[tuple[str, str]]:
        return [(SCOPE_TASK, task), (SCOPE_SESSION, session), (SCOPE_DAY, day)]

    def preflight(
        self,
        *,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        task: str,
        session: str,
        day: str,
    ) -> Estimate:
        """Answer 'may I, and what will it cost' **before** the request is built.

        Raises `CapExceeded` when the projected spend would breach any budget, so the caller
        never starts an operation it is not allowed to finish.
        """
        dollars = self.price(provider, model, input_tokens, output_tokens)
        rate_known = self.rate_for(provider, model) is not None
        with self._lock:
            for scope, key in self._scopes_for(task, session, day):
                budget = self.budgets.get(scope)
                if budget is None:
                    continue
                projected = self.totals(scope, key).plus(input_tokens, output_tokens, dollars)
                _check(budget, projected, scope, rate_known)
        over = (
            self.estimate_threshold_dollars is not None
            and dollars is not None
            and dollars >= self.estimate_threshold_dollars
        )
        return Estimate(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            dollars=dollars,
            over_threshold=over,
        )

    def spend(
        self,
        *,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        task: str,
        session: str,
        day: str,
        cached_input_tokens: int = 0,
    ) -> Spend:
        """Record a completed charge, refusing it if it would breach a cap.

        The check and the append happen under one lock, so a concurrent fleet cannot slip two
        charges past the same limit by both reading a stale total.
        """
        dollars = self.price(provider, model, input_tokens, output_tokens)
        rate_known = self.rate_for(provider, model) is not None
        with self._lock:
            for scope, key in self._scopes_for(task, session, day):
                budget = self.budgets.get(scope)
                if budget is None:
                    continue
                projected = self.totals(scope, key).plus(input_tokens, output_tokens, dollars)
                _check(budget, projected, scope, rate_known)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            record = {
                "provider": provider,
                "model": model,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cached_input_tokens": cached_input_tokens,
                "dollars": None if dollars is None else str(dollars),
                SCOPE_TASK: task,
                SCOPE_SESSION: session,
                SCOPE_DAY: day,
            }
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, sort_keys=True) + "\n")
        return Spend().plus(input_tokens, output_tokens, dollars)

    # ------------------------------------------------------------- reporting

    def cache_hit_rate(self, scope: str, key: str) -> float | None:
        """Prompt-cache hit rate (§7: report it so users see the saving).

        `None` when nothing has been spent — never 0.0, which would read as "the cache never
        works" rather than "there is nothing to report yet".
        """
        cached = billed = 0
        for record in self._records():
            if record.get(scope) != key:
                continue
            cached += int(record.get("cached_input_tokens", 0))
            billed += int(record.get("input_tokens", 0))
        total = cached + billed
        return None if total == 0 else cached / total
