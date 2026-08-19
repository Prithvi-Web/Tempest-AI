"""Phase 19.6 pins: the cost meter (P11, L21).

The load-bearing property is that **a cap cannot be routed around**: the check and the recording
happen in the same call under one lock, so spending IS passing the gate. The other half is
honesty — tokens are measured, dollars are only ever computed from a rate the user supplied, and
a limit that cannot be evaluated raises instead of quietly passing.
"""

import json
import threading
from decimal import Decimal
from pathlib import Path

import pytest

from tempest.inference import cost


def _meter(tmp_path: Path, **kw: object) -> cost.Meter:
    return cost.Meter(tmp_path, **kw)  # type: ignore[arg-type]


def _spend(meter: cost.Meter, **kw: object) -> cost.Spend:
    args: dict[str, object] = {
        "provider": "anthropic",
        "model": "m-1",
        "input_tokens": 1000,
        "output_tokens": 500,
        "task": "t1",
        "session": "s1",
        "day": "2026-08-18",
    }
    args.update(kw)
    return meter.spend(**args)  # type: ignore[arg-type]


class TestTokensAreMeasured:
    def test_a_charge_is_recorded_and_totalled(self, tmp_path: Path) -> None:
        meter = _meter(tmp_path)
        _spend(meter)
        total = meter.totals(cost.SCOPE_TASK, "t1")
        assert (total.input_tokens, total.output_tokens, total.total_tokens) == (1000, 500, 1500)

    def test_totals_are_scoped_independently(self, tmp_path: Path) -> None:
        meter = _meter(tmp_path)
        _spend(meter, task="t1", session="s1")
        _spend(meter, task="t2", session="s1")
        assert meter.totals(cost.SCOPE_TASK, "t1").total_tokens == 1500
        assert meter.totals(cost.SCOPE_TASK, "t2").total_tokens == 1500
        assert meter.totals(cost.SCOPE_SESSION, "s1").total_tokens == 3000

    def test_totals_survive_a_restart(self, tmp_path: Path) -> None:
        """A running meter that forgets on restart is not a meter."""
        _spend(_meter(tmp_path))
        assert _meter(tmp_path).totals(cost.SCOPE_TASK, "t1").total_tokens == 1500

    def test_an_unknown_scope_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(cost.CostError, match="unknown scope"):
            _meter(tmp_path).totals("century", "t1")

    def test_a_fresh_meter_reports_zero_not_an_error(self, tmp_path: Path) -> None:
        assert _meter(tmp_path).totals(cost.SCOPE_TASK, "nothing-yet").total_tokens == 0


class TestDollarsAreNeverGuessed:
    def test_with_no_rate_the_tokens_still_count_and_dollars_are_none(self, tmp_path: Path) -> None:
        """`None` reads as 'not priced'. A 0.00 here would be a confident wrong number."""
        meter = _meter(tmp_path)
        _spend(meter)
        total = meter.totals(cost.SCOPE_TASK, "t1")
        assert total.total_tokens == 1500
        assert total.dollars is None
        assert total.unpriced_charges == 1

    def test_a_configured_rate_prices_the_charge_exactly(self, tmp_path: Path) -> None:
        rates = {"anthropic/m-1": cost.Rate(Decimal("3"), Decimal("15"))}
        meter = _meter(tmp_path, rates=rates)
        _spend(meter)  # 1000 in, 500 out
        # 1000/1e6*3 + 500/1e6*15 = 0.003 + 0.0075 = 0.0105 — exact decimal arithmetic, no float.
        assert meter.totals(cost.SCOPE_TASK, "t1").dollars == Decimal("0.0105")

    def test_a_provider_wide_rate_applies_when_no_model_rate_exists(self, tmp_path: Path) -> None:
        meter = _meter(tmp_path, rates={"anthropic": cost.Rate(Decimal("1"), Decimal("1"))})
        _spend(meter)
        assert meter.totals(cost.SCOPE_TASK, "t1").dollars == Decimal("0.0015")

    def test_a_model_rate_beats_the_provider_rate(self, tmp_path: Path) -> None:
        meter = _meter(
            tmp_path,
            rates={
                "anthropic": cost.Rate(Decimal("1"), Decimal("1")),
                "anthropic/m-1": cost.Rate(Decimal("10"), Decimal("10")),
            },
        )
        _spend(meter)
        assert meter.totals(cost.SCOPE_TASK, "t1").dollars == Decimal("0.015")

    def test_mixed_priced_and_unpriced_charges_are_labelled(self, tmp_path: Path) -> None:
        """A partial dollar figure must announce that it is partial."""
        meter = _meter(tmp_path, rates={"anthropic": cost.Rate(Decimal("3"), Decimal("15"))})
        _spend(meter)
        _spend(meter, provider="openai", model="x")  # no rate for openai
        total = meter.totals(cost.SCOPE_TASK, "t1")
        assert total.dollars == Decimal("0.0105")
        assert total.unpriced_charges == 1
        assert total.total_tokens == 3000


