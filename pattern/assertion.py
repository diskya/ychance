from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

import numpy as np

from audit import canonicalize


class AssertionValidationError(ValueError):
    """Raised when an assertion body is not computable."""


@dataclass(frozen=True)
class AssertionOp:
    kind: str
    op_version: str
    normalize: Callable[[Mapping[str, Any]], dict[str, Any]]
    fn: Callable[[dict[str, Any], Any], bool]

    def validate(self) -> None:
        if not isinstance(self.kind, str) or not self.kind:
            raise AssertionValidationError("assertion kind must be a non-empty string")
        if not isinstance(self.op_version, str) or not self.op_version:
            raise AssertionValidationError("assertion op_version must be a non-empty string")


@dataclass(frozen=True)
class Assertion:
    kind: str
    args: dict[str, Any]
    op_version: str
    _fn: Callable[[dict[str, Any], Any], bool] = field(repr=False, compare=False)

    def public_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "args": _canonical_copy(self.args)}

    def hash_dict(self) -> dict[str, Any]:
        data = self.public_dict()
        data["op_version"] = self.op_version
        return data

    def evaluate(self, value: Any) -> bool:
        return bool(self._fn(self.args, value))


def load_assertion(
    body: Mapping[str, Any] | Assertion,
    *,
    op_registry: Mapping[str, AssertionOp] | None = None,
) -> Assertion:
    if isinstance(body, Assertion):
        return body
    if not isinstance(body, Mapping):
        raise AssertionValidationError("assertion must be a mapping")
    if set(body.keys()) != {"kind", "args"}:
        raise AssertionValidationError("assertion must contain exactly kind and args")
    kind = body["kind"]
    if not isinstance(kind, str) or not kind:
        raise AssertionValidationError("assertion kind must be a non-empty string")
    registry = dict(op_registry or DEFAULT_ASSERTION_OPS)
    op = registry.get(kind)
    if op is None:
        raise AssertionValidationError(f"unknown assertion kind {kind!r}")
    op.validate()
    args = body["args"]
    if not isinstance(args, Mapping):
        raise AssertionValidationError("assertion args must be a mapping")
    normalized = op.normalize(args)
    return Assertion(kind=kind, args=normalized, op_version=op.op_version, _fn=op.fn)


def _canonical_copy(value: Any) -> Any:
    return json.loads(canonicalize(value).decode("utf-8"))


def _finite_float(value: Any, label: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise AssertionValidationError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise AssertionValidationError(f"{label} must be finite")
    return result


def _normalize_in_range(args: Mapping[str, Any]) -> dict[str, Any]:
    if set(args.keys()) != {"lo", "hi"}:
        raise AssertionValidationError("in_range args must be lo and hi")
    lo = _finite_float(args["lo"], "in_range lo")
    hi = _finite_float(args["hi"], "in_range hi")
    if hi < lo:
        raise AssertionValidationError("in_range hi must be >= lo")
    return {"lo": lo, "hi": hi}


def _normalize_quantile_ge(args: Mapping[str, Any]) -> dict[str, Any]:
    if set(args.keys()) != {"p", "threshold"}:
        raise AssertionValidationError("quantile_ge args must be p and threshold")
    p = _finite_float(args["p"], "quantile_ge p")
    if p < 0.0 or p > 1.0:
        raise AssertionValidationError("quantile_ge p must be in [0, 1]")
    threshold = _finite_float(args["threshold"], "quantile_ge threshold")
    return {"p": p, "threshold": threshold}


def _normalize_sign(args: Mapping[str, Any]) -> dict[str, Any]:
    if set(args.keys()) != {"expected_sign"}:
        raise AssertionValidationError("sign args must be expected_sign")
    value = args["expected_sign"]
    if isinstance(value, str):
        labels = {"negative": -1, "zero": 0, "positive": 1}
        if value not in labels:
            raise AssertionValidationError(
                "sign expected_sign must be negative, zero, positive, -1, 0, or 1"
            )
        sign_value = labels[value]
    elif isinstance(value, int) and not isinstance(value, bool):
        if value not in {-1, 0, 1}:
            raise AssertionValidationError("sign expected_sign must be -1, 0, or 1")
        sign_value = int(value)
    else:
        raise AssertionValidationError("sign expected_sign must be a string or int")
    return {"expected_sign": sign_value}


def _numeric_array(value: Any) -> np.ndarray:
    if hasattr(value, "outputs") and hasattr(value.outputs, "tensor"):
        value = value.outputs.tensor
    elif hasattr(value, "tensor"):
        value = value.tensor
    try:
        array = np.asarray(value, dtype=float).reshape(-1)
    except (TypeError, ValueError):
        return np.asarray([], dtype=float)
    return array


def _usable(array: np.ndarray) -> bool:
    return bool(array.size) and bool(np.isfinite(array).all())


def _in_range(args: dict[str, Any], value: Any) -> bool:
    array = _numeric_array(value)
    if not _usable(array):
        return False
    return bool(np.all((array >= args["lo"]) & (array <= args["hi"])))


def _quantile_ge(args: dict[str, Any], value: Any) -> bool:
    array = _numeric_array(value)
    if not _usable(array):
        return False
    return bool(float(np.quantile(array, args["p"])) >= args["threshold"])


def _sign(args: dict[str, Any], value: Any) -> bool:
    array = _numeric_array(value)
    if not _usable(array):
        return False
    expected = args["expected_sign"]
    if expected < 0:
        return bool(np.all(array < 0.0))
    if expected > 0:
        return bool(np.all(array > 0.0))
    return bool(np.all(array == 0.0))


DEFAULT_ASSERTION_OPS: dict[str, AssertionOp] = {
    "in_range": AssertionOp(
        kind="in_range",
        op_version="1",
        normalize=_normalize_in_range,
        fn=_in_range,
    ),
    "quantile_ge": AssertionOp(
        kind="quantile_ge",
        op_version="1",
        normalize=_normalize_quantile_ge,
        fn=_quantile_ge,
    ),
    "sign": AssertionOp(
        kind="sign",
        op_version="1",
        normalize=_normalize_sign,
        fn=_sign,
    ),
}
