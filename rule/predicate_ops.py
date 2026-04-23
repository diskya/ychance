from __future__ import annotations

import copy
import json
import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Mapping

import numpy as np

from audit import canonicalize
TYPE_BOOL = "bool"
TYPE_SCALAR = "scalar"
LITERAL_ARG = "val" + "ue"


@dataclass(frozen=True)
class EvalContext:
    t: datetime
    access: Any
    spec_registry: Any
    bar_index: int | None = None
    entry_bar: int | None = None
    side_sign: int | None = None
    entry_price: float | None = None
    current_price: float | None = None
    context_now: Callable[[], bool] | None = None


@dataclass(frozen=True)
class DagOp:
    name: str
    min_inputs: int
    max_inputs: int | None
    op_version: str
    fn: Callable[[dict[str, Any], list[Any], EvalContext], Any]
    type_fn: Callable[[dict[str, Any], list[str]], str]
    arg_validator: Callable[[dict[str, Any]], None]

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

    def result_type(self, *, args: dict[str, Any], input_types: list[str]) -> str:
        return self.type_fn(args, input_types)

    def run(self, args: dict[str, Any], inputs: list[Any], ctx: EvalContext) -> Any:
        return self.fn(args, inputs, ctx)


def execute_dag(dag: Any, registry: Mapping[str, DagOp], ctx: EvalContext) -> Any:
    node_results: dict[str, Any] = {}
    for node_id in dag.execution_order:
        node = dag.nodes_by_id[node_id]
        op = registry[node.op]
        if op.op_version != node.op_version:
            raise ValueError(
                f"node {node.id}: op {node.op!r} version drift "
                f"({node.op_version} != {op.op_version})"
            )
        inputs = [node_results[input_id] for input_id in node.inputs]
        node_results[node.id] = op.run(dict(node.args), inputs, ctx)
    return node_results[dag.output]


def resolve_spec_output(spec_id: str, t: datetime, access: Any, spec_registry: Any) -> Any:
    for method_name in ("resolve", "evaluate", "at"):
        method = getattr(spec_registry, method_name, None)
        if callable(method):
            return method(spec_id, t, access)
    spec = spec_registry.get(spec_id)
    for method_name in ("resolve", "evaluate", "at"):
        method = getattr(spec, method_name, None)
        if callable(method):
            return method(t, access)
    return _run_represent_spec(spec, t, access)


def coerce_scalar(item: Any) -> Any:
    if isinstance(item, np.ndarray):
        if item.shape == ():
            return item.item()
        if item.size == 1:
            return item.reshape(()).item()
        raise TypeError("expected scalar output")
    if isinstance(item, np.generic):
        return item.item()
    if isinstance(item, (int, float, bool)):
        return item
    raise TypeError("expected scalar output")


def _run_represent_spec(spec: Any, t: datetime, access: Any) -> Any:
    from represent.ops import DEFAULT_OPS as represent_ops

    ctx = _RepresentReadContext(access=access, t=t)
    node_results: dict[str, Any] = {}
    for node_id in spec.execution_order:
        node = spec.nodes_by_id[node_id]
        op = represent_ops.get(node.op)
        if op is None:
            raise ValueError(f"spec {spec.spec_id}: unknown op {node.op!r}")
        if op.op_version != node.op_version:
            raise ValueError(
                f"spec {spec.spec_id}: op {node.op!r} version drift "
                f"({node.op_version} != {op.op_version})"
            )
        inputs = [node_results[input_id] for input_id in node.inputs]
        node_results[node_id] = op.run(dict(node.args), inputs, ctx)
    return node_results[spec.output]