class TestHardCapsAtTheRouter:
    def test_a_token_cap_refuses_the_spend_that_would_breach_it(self, tmp_path: Path) -> None:
        meter = _meter(tmp_path, budgets={cost.SCOPE_TASK: cost.Budget(max_total_tokens=2000)})
        _spend(meter)  # 1500
        with pytest.raises(cost.CapExceeded, match="total-token cap"):
            _spend(meter)  # would reach 3000

    def test_a_refused_spend_is_not_recorded(self, tmp_path: Path) -> None:
        """The cap is enforced BEFORE the ledger grows — otherwise the refusal still bills."""
        meter = _meter(tmp_path, budgets={cost.SCOPE_TASK: cost.Budget(max_total_tokens=2000)})
        _spend(meter)
        with pytest.raises(cost.CapExceeded):
            _spend(meter)
        assert meter.totals(cost.SCOPE_TASK, "t1").total_tokens == 1500

    def test_input_and_output_caps_are_separate(self, tmp_path: Path) -> None:
        meter = _meter(tmp_path, budgets={cost.SCOPE_TASK: cost.Budget(max_output_tokens=400)})
        with pytest.raises(cost.CapExceeded, match="output-token cap"):
            _spend(meter)  # 500 out

    def test_an_input_cap_names_itself(self, tmp_path: Path) -> None:
        meter = _meter(tmp_path, budgets={cost.SCOPE_TASK: cost.Budget(max_input_tokens=100)})
        with pytest.raises(cost.CapExceeded, match="input-token cap"):
            _spend(meter)

    def test_a_dollar_cap_refuses_when_the_rate_is_known(self, tmp_path: Path) -> None:
        meter = _meter(
            tmp_path,
            rates={"anthropic": cost.Rate(Decimal("3"), Decimal("15"))},
            budgets={cost.SCOPE_TASK: cost.Budget(max_dollars=Decimal("0.011"))},
        )
        _spend(meter)  # 0.0105
        with pytest.raises(cost.CapExceeded, match="spend cap"):
            _spend(meter)  # would reach 0.021

    def test_each_scope_is_enforced_independently(self, tmp_path: Path) -> None:
        meter = _meter(tmp_path, budgets={cost.SCOPE_DAY: cost.Budget(max_total_tokens=2000)})
        _spend(meter, task="t1")
        with pytest.raises(cost.CapExceeded, match="day"):
            _spend(meter, task="t2")  # a different task, but the same day

    def test_no_budget_means_no_cap(self, tmp_path: Path) -> None:
        meter = _meter(tmp_path)
        for _ in range(5):
            _spend(meter)
        assert meter.totals(cost.SCOPE_TASK, "t1").total_tokens == 7500


class TestAnUnevaluableLimitNeverPasses:
    def test_a_dollar_cap_without_a_rate_raises_rather_than_passing(self, tmp_path: Path) -> None:
        """'I could not check your limit' must never look like 'you are within your limit'."""
        meter = _meter(tmp_path, budgets={cost.SCOPE_TASK: cost.Budget(max_dollars=Decimal("1"))})
        with pytest.raises(cost.RateUnknown, match="cannot be evaluated"):
            _spend(meter)

    def test_that_refusal_records_nothing(self, tmp_path: Path) -> None:
        meter = _meter(tmp_path, budgets={cost.SCOPE_TASK: cost.Budget(max_dollars=Decimal("1"))})
        with pytest.raises(cost.RateUnknown):
            _spend(meter)
        assert meter.totals(cost.SCOPE_TASK, "t1").total_tokens == 0

    def test_a_token_cap_still_works_with_no_rates_at_all(self, tmp_path: Path) -> None:
        """A user with no price table still gets real hard caps."""
        meter = _meter(tmp_path, budgets={cost.SCOPE_TASK: cost.Budget(max_total_tokens=1000)})
        with pytest.raises(cost.CapExceeded):
            _spend(meter)


