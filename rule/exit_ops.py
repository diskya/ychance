from __future__ import annotations

from typing import Any

from .predicate_ops import (
    DEFAULT_PREDICATE_OPS,
    TYPE_BOOL,
    TYPE_SCALAR,
    DagOp,
    EvalContext,
    _no_args,
)


def _scalar_type(args: dict[str, Any], input_types: list[str]) -> str:
    return TYPE_SCALAR


def _bool_type(args: dict[str, Any], input_types: list[str]) -> str:
    return TYPE_BOOL


def _time_since_entry(args: dict[str, Any], inputs: list[Any], ctx: EvalContext) -> int:
    if ctx.entry_bar is None or ctx.bar_index is None:
        raise RuntimeError("entry bars are unavailable")
    return ctx.bar_index - ctx.entry_bar


def _realized_pnl(args: dict[str, Any], inputs: list[Any], ctx: EvalContext) -> float:
    if ctx.entry_price is None or ctx.current_price is None or ctx.side_sign is None:
        raise RuntimeError("position inputs are unavailable")
    return (ctx.current_price - ctx.entry_price) * ctx.side_sign


def _context_still_holds(args: dict[str, Any], inputs: list[Any], ctx: EvalContext) -> bool:
    if ctx.context_now is None:
        raise RuntimeError("context callback is unavailable")
    return ctx.context_now()


DEFAULT_EXIT_OPS: dict[str, DagOp] = {
    **DEFAULT_PREDICATE_OPS,
    "time_since_entry": DagOp(
        "time_since_entry",
        0,
        0,
        "1",
        _time_since_entry,
        _scalar_type,
        _no_args,
    ),
    "realized_pnl": DagOp(
        "realized_pnl",
        0,
        0,
        "1",
        _realized_pnl,
        _scalar_type,
        _no_args,
    ),
    "context_still_holds": DagOp(
        "context_still_holds",
        0,
        0,
        "1",
        _context_still_holds,
        _bool_type,
        _no_args,
    ),
}
