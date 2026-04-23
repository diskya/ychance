from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

import numpy as np

from .predicate_ops import resolve_spec_output


# Floating reductions can leave tiny residue around exact cancellation.
ZERO_MEAN_TOLERANCE = 1e-12
ASSERTION_KINDS = frozenset({"in_range", "quantile_ge", "sign"})


@dataclass(frozen=True)
class GroundingWindow:
    t0: datetime
    t1: datetime

    def as_dict(self) -> dict[str, str]:
        return {
            "t0": self.t0.isoformat(),
            "t1": self.t1.isoformat(),
        }


@dataclass(frozen=True)
class Grounding:
    spec_ref: str
    assertion: dict[str, Any]
    window: GroundingWindow

    def as_dict(self) -> dict[str, Any]:
        return {
            "spec_ref": self.spec_ref,
            "assertion": dict(self.assertion),
            "window": self.window.as_dict(),
        }

    def evaluate(self, access: Any, spec_registry: Any) -> bool:
        items = _series_for_window(
            spec_ref=self.spec_ref,
            window=self.window,
            access=access,
            spec_registry=spec_registry,
        )
        arr = np.asarray(items, dtype=float).reshape(-1)
        if arr.size == 0:
            return False
        mean_item = float(np.mean(arr))
        assertion = self.assertion
        kind = assertion["kind"]
        if kind == "in_range":
            return float(assertion["lo"]) <= mean_item <= float(assertion["hi"])
        if kind == "quantile_ge":
            q = float(np.quantile(arr, float(assertion["p"])))
            return q >= float(assertion["threshold"])
        if kind == "sign":
            return _mean_sign(mean_item) == int(assertion["expected_sign"])
        raise AssertionError("unreachable assertion kind")


def load_grounding(body: Mapping[str, Any]) -> Grounding:
    if not isinstance(body, Mapping):
        raise TypeError("grounding must be a mapping")
    keys = frozenset({"spec_ref", "assertion", "window"})
    extra = set(body.keys()) - keys
    missing = keys - set(body.keys())
    if extra or missing:
        raise ValueError(
            "grounding must contain exactly ['assertion', 'spec_ref', 'window']; "
            f"missing={sorted(missing)}, extra={sorted(extra)}"
        )
    spec_ref = body["spec_ref"]
    if not isinstance(spec_ref, str) or len(spec_ref) != 64:
        raise ValueError("grounding.spec_ref must be a 64-character string")
    assertion = _normalize_assertion(body["assertion"])
    window = _normalize_window(body["window"])
    return Grounding(spec_ref=spec_ref, assertion=assertion, window=window)


def _normalize_assertion(body: Any) -> dict[str, Any]:
    if not isinstance(body, Mapping):
        raise ValueError("assertion must be a mapping")
    kind = body.get("kind")
    if kind not in ASSERTION_KINDS:
        raise ValueError("assertion kind is not allowed")
    if kind == "in_range":
        _assert_keys(body, {"kind", "lo", "hi"})
        lo = _finite_float(body["lo"], "lo")
        hi = _finite_float(body["hi"], "hi")
        if hi < lo:
            raise ValueError("hi must be >= lo")
        return {"kind": "in_range", "lo": lo, "hi": hi}
    if kind == "quantile_ge":
        _assert_keys(body, {"kind", "p", "threshold"})
        p = _finite_float(body["p"], "p")
        if p < 0 or p > 1:
            raise ValueError("p must be in [0, 1]")
        threshold = _finite_float(body["threshold"], "threshold")
        return {"kind": "quantile_ge", "p": p, "threshold": threshold}
    _assert_keys(body, {"kind", "expected_sign"})
    expected = body["expected_sign"]
    if expected not in {-1, 0, 1}:
        raise ValueError("expected_sign must be -1, 0, or 1")
    return {"kind": "sign", "expected_sign": int(expected)}


def _normalize_window(body: Any) -> GroundingWindow:
    if not isinstance(body, Mapping):
        raise ValueError("window must be a mapping")
    _assert_keys(body, {"t0", "t1"})
    t0 = _aware_datetime(body["t0"], "t0")
    t1 = _aware_datetime(body["t1"], "t1")
    if t1 < t0:
        raise ValueError("window.t1 must be >= window.t0")
    return GroundingWindow(t0=t0, t1=t1)


def _assert_keys(body: Mapping[str, Any], keys: set[str]) -> None:
    extra = set(body.keys()) - keys
    missing = keys - set(body.keys())
    if extra or missing:
        raise ValueError(f"unexpected keys; missing={sorted(missing)}, extra={sorted(extra)}")


def _finite_float(raw: Any, field: str) -> float:
    if not isinstance(raw, (int, float)):
        raise ValueError(f"{field} must be numeric")
    item = float(raw)
    if not math.isfinite(item):
        raise ValueError(f"{field} must be finite")
    return item


def _aware_datetime(raw: Any, field: str) -> datetime:
    if isinstance(raw, datetime):
        dt = raw
    elif isinstance(raw, str) and raw:
        dt = datetime.fromisoformat(raw)
    else:
        raise TypeError(f"{field} must be datetime or ISO-8601 string")
    if dt.tzinfo is None:
        raise ValueError(f"{field} must be timezone-aware")
    return dt


def _series_for_window(
    *,
    spec_ref: str,
    window: GroundingWindow,
    access: Any,
    spec_registry: Any,
) -> np.ndarray:
    for method_name in ("series", "evaluate_series", "resolve_series"):
        method = getattr(spec_registry, method_name, None)
        if callable(method):
            return np.asarray(method(spec_ref, window.t0, window.t1, access), dtype=float)
    spec = spec_registry.get(spec_ref)
    for method_name in ("series", "evaluate_series", "resolve_series"):
        method = getattr(spec, method_name, None)
        if callable(method):
            return np.asarray(method(window.t0, window.t1, access), dtype=float)
    return np.asarray(resolve_spec_output(spec_ref, window.t1, access, spec_registry), dtype=float)


def _mean_sign(mean_item: float) -> int:
    if abs(mean_item) <= ZERO_MEAN_TOLERANCE:
        return 0
    return 1 if mean_item > 0 else -1