class TestPreflight:
    def test_preflight_refuses_before_the_request_is_built(self, tmp_path: Path) -> None:
        meter = _meter(tmp_path, budgets={cost.SCOPE_TASK: cost.Budget(max_total_tokens=1000)})
        with pytest.raises(cost.CapExceeded):
            meter.preflight(
                provider="anthropic",
                model="m-1",
                input_tokens=900,
                output_tokens=200,
                task="t1",
                session="s1",
                day="d",
            )
        assert meter.totals(cost.SCOPE_TASK, "t1").total_tokens == 0

    def test_preflight_returns_the_projected_cost(self, tmp_path: Path) -> None:
        meter = _meter(tmp_path, rates={"anthropic": cost.Rate(Decimal("3"), Decimal("15"))})
        estimate = meter.preflight(
            provider="anthropic",
            model="m-1",
            input_tokens=1000,
            output_tokens=500,
            task="t1",
            session="s1",
            day="d",
        )
        assert estimate.dollars == Decimal("0.0105")
        assert estimate.over_threshold is False

    def test_preflight_flags_an_operation_over_the_users_threshold(self, tmp_path: Path) -> None:
        meter = _meter(
            tmp_path,
            rates={"anthropic": cost.Rate(Decimal("3"), Decimal("15"))},
            estimate_threshold_dollars=Decimal("0.01"),
        )
        estimate = meter.preflight(
            provider="anthropic",
            model="m-1",
            input_tokens=1000,
            output_tokens=500,
            task="t1",
            session="s1",
            day="d",
        )
        assert estimate.over_threshold is True

    def test_an_unpriced_operation_is_never_flagged_over_a_threshold(self, tmp_path: Path) -> None:
        """Without a rate we do not know the cost, so we must not claim it crossed a line."""
        meter = _meter(tmp_path, estimate_threshold_dollars=Decimal("0.01"))
        estimate = meter.preflight(
            provider="anthropic",
            model="m-1",
            input_tokens=10**9,
            output_tokens=10**9,
            task="t1",
            session="s1",
            day="d",
        )
        assert estimate.dollars is None
        assert estimate.over_threshold is False


class TestConcurrency:
    def test_a_fleet_cannot_slip_two_charges_past_one_cap(self, tmp_path: Path) -> None:
        """F17 spends concurrently; without the lock both turns read a stale total and pass."""
        meter = _meter(tmp_path, budgets={cost.SCOPE_SESSION: cost.Budget(max_total_tokens=3000)})
        errors: list[Exception] = []
        accepted: list[int] = []

        def worker() -> None:
            try:
                _spend(meter, task=f"t{threading.get_ident()}")
                accepted.append(1)
            except cost.CapExceeded as err:
                errors.append(err)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert len(accepted) == 2, f"cap admitted {len(accepted)} charges, expected 2"
        assert len(errors) == 6
        assert meter.totals(cost.SCOPE_SESSION, "s1").total_tokens == 3000


class TestCacheHitRate:
    def test_the_rate_is_reported_so_users_see_the_saving(self, tmp_path: Path) -> None:
        meter = _meter(tmp_path)
        _spend(meter, input_tokens=250, cached_input_tokens=750)
        assert meter.cache_hit_rate(cost.SCOPE_TASK, "t1") == pytest.approx(0.75)

    def test_nothing_spent_reports_none_not_zero(self, tmp_path: Path) -> None:
        """0.0 would read as 'the cache never works'; None reads as 'nothing to report yet'."""
        assert _meter(tmp_path).cache_hit_rate(cost.SCOPE_TASK, "t1") is None


class TestLedgerDurability:
    def test_the_ledger_is_append_only_and_one_record_per_charge(self, tmp_path: Path) -> None:
        meter = _meter(tmp_path)
        _spend(meter)
        first = meter.path.read_text()
        _spend(meter)
        after = meter.path.read_text()
        assert after.startswith(first), "an existing ledger line was rewritten"
        assert len(after.strip().splitlines()) == 2

    def test_blank_and_non_object_lines_are_tolerated(self, tmp_path: Path) -> None:
        """A ledger on disk can be hand-edited; a crash here would take the meter down."""
        meter = _meter(tmp_path)
        _spend(meter)
        with meter.path.open("a", encoding="utf-8") as fh:
            fh.write("\n")
            fh.write('"not a record"\n')
            fh.write("42\n")
        assert _meter(tmp_path).totals(cost.SCOPE_TASK, "t1").total_tokens == 1500

    def test_the_recorded_shape_carries_everything_the_ui_needs(self, tmp_path: Path) -> None:
        meter = _meter(tmp_path, rates={"anthropic": cost.Rate(Decimal("3"), Decimal("15"))})
        _spend(meter, cached_input_tokens=7)
        record = json.loads(meter.path.read_text().strip())
        assert record["provider"] == "anthropic"
        assert record["model"] == "m-1"
        assert record["cached_input_tokens"] == 7
        assert record["dollars"] == "0.0105"
        assert record[cost.SCOPE_DAY] == "2026-08-18"

    def test_a_fully_cached_turn_reports_a_perfect_rate(self, tmp_path: Path) -> None:
        """Every input token served from cache: the saving is total, and worth showing."""
        meter = _meter(tmp_path)
        _spend(meter, input_tokens=0, cached_input_tokens=900)
        assert meter.cache_hit_rate(cost.SCOPE_TASK, "t1") == pytest.approx(1.0)

    def test_charges_in_other_scopes_do_not_pollute_the_rate(self, tmp_path: Path) -> None:
        meter = _meter(tmp_path)
        _spend(meter, task="t1", input_tokens=100, cached_input_tokens=900)
        _spend(meter, task="t2", input_tokens=1000, cached_input_tokens=0)
        assert meter.cache_hit_rate(cost.SCOPE_TASK, "t1") == pytest.approx(0.9)
        assert meter.cache_hit_rate(cost.SCOPE_TASK, "t2") == pytest.approx(0.0)
