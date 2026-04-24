from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

import numpy as np

from audit import canonicalize
from rule import Grounding, Rule
from rule.grounding import load_grounding
from rule.predicate_ops import resolve_spec_output


_FLOAT_TEXT = ".17g"
_ZERO = 1e-12


def stable_float_text(raw: Any) -> str:
    item = float(raw)
    if not math.isfinite(item):
        raise ValueError("number must be finite")
    if item == 0.0:
        item = 0.0
    return format(item, _FLOAT_TEXT)


def encode_atom(raw: Any) -> Any:
    if raw is None:
        return {"kind": "none"}
    if isinstance(raw, bool):
        return {"kind": "bool", "item": raw}
    if isinstance(raw, int) and not isinstance(raw, bool):
        return {"kind": "int", "item": raw}
    if isinstance(raw, float):
        return {"kind": "float", "text": stable_float_text(raw)}
    if isinstance(raw, str):
        return {"kind": "str", "text": raw}
    if isinstance(raw, tuple):
        return [encode_atom(item) for item in raw]
    if isinstance(raw, list):
        return [encode_atom(item) for item in raw]
    if isinstance(raw, Mapping):
        return {str(key): encode_atom(raw_item) for key, raw_item in raw.items()}
    raise TypeError(f"unsupported atom type: {type(raw).__name__}")


def hash_payload(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonicalize(encode_atom(dict(payload)))).hexdigest()


def decode_number(raw: Any) -> float:
    if isinstance(raw, bool):
        raise TypeError("bool is not numeric")
    if isinstance(raw, (int, float)):
        item = float(raw)
    elif isinstance(raw, str):
        item = float(raw)
    elif isinstance(raw, Mapping) and raw.get("kind") == "float":
        item = float(raw["text"])
    elif isinstance(raw, Mapping) and raw.get("kind") == "int":
        item = float(raw["item"])
    else:
        raise TypeError("numeric atom required")
    if not math.isfinite(item):
        raise ValueError("number must be finite")
    return item


@dataclass(frozen=True)
class GroundingStats:
    grounding_hash: str
    stats_hash: str
    spec_ref: str
    window_t0: str
    window_t1: str
    assertion_kind_code: int
    assertion_lo: str | None
    assertion_hi: str | None
    assertion_p: str | None
    assertion_threshold: str | None
    assertion_expected_sign: int | None
    count: int
    finite_count: int
    mean: str
    min_item: str
    max_item: str
    span: str
    std: str
    q000: str
    q025: str
    q050: str
    q075: str
    q100: str
    positive_fraction: str
    negative_fraction: str
    zero_fraction: str
    missing_fraction: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "grounding_hash": self.grounding_hash,
            "stats_hash": self.stats_hash,
            "spec_ref": self.spec_ref,
            "window_t0": self.window_t0,
            "window_t1": self.window_t1,
            "assertion_kind_code": self.assertion_kind_code,
            "assertion_lo": self.assertion_lo,
            "assertion_hi": self.assertion_hi,
            "assertion_p": self.assertion_p,
            "assertion_threshold": self.assertion_threshold,
            "assertion_expected_sign": self.assertion_expected_sign,
            "count": self.count,
            "finite_count": self.finite_count,
            "mean": self.mean,
            "min_item": self.min_item,
            "max_item": self.max_item,
            "span": self.span,
            "std": self.std,
            "q000": self.q000,
            "q025": self.q025,
            "q050": self.q050,
            "q075": self.q075,
            "q100": self.q100,
            "positive_fraction": self.positive_fraction,
            "negative_fraction": self.negative_fraction,
            "zero_fraction": self.zero_fraction,
            "missing_fraction": self.missing_fraction,
        }

    def numeric_items(self) -> dict[str, float]:
        return {
            "assertion_kind_code": float(self.assertion_kind_code),
            "assertion_lo": _optional_number(self.assertion_lo),
            "assertion_hi": _optional_number(self.assertion_hi),
            "assertion_p": _optional_number(self.assertion_p),
            "assertion_threshold": _optional_number(self.assertion_threshold),
            "assertion_expected_sign": _optional_number(self.assertion_expected_sign),
            "count": float(self.count),
            "finite_count": float(self.finite_count),
            "mean": decode_number(self.mean),
            "min_item": decode_number(self.min_item),
            "max_item": decode_number(self.max_item),
            "span": decode_number(self.span),
            "std": decode_number(self.std),
            "q000": decode_number(self.q000),
            "q025": decode_number(self.q025),
            "q050": decode_number(self.q050),
            "q075": decode_number(self.q075),
            "q100": decode_number(self.q100),
            "positive_fraction": decode_number(self.positive_fraction),
            "negative_fraction": decode_number(self.negative_fraction),
            "zero_fraction": decode_number(self.zero_fraction),
            "missing_fraction": decode_number(self.missing_fraction),
        }

    def stat(self, name: str) -> float:
        items = self.numeric_items()
        try:
            return items[name]
        except KeyError as exc:
            raise KeyError(f"unknown stat {name!r}") from exc