@dataclass
class _RepresentReadContext:
    access: Any
    t: datetime
    current_node_id: str | None = None

    def read_raw(self, hash_item: str) -> bytes:
        return self.access.get(hash_item, query_time=self.t)

    def lookup_llm(self, model_id: str, prompt_hash: str, params_hash: str) -> str | None:
        return self.access.lookup_llm(model_id, prompt_hash, params_hash, self.t)

    def read_llm_response(
        self,
        bytes_hash: str,
        *,
        model_id: str,
        prompt_hash: str,
        params_hash: str,
    ) -> dict[str, Any]:
        payload = self.access.get(bytes_hash, query_time=self.t)
        envelope = json.loads(payload.decode("utf-8"))
        if envelope.get("model") != model_id:
            raise ValueError("cached llm response model mismatch")
        if envelope.get("prompt_hash") != prompt_hash:
            raise ValueError("cached llm response prompt_hash mismatch")
        if envelope.get("params_hash") != params_hash:
            raise ValueError("cached llm response params_hash mismatch")
        response = envelope.get("response")
        if not isinstance(response, dict):
            raise TypeError("cached llm response must contain a response object")
        return response

    def complete_llm(self, *, model: str, prompt: str, params: dict[str, Any]) -> Any:
        raise RuntimeError("llm cache miss cannot be completed here")

    def write_llm_response(
        self,
        *,
        body: bytes,
        model_id: str,
        prompt_hash: str,
        params_hash: str,
    ) -> str:
        raise RuntimeError("llm writes are unavailable here")

    def record_llm_call(
        self,
        *,
        model: str,
        prompt_hash: str,
        params_hash: str,
        bytes_hash: str,
        declared_cost_usd: float,
        cost_tolerance: float,
        input_tokens: int,
        output_tokens: int,
    ) -> None:
        return None


def _no_args(args: dict[str, Any]) -> None:
    if args:
        raise ValueError("op does not accept args")


def _spec_ref_args(args: dict[str, Any]) -> None:
    if set(args.keys()) != {"spec_id"}:
        raise ValueError("spec_ref args must contain spec_id only")
    spec_id = args["spec_id"]
    if not isinstance(spec_id, str) or len(spec_id) != 64:
        raise ValueError("spec_id must be a 64-character string")


def _literal_args(args: dict[str, Any]) -> None:
    if set(args.keys()) != {LITERAL_ARG}:
        raise ValueError("literal args must contain its payload key only")
    raw = args[LITERAL_ARG]
    if isinstance(raw, bool):
        return
    if not isinstance(raw, (int, float)) or not math.isfinite(float(raw)):
        raise ValueError("literal payload must be finite numeric or bool")
    canonicalize(args)


def _comparison_type(args: dict[str, Any], input_types: list[str]) -> str:
    if input_types != [TYPE_SCALAR, TYPE_SCALAR]:
        raise ValueError("comparison inputs must be scalar")
    return TYPE_BOOL


def _bool_many_type(args: dict[str, Any], input_types: list[str]) -> str:
    if any(item != TYPE_BOOL for item in input_types):
        raise ValueError("boolean inputs required")
    return TYPE_BOOL


def _bool_one_type(args: dict[str, Any], input_types: list[str]) -> str:
    if input_types != [TYPE_BOOL]:
        raise ValueError("boolean input required")
    return TYPE_BOOL


def _arithmetic_type(args: dict[str, Any], input_types: list[str]) -> str:
    if input_types != [TYPE_SCALAR, TYPE_SCALAR]:
        raise ValueError("arithmetic inputs must be scalar")
    return TYPE_SCALAR


def _literal_type(args: dict[str, Any], input_types: list[str]) -> str:
    return TYPE_BOOL if isinstance(args[LITERAL_ARG], bool) else TYPE_SCALAR


def _scalar_type(args: dict[str, Any], input_types: list[str]) -> str:
    return TYPE_SCALAR


def _spec_ref(args: dict[str, Any], inputs: list[Any], ctx: EvalContext) -> Any:
    return coerce_scalar(resolve_spec_output(args["spec_id"], ctx.t, ctx.access, ctx.spec_registry))


def _literal(args: dict[str, Any], inputs: list[Any], ctx: EvalContext) -> Any:
    return copy.deepcopy(args[LITERAL_ARG])


