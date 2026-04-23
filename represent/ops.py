from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from typing import Any, Callable

import numpy as np


def _noop_args(args: dict[str, Any]) -> None:
    return None


def _ensure_no_args(args: dict[str, Any]) -> None:
    if args:
        raise ValueError("op does not accept args")


def _ensure_hash_arg(args: dict[str, Any]) -> None:
    if set(args.keys()) != {"hash"}:
        raise ValueError("raw_get args must be {'hash': ...}")
    value = args["hash"]
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError("raw_get hash must be a 64-character string")


def _ensure_literal_args(args: dict[str, Any]) -> None:
    if set(args.keys()) != {"value"}:
        raise ValueError("literal args must be {'value': ...}")


def _ensure_path_args(args: dict[str, Any]) -> None:
    if set(args.keys()) != {"path"}:
        raise ValueError("json_get args must be {'path': [...]}")
    path = args["path"]
    if not isinstance(path, list):
        raise ValueError("json_get path must be a list")
    for item in path:
        if not isinstance(item, (str, int)):
            raise ValueError("json_get path items must be strings or integers")


def _ensure_axis_args(args: dict[str, Any]) -> None:
    extra = set(args.keys()) - {"axis"}
    if extra:
        raise ValueError(f"unexpected args: {sorted(extra)}")
    _normalize_axis(args.get("axis", 0))


def _ensure_reduction_args(args: dict[str, Any]) -> None:
    extra = set(args.keys()) - {"axis", "keepdims"}
    if extra:
        raise ValueError(f"unexpected args: {sorted(extra)}")
    _normalize_axis(args.get("axis"))
    keepdims = args.get("keepdims", False)
    if not isinstance(keepdims, bool):
        raise ValueError("keepdims must be a bool")


def _ensure_z_score_args(args: dict[str, Any]) -> None:
    extra = set(args.keys()) - {"axis", "epsilon"}
    if extra:
        raise ValueError(f"unexpected args: {sorted(extra)}")
    _normalize_axis(args.get("axis"))
    epsilon = args.get("epsilon", 1e-12)
    if not isinstance(epsilon, (int, float)) or float(epsilon) < 0:
        raise ValueError("epsilon must be a non-negative number")


def _normalize_axis(value: Any) -> int | tuple[int, ...] | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, list) and all(isinstance(item, int) for item in value):
        return tuple(value)
    raise ValueError("axis must be an int, a list of ints, or null")


def _as_array(value: Any, *, dtype: Any | None = None) -> np.ndarray:
    return np.array(value, dtype=dtype, copy=True, order="C")


def _raw_get(args: dict[str, Any], inputs: list[Any], ctx: Any) -> bytes:
    return ctx.read_raw(args["hash"])


def _literal(args: dict[str, Any], inputs: list[Any], ctx: Any) -> Any:
    return copy.deepcopy(args["value"])


def _decode_json(args: dict[str, Any], inputs: list[Any], ctx: Any) -> Any:
    value = inputs[0]
    if isinstance(value, bytes):
        text = value.decode("utf-8")
    elif isinstance(value, str):
        text = value
    else:
        raise TypeError("decode_json expects bytes or str input")
    return json.loads(text)


def _decode_text(args: dict[str, Any], inputs: list[Any], ctx: Any) -> str:
    value = inputs[0]
    if isinstance(value, bytes):
        return value.decode("utf-8")
    if isinstance(value, str):
        return value
    raise TypeError("decode_text expects bytes or str input")


def _json_get(args: dict[str, Any], inputs: list[Any], ctx: Any) -> Any:
    current = inputs[0]
    for item in args["path"]:
        if isinstance(item, int):
            if not isinstance(current, list):
                raise TypeError("integer path item requires list input")
            current = current[item]
            continue
        if not isinstance(current, dict):
            raise TypeError("string path item requires dict input")
        current = current[item]
    return current


def _cast_float64(args: dict[str, Any], inputs: list[Any], ctx: Any) -> np.ndarray:
    return _as_array(inputs[0], dtype=np.float64)


def _stack(args: dict[str, Any], inputs: list[Any], ctx: Any) -> np.ndarray:
    axis = int(args.get("axis", 0))
    arrays = [_as_array(item) for item in inputs]
    return np.ascontiguousarray(np.stack(arrays, axis=axis))


def _concatenate(args: dict[str, Any], inputs: list[Any], ctx: Any) -> np.ndarray:
    axis = int(args.get("axis", 0))
    arrays = [_as_array(item) for item in inputs]
    return np.ascontiguousarray(np.concatenate(arrays, axis=axis))


