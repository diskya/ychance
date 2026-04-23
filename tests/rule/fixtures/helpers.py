from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np

from rule import action as action_module


PRICE_SPEC = "1" * 64
AUX_SPEC = "2" * 64
GROUND_SPEC = "3" * 64
OTHER_SPEC = "4" * 64
BASE_T = datetime(2026, 1, 1, tzinfo=timezone.utc)


@dataclass
class SeriesRegistry:
    series_by_id: dict[str, list[float]]
    start: datetime = BASE_T
    step_seconds: int = 60

    def at(self, spec_id: str, t: datetime, access: Any) -> float:
        index = int((t - self.start).total_seconds() // self.step_seconds)
        return self.series_by_id[spec_id][index]

    def series(self, spec_id: str, t0: datetime, t1: datetime, access: Any) -> np.ndarray:
        start = int((t0 - self.start).total_seconds() // self.step_seconds)
        end = int((t1 - self.start).total_seconds() // self.step_seconds)
        return np.asarray(self.series_by_id[spec_id][start : end + 1], dtype=float)


def tick(n: int) -> datetime:
    return BASE_T + timedelta(minutes=n)


def literal(value: float | bool, node_id: str = "lit") -> dict[str, Any]:
    return {"id": node_id, "op": "literal", "args": {"value": value}, "inputs": []}


def spec_ref(spec_id: str = PRICE_SPEC, node_id: str = "spec") -> dict[str, Any]:
    return {"id": node_id, "op": "spec_ref", "args": {"spec_id": spec_id}, "inputs": []}


def binary(node_id: str, op: str, left: str, right: str) -> dict[str, Any]:
    return {"id": node_id, "op": op, "args": {}, "inputs": [left, right]}


def unary(node_id: str, op: str, child: str) -> dict[str, Any]:
    return {"id": node_id, "op": op, "args": {}, "inputs": [child]}


def context_price_gt(threshold: float = 100, *, output: str = "gt") -> dict[str, Any]:
    return {
        "nodes": [
            spec_ref(PRICE_SPEC, "price"),
            literal(threshold, "threshold"),
            binary(output, "gt", "price", "threshold"),
        ],
        "output": output,
    }


def context_price_le(threshold: float = 100, *, output: str = "le") -> dict[str, Any]:
    return {
        "nodes": [
            spec_ref(PRICE_SPEC, "price"),
            literal(threshold, "threshold"),
            binary(output, "le", "price", "threshold"),
        ],
        "output": output,
    }


def exit_after(bars: int = 3, *, output: str = "done") -> dict[str, Any]:
    return {
        "nodes": [
            {"id": "elapsed", "op": "time_since_entry", "args": {}, "inputs": []},
            literal(bars, "bars"),
            binary(output, "ge", "elapsed", "bars"),
        ],
        "output": output,
    }


def exit_false() -> dict[str, Any]:
    return exit_after(99)


def exit_when_context_stops() -> dict[str, Any]:
    return {
        "nodes": [
            {"id": "still", "op": "context_still_holds", "args": {}, "inputs": []},
            unary("done", "not", "still"),
        ],
        "output": "done",
    }


def base_grounding(kind: str = "in_range") -> dict[str, Any]:
    if kind == "in_range":
        assertion = {"kind": "in_range", "lo": 0.0, "hi": 10.0}
    elif kind == "quantile_ge":
        assertion = {"kind": "quantile_ge", "p": 0.5, "threshold": 0.0}
    elif kind == "sign":
        assertion = {"kind": "sign", "expected_sign": 1}
    else:
        assertion = {"kind": kind}
    return {
        "spec_ref": GROUND_SPEC,
        "assertion": assertion,
        "window": {"t0": tick(0).isoformat(), "t1": tick(4).isoformat()},
    }


def rule_body(
    *,
    context: dict[str, Any] | None = None,
    exit: dict[str, Any] | None = None,
    side: str = "long",
    horizon_bars: int = 5,
    cadence_seconds: int = 60,
    grounding: dict[str, Any] | None = None,
    price_spec_ref: str = PRICE_SPEC,
) -> dict[str, Any]:
    return {
        "context": context if context is not None else context_price_gt(),
        "exit": exit if exit is not None else exit_after(3),
        "action": {"side": side, "size_multiplier": 1.0},
        "action_schema_version": action_module.action_schema_version,
        "horizon_bars": horizon_bars,
        "cadence": {"kind": "fixed_step", "step_seconds": cadence_seconds},
        "grounding": grounding if grounding is not None else base_grounding(),
        "price_spec_ref": price_spec_ref,
    }