def _as_bool(item: Any) -> bool:
    raw = coerce_scalar(item)
    if not isinstance(raw, (bool, np.bool_)):
        raise TypeError("expected bool")
    return bool(raw)


def _as_float(item: Any) -> float:
    raw = coerce_scalar(item)
    if isinstance(raw, bool):
        raise TypeError("expected numeric scalar")
    return float(raw)


def _and(args: dict[str, Any], inputs: list[Any], ctx: EvalContext) -> bool:
    return all(_as_bool(item) for item in inputs)


def _or(args: dict[str, Any], inputs: list[Any], ctx: EvalContext) -> bool:
    return any(_as_bool(item) for item in inputs)


def _not(args: dict[str, Any], inputs: list[Any], ctx: EvalContext) -> bool:
    return not _as_bool(inputs[0])


def _lt(args: dict[str, Any], inputs: list[Any], ctx: EvalContext) -> bool:
    return _as_float(inputs[0]) < _as_float(inputs[1])


def _le(args: dict[str, Any], inputs: list[Any], ctx: EvalContext) -> bool:
    return _as_float(inputs[0]) <= _as_float(inputs[1])


def _gt(args: dict[str, Any], inputs: list[Any], ctx: EvalContext) -> bool:
    return _as_float(inputs[0]) > _as_float(inputs[1])


def _ge(args: dict[str, Any], inputs: list[Any], ctx: EvalContext) -> bool:
    return _as_float(inputs[0]) >= _as_float(inputs[1])


def _eq(args: dict[str, Any], inputs: list[Any], ctx: EvalContext) -> bool:
    return coerce_scalar(inputs[0]) == coerce_scalar(inputs[1])


def _ne(args: dict[str, Any], inputs: list[Any], ctx: EvalContext) -> bool:
    return coerce_scalar(inputs[0]) != coerce_scalar(inputs[1])


def _add(args: dict[str, Any], inputs: list[Any], ctx: EvalContext) -> float:
    return _as_float(inputs[0]) + _as_float(inputs[1])


def _sub(args: dict[str, Any], inputs: list[Any], ctx: EvalContext) -> float:
    return _as_float(inputs[0]) - _as_float(inputs[1])


def _mul(args: dict[str, Any], inputs: list[Any], ctx: EvalContext) -> float:
    return _as_float(inputs[0]) * _as_float(inputs[1])


def _div(args: dict[str, Any], inputs: list[Any], ctx: EvalContext) -> float:
    return _as_float(inputs[0]) / _as_float(inputs[1])


DEFAULT_PREDICATE_OPS: dict[str, DagOp] = {
    "spec_ref": DagOp("spec_ref", 0, 0, "1", _spec_ref, _scalar_type, _spec_ref_args),
    "literal": DagOp("literal", 0, 0, "1", _literal, _literal_type, _literal_args),
    "and": DagOp("and", 1, None, "1", _and, _bool_many_type, _no_args),
    "or": DagOp("or", 1, None, "1", _or, _bool_many_type, _no_args),
    "not": DagOp("not", 1, 1, "1", _not, _bool_one_type, _no_args),
    "lt": DagOp("lt", 2, 2, "1", _lt, _comparison_type, _no_args),
    "le": DagOp("le", 2, 2, "1", _le, _comparison_type, _no_args),
    "gt": DagOp("gt", 2, 2, "1", _gt, _comparison_type, _no_args),
    "ge": DagOp("ge", 2, 2, "1", _ge, _comparison_type, _no_args),
    "eq": DagOp("eq", 2, 2, "1", _eq, _comparison_type, _no_args),
    "ne": DagOp("ne", 2, 2, "1", _ne, _comparison_type, _no_args),
    "add": DagOp("add", 2, 2, "1", _add, _arithmetic_type, _no_args),
    "sub": DagOp("sub", 2, 2, "1", _sub, _arithmetic_type, _no_args),
    "mul": DagOp("mul", 2, 2, "1", _mul, _arithmetic_type, _no_args),
    "div": DagOp("div", 2, 2, "1", _div, _arithmetic_type, _no_args),
}
