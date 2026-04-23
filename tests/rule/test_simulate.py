from __future__ import annotations

import pytest

from rule import finalize_rule

from .fixtures.helpers import (
    PRICE_SPEC,
    SeriesRegistry,
    context_price_gt,
    exit_after,
    exit_false,
    exit_when_context_stops,
    rule_body,
    tick,
)


def test_elapsed_exit_emits_expected_trade_sequence() -> None:
    registry = SeriesRegistry({PRICE_SPEC: [99, 101, 102, 103, 104, 98, 99, 105, 106, 107, 108]})
    rule = finalize_rule(rule_body(context=context_price_gt(100), exit=exit_after(3), horizon_bars=10))

    trades = rule.simulate((tick(0), tick(10)), object(), registry)

    assert [(t.entry_t, t.exit_t, t.entry_price, t.exit_price, t.exit_reason) for t in trades] == [
        (tick(1), tick(4), 101.0, 104.0, "exit_predicate"),
        (tick(7), tick(10), 105.0, 108.0, "exit_predicate"),
    ]
    assert trades[0].holding_return == pytest.approx((104 - 101) / 101)


def test_cash_action_yields_empty_trades() -> None:
    registry = SeriesRegistry({PRICE_SPEC: [101, 102, 103]})
    rule = finalize_rule(rule_body(side="cash"))

    assert rule.simulate((tick(0), tick(2)), object(), registry) == []


def test_horizon_exit_fires_when_predicate_stays_false() -> None:
    registry = SeriesRegistry({PRICE_SPEC: [101, 102, 103, 104]})
    rule = finalize_rule(rule_body(exit=exit_false(), horizon_bars=2))

    trades = rule.simulate((tick(0), tick(3)), object(), registry)

    assert len(trades) == 1
    assert trades[0].entry_t == tick(0)
    assert trades[0].exit_t == tick(2)
    assert trades[0].exit_reason == "horizon"


def test_exit_predicate_fires_before_horizon() -> None:
    registry = SeriesRegistry({PRICE_SPEC: [101, 102, 103, 104]})
    rule = finalize_rule(rule_body(exit=exit_after(1), horizon_bars=5))

    trades = rule.simulate((tick(0), tick(3)), object(), registry)

    assert len(trades) == 2
    assert trades[0].exit_t == tick(1)
    assert trades[0].exit_reason == "exit_predicate"


def test_context_still_holds_can_close_when_context_stops() -> None:
    registry = SeriesRegistry({PRICE_SPEC: [101, 102, 99, 98]})
    rule = finalize_rule(rule_body(context=context_price_gt(100), exit=exit_when_context_stops()))

    trades = rule.simulate((tick(0), tick(3)), object(), registry)

    assert len(trades) == 1
    assert trades[0].entry_t == tick(0)
    assert trades[0].exit_t == tick(2)
    assert trades[0].exit_reason == "exit_predicate"


def test_holding_return_is_raw_ratio_adjusted_by_side() -> None:
    registry = SeriesRegistry({PRICE_SPEC: [100, 90, 80]})
    rule = finalize_rule(
        rule_body(side="short", context=context_price_gt(99), exit=exit_after(1), horizon_bars=5)
    )

    trades = rule.simulate((tick(0), tick(2)), object(), registry)

    assert len(trades) == 1
    assert trades[0].holding_return == pytest.approx((90 - 100) / 100 * -1)