def _mean(args: dict[str, Any], inputs: list[Any], ctx: Any) -> np.ndarray:
    axis = _normalize_axis(args.get("axis"))
    keepdims = args.get("keepdims", False)
    array = _as_array(inputs[0])
    result = np.mean(array, axis=axis, keepdims=keepdims, dtype=np.float64)
    return _as_array(result)


def _sum(args: dict[str, Any], inputs: list[Any], ctx: Any) -> np.ndarray:
    axis = _normalize_axis(args.get("axis"))
    keepdims = args.get("keepdims", False)
    array = _as_array(inputs[0])
    result = np.sum(array, axis=axis, keepdims=keepdims, dtype=np.float64)
    return _as_array(result)


def _z_score(args: dict[str, Any], inputs: list[Any], ctx: Any) -> np.ndarray:
    axis = _normalize_axis(args.get("axis"))
    epsilon = float(args.get("epsilon", 1e-12))
    array = _as_array(inputs[0], dtype=np.float64)
    mean = np.mean(array, axis=axis, keepdims=True, dtype=np.float64)
    std = np.std(array, axis=axis, keepdims=True, dtype=np.float64)
    safe_std = np.where(std < epsilon, epsilon, std)
    return np.ascontiguousarray((array - mean) / safe_std)


@dataclass(frozen=True)
class PrimitiveOp:
    name: str
    min_inputs: int
    max_inputs: int | None
    op_version: str
    fn: Callable[[dict[str, Any], list[Any], Any], Any]
    arg_validator: Callable[[dict[str, Any]], None] = _noop_args

    def validate(self, *, node_id: str, args: dict[str, Any], input_count: int) -> None:
        if input_count < self.min_inputs:
            raise ValueError(
                f"node {node_id}: op {self.name!r} requires at least {self.min_inputs} inputs"
            )
        if self.max_inputs is not None and input_count > self.max_inputs:
            raise ValueError(
                f"node {node_id}: op {self.name!r} accepts at most {self.max_inputs} inputs"
            )
        self.arg_validator(args)

    def run(self, args: dict[str, Any], inputs: list[Any], ctx: Any) -> Any:
        return self.fn(args, inputs, ctx)


DEFAULT_OPS: dict[str, PrimitiveOp] = {
    "raw_get": PrimitiveOp(
        name="raw_get",
        min_inputs=0,
        max_inputs=0,
        op_version="1",
        fn=_raw_get,
        arg_validator=_ensure_hash_arg,
    ),
    "literal": PrimitiveOp(
        name="literal",
        min_inputs=0,
        max_inputs=0,
        op_version="1",
        fn=_literal,
        arg_validator=_ensure_literal_args,
    ),
    "decode_json": PrimitiveOp(
        name="decode_json",
        min_inputs=1,
        max_inputs=1,
        op_version="1",
        fn=_decode_json,
        arg_validator=_ensure_no_args,
    ),
    "decode_text": PrimitiveOp(
        name="decode_text",
        min_inputs=1,
        max_inputs=1,
        op_version="1",
        fn=_decode_text,
        arg_validator=_ensure_no_args,
    ),
    "json_get": PrimitiveOp(
        name="json_get",
        min_inputs=1,
        max_inputs=1,
        op_version="1",
        fn=_json_get,
        arg_validator=_ensure_path_args,
    ),
    "cast_float64": PrimitiveOp(
        name="cast_float64",
        min_inputs=1,
        max_inputs=1,
        op_version="1",
        fn=_cast_float64,
        arg_validator=_ensure_no_args,
    ),
    "stack": PrimitiveOp(
        name="stack",
        min_inputs=1,
        max_inputs=None,
        op_version="1",
        fn=_stack,
        arg_validator=_ensure_axis_args,
    ),
    "concatenate": PrimitiveOp(
        name="concatenate",
        min_inputs=1,
        max_inputs=None,
        op_version="1",
        fn=_concatenate,
        arg_validator=_ensure_axis_args,
    ),
    "mean": PrimitiveOp(
        name="mean",
        min_inputs=1,
        max_inputs=1,
        op_version="1",
        fn=_mean,
        arg_validator=_ensure_reduction_args,
    ),
    "sum": PrimitiveOp(
        name="sum",
        min_inputs=1,
        max_inputs=1,
        op_version="1",
        fn=_sum,
        arg_validator=_ensure_reduction_args,
    ),
    "z_score": PrimitiveOp(
        name="z_score",
        min_inputs=1,
        max_inputs=1,
        op_version="1",
        fn=_z_score,
        arg_validator=_ensure_z_score_args,
    ),
}
