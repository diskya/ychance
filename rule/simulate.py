from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

from .exit_ops import DEFAULT_EXIT_OPS
from .predicate_ops import DEFAULT_PREDICATE_OPS, coerce_scalar, resolve_spec_output


@dataclass(frozen=True)
class Trade:
    entry_t: datetime
    exit_t: datetime
    side: Literal["long", "short", "cash"]
    entry_price: float
    exit_price: float
    holding_return: float
    exit_reason: Literal["horizon", "exit_predicate"]


def simulate_rule(
    rule: Any,
    window: tuple[datetime, datetime],
    access: Any,
    spec_registry: Any,
) -> list[Trade]:
    start, end = _normalize_window(window)
    if rule.action.side == "cash":
        return []

    side_sign = _side_sign(rule.action.side)
    step = timedelta(seconds=rule.cadence.step_seconds)
    trades: list[Trade] = []
    in_position = False
    entry_t: datetime | None = None
    entry_bar: int | None = None
    entry_price: float | None = None

    t = start
    bar_index = 0
    while t <= end:
        if not in_position:
            if rule._evaluate_context_with_registry(t, access, spec_registry, DEFAULT_PREDICATE_OPS):
                entry_t = t
                entry_bar = bar_index
                entry_price = _price_at(rule.price_spec_ref, t, access, spec_registry)
                in_position = True
        else:
            assert entry_t is not None
            assert entry_bar is not None
            assert entry_price is not None
            current_price = _price_at(rule.price_spec_ref, t, access, spec_registry)
            exit_predicate = rule._evaluate_exit_with_registry(
                t=t,
                access=access,
                spec_registry=spec_registry,
                predicate_registry=DEFAULT_PREDICATE_OPS,
                exit_registry=DEFAULT_EXIT_OPS,
                bar_index=bar_index,
                entry_bar=entry_bar,
                side_sign=side_sign,
                entry_price=entry_price,
                current_price=current_price,
            )
            if exit_predicate:
                trades.append(
                    _trade(
                        entry_t=entry_t,
                        exit_t=t,
                        side=rule.action.side,
                        side_sign=side_sign,
                        entry_price=entry_price,
                        exit_price=current_price,
                        exit_reason="exit_predicate",
                    )
                )
                in_position = False
                entry_t = None
                entry_bar = None
                entry_price = None
            elif bar_index - entry_bar >= rule.horizon_bars:
                trades.append(
                    _trade(
                        entry_t=entry_t,
                        exit_t=t,
                        side=rule.action.side,
                        side_sign=side_sign,
                        entry_price=entry_price,
                        exit_price=current_price,
                        exit_reason="horizon",
                    )
                )
                in_position = False
                entry_t = None
                entry_bar = None
                entry_price = None
        t += step
        bar_index += 1
    return trades


def _trade(
    *,
    entry_t: datetime,
    exit_t: datetime,
    side: Literal["long", "short", "cash"],
    side_sign: int,
    entry_price: float,
    exit_price: float,
    exit_reason: Literal["horizon", "exit_predicate"],
) -> Trade:
    return Trade(
        entry_t=entry_t,
        exit_t=exit_t,
        side=side,
        entry_price=entry_price,
        exit_price=exit_price,
        holding_return=(exit_price - entry_price) / entry_price * side_sign,
        exit_reason=exit_reason,
    )


def _price_at(spec_id: str, t: datetime, access: Any, spec_registry: Any) -> float:
    raw = coerce_scalar(resolve_spec_output(spec_id, t, access, spec_registry))
    if isinstance(raw, bool):
        raise TypeError("price output must be numeric")
    return float(raw)


def _side_sign(side: str) -> int:
    if side == "long":
        return 1
    if side == "short":
        return -1
    raise ValueError("cash side has no position sign")


def _normalize_window(window: tuple[datetime, datetime]) -> tuple[datetime, datetime]:
    if not (isinstance(window, tuple) and len(window) == 2):
        raise TypeError("window must be a (start, end) tuple")
    start, end = window
    _ensure_aware(start, "window start")
    _ensure_aware(end, "window end")
    if end < start:
        raise ValueError("window end must be >= start")
    return start, end


def _ensure_aware(raw: datetime, field: str) -> None:
    if not isinstance(raw, datetime):
        raise TypeError(f"{field} must be a datetime")
    if raw.tzinfo is None:
        raise ValueError(f"{field} must be timezone-aware")