def compute_grounding_stats(
    source: Rule | Grounding | Mapping[str, Any],
    access: Any,
    spec_registry: Any,
) -> GroundingStats:
    grounding = _coerce_grounding(source)
    arr = np.asarray(
        _series_for_grounding(
            spec_ref=grounding.spec_ref,
            t0=grounding.window.t0,
            t1=grounding.window.t1,
            access=access,
            spec_registry=spec_registry,
        ),
        dtype=float,
    ).reshape(-1)
    if arr.size == 0:
        raise ValueError("grounding yielded no items")

    finite = arr[np.isfinite(arr)]
    if finite.size == 0:
        raise ValueError("grounding yielded no finite items")

    count = int(arr.size)
    finite_count = int(finite.size)
    miss = float(count - finite_count) / float(count)
    mean_item = float(np.mean(finite))
    min_item = float(np.min(finite))
    max_item = float(np.max(finite))
    qs = np.quantile(finite, [0.0, 0.25, 0.5, 0.75, 1.0])
    pos = float(np.count_nonzero(finite > _ZERO)) / float(finite_count)
    neg = float(np.count_nonzero(finite < -_ZERO)) / float(finite_count)
    zero = float(np.count_nonzero(np.abs(finite) <= _ZERO)) / float(finite_count)

    grounding_dict = grounding.as_dict()
    grounding_hash = hash_payload(grounding_dict)
    assertion = grounding.assertion
    payload = {
        "spec_ref": grounding.spec_ref,
        "window_t0": grounding.window.t0.isoformat(),
        "window_t1": grounding.window.t1.isoformat(),
        "assertion_kind_code": _assertion_kind_code(assertion["kind"]),
        "assertion_lo": _optional_float_text(assertion.get("lo")),
        "assertion_hi": _optional_float_text(assertion.get("hi")),
        "assertion_p": _optional_float_text(assertion.get("p")),
        "assertion_threshold": _optional_float_text(assertion.get("threshold")),
        "assertion_expected_sign": assertion.get("expected_sign"),
        "count": count,
        "finite_count": finite_count,
        "mean": stable_float_text(mean_item),
        "min_item": stable_float_text(min_item),
        "max_item": stable_float_text(max_item),
        "span": stable_float_text(max_item - min_item),
        "std": stable_float_text(float(np.std(finite))),
        "q000": stable_float_text(float(qs[0])),
        "q025": stable_float_text(float(qs[1])),
        "q050": stable_float_text(float(qs[2])),
        "q075": stable_float_text(float(qs[3])),
        "q100": stable_float_text(float(qs[4])),
        "positive_fraction": stable_float_text(pos),
        "negative_fraction": stable_float_text(neg),
        "zero_fraction": stable_float_text(zero),
        "missing_fraction": stable_float_text(miss),
    }
    stats_hash = hash_payload(payload)
    return GroundingStats(
        grounding_hash=grounding_hash,
        stats_hash=stats_hash,
        **payload,
    )


def _coerce_grounding(source: Rule | Grounding | Mapping[str, Any]) -> Grounding:
    if isinstance(source, Rule):
        return source.grounding
    if isinstance(source, Grounding):
        return source
    return load_grounding(source)


def _series_for_grounding(
    *,
    spec_ref: str,
    t0: datetime,
    t1: datetime,
    access: Any,
    spec_registry: Any,
) -> np.ndarray:
    for method_name in ("series", "evaluate_series", "resolve_series"):
        method = getattr(spec_registry, method_name, None)
        if callable(method):
            return np.asarray(method(spec_ref, t0, t1, access), dtype=float)
    spec = spec_registry.get(spec_ref)
    for method_name in ("series", "evaluate_series", "resolve_series"):
        method = getattr(spec, method_name, None)
        if callable(method):
            return np.asarray(method(t0, t1, access), dtype=float)
    return np.asarray(resolve_spec_output(spec_ref, t1, access, spec_registry), dtype=float)


def _assertion_kind_code(kind: str) -> int:
    table = {"in_range": 1, "quantile_ge": 2, "sign": 3}
    return table[kind]


def _optional_float_text(raw: Any) -> str | None:
    if raw is None:
        return None
    return stable_float_text(raw)


def _optional_number(raw: Any) -> float:
    if raw is None:
        return 0.0
    return decode_number(raw)
