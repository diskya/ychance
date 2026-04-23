from __future__ import annotations

import hashlib
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from audit import canonicalize

from . import action as action_module
from .action import Action, load_action
from .exit_ops import DEFAULT_EXIT_OPS
from .grounding import Grounding, load_grounding
from .predicate_ops import (
    DEFAULT_PREDICATE_OPS,
    TYPE_BOOL,
    DagOp,
    EvalContext,
    execute_dag,
)


class RuleValidationError(ValueError):
    pass


_RULE_KEYS = frozenset(
    {
        "context",
        "exit",
        "action",
        "action_schema_version",
        "horizon_bars",
        "cadence",
        "grounding",
        "price_spec_ref",
    }
)
_DAG_KEYS = frozenset({"nodes", "output"})
_NODE_KEYS = frozenset({"id", "op", "args", "inputs"})
_CADENCE_KEYS = frozenset({"kind", "step_seconds"})


@dataclass(frozen=True)
class RuleNode:
    id: str
    op: str
    op_version: str
    args: dict[str, Any]
    inputs: tuple[str, ...]
    result_type: str

    def public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "op": self.op,
            "args": dict(self.args),
            "inputs": list(self.inputs),
        }


@dataclass(frozen=True)
class RuleDag:
    nodes: tuple[RuleNode, ...]
    output: str
    topological_order: tuple[str, ...]
    execution_order: tuple[str, ...]

    @property
    def nodes_by_id(self) -> dict[str, RuleNode]:
        return {node.id: node for node in self.nodes}

    def public_dict(self) -> dict[str, Any]:
        return {
            "nodes": [node.public_dict() for node in self.nodes],
            "output": self.output,
        }


@dataclass(frozen=True)
class Cadence:
    kind: str
    step_seconds: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "step_seconds": self.step_seconds,
        }


@dataclass(frozen=True)
class Rule:
    rule_id: str
    context: RuleDag
    exit: RuleDag
    action: Action
    horizon_bars: int
    cadence: Cadence
    grounding: Grounding
    price_spec_ref: str

    def public_body(self) -> dict[str, Any]:
        return {
            "context": self.context.public_dict(),
            "exit": self.exit.public_dict(),
            "action": self.action.as_dict(),
            "action_schema_version": action_module.action_schema_version,
            "horizon_bars": self.horizon_bars,
            "cadence": self.cadence.as_dict(),
            "grounding": self.grounding.as_dict(),
            "price_spec_ref": self.price_spec_ref,
        }

    def to_dict(self) -> dict[str, Any]:
        data = self.public_body()
        data["rule_id"] = self.rule_id
        return data

    def evaluate(self, t: datetime, access: Any, spec_registry: Any) -> bool:
        _ensure_aware_datetime(t, "t")
        ctx = EvalContext(t=t, access=access, spec_registry=spec_registry)
        return bool(execute_dag(self.context, DEFAULT_PREDICATE_OPS, ctx))

    def simulate(
        self,
        window: tuple[datetime, datetime],
        access: Any,
        spec_registry: Any,
    ) -> list[Any]:
        from .simulate import simulate_rule

        return simulate_rule(self, window, access, spec_registry)

    def _evaluate_context_with_registry(
        self,
        t: datetime,
        access: Any,
        spec_registry: Any,
        predicate_registry: Mapping[str, DagOp],
    ) -> bool:
        ctx = EvalContext(t=t, access=access, spec_registry=spec_registry)
        return bool(execute_dag(self.context, predicate_registry, ctx))

    def _evaluate_exit_with_registry(
        self,
        *,
        t: datetime,
        access: Any,
        spec_registry: Any,
        predicate_registry: Mapping[str, DagOp],
        exit_registry: Mapping[str, DagOp],
        bar_index: int,
        entry_bar: int,
        side_sign: int,
        entry_price: float,
        current_price: float,
    ) -> bool:
        def context_now() -> bool:
            return self._evaluate_context_with_registry(
                t,
                access,
                spec_registry,
                predicate_registry,
            )

        ctx = EvalContext(
            t=t,
            access=access,
            spec_registry=spec_registry,
            bar_index=bar_index,
            entry_bar=entry_bar,
            side_sign=side_sign,
            entry_price=entry_price,
            current_price=current_price,
            context_now=context_now,
        )
        return bool(execute_dag(self.exit, exit_registry, ctx))


def finalize_rule(
    body: Mapping[str, Any],
    *,
    predicate_registry: Mapping[str, DagOp] | None = None,
    exit_registry: Mapping[str, DagOp] | None = None,
) -> Rule:
    pred_ops = dict(predicate_registry or DEFAULT_PREDICATE_OPS)
    ex_ops = dict(exit_registry or DEFAULT_EXIT_OPS)
    normalized, context, exit_dag = _normalize_and_resolve(body, pred_ops, ex_ops)
    rule_id = _compute_rule_id(normalized, context, exit_dag)
    return Rule(
        rule_id=rule_id,
        context=context,
        exit=exit_dag,
        action=load_action(normalized["action"]),
        horizon_bars=normalized["horizon_bars"],
        cadence=Cadence(**normalized["cadence"]),
        grounding=load_grounding(normalized["grounding"]),
        price_spec_ref=normalized["price_spec_ref"],
    )


def load_rule(
    document: Mapping[str, Any] | Rule,
    *,
    predicate_registry: Mapping[str, DagOp] | None = None,
    exit_registry: Mapping[str, DagOp] | None = None,
) -> Rule:
    if isinstance(document, Rule):
        return document
    if not isinstance(document, Mapping):
        raise RuleValidationError("rule must be a mapping")
    doc = dict(document)
    rule_id = doc.pop("rule_id", None)
    if not isinstance(rule_id, str) or len(rule_id) != 64:
        raise RuleValidationError("rule_id must be a 64-character string")
    rule = finalize_rule(doc, predicate_registry=predicate_registry, exit_registry=exit_registry)
    if rule.rule_id != rule_id:
        raise RuleValidationError("rule_id does not match the canonical rule body")
    return rule


def _normalize_and_resolve(
    body: Mapping[str, Any],
    predicate_registry: Mapping[str, DagOp],
    exit_registry: Mapping[str, DagOp],
) -> tuple[dict[str, Any], RuleDag, RuleDag]:
    if not isinstance(body, Mapping):
        raise RuleValidationError("rule body must be a mapping")
    extra = set(body.keys()) - _RULE_KEYS
    missing = _RULE_KEYS - set(body.keys())
    if extra or missing:
        raise RuleValidationError(
            "rule body has wrong keys; "
            f"missing={sorted(missing)}, extra={sorted(extra)}"
        )

    action_version = body["action_schema_version"]
    if action_version != action_module.action_schema_version:
        raise RuleValidationError("action_schema_version does not match module constant")

    try:
        action = load_action(body["action"])
        grounding = load_grounding(body["grounding"])
    except (TypeError, ValueError) as exc:
        raise RuleValidationError(str(exc)) from exc

    horizon_bars = body["horizon_bars"]
    if not isinstance(horizon_bars, int) or horizon_bars <= 0:
        raise RuleValidationError("horizon_bars must be a positive int")

    cadence = _normalize_cadence(body["cadence"])
    price_spec_ref = body["price_spec_ref"]
    if not isinstance(price_spec_ref, str) or len(price_spec_ref) != 64:
        raise RuleValidationError("price_spec_ref must be a 64-character string")

    context = _normalize_dag(
        body["context"],
        predicate_registry,
        section="context",
        expected_root_type=TYPE_BOOL,
    )
    exit_dag = _normalize_dag(
        body["exit"],
        exit_registry,
        section="exit",
        expected_root_type=TYPE_BOOL,
    )

    normalized = {
        "context": context.public_dict(),
        "exit": exit_dag.public_dict(),
        "action": action.as_dict(),
        "action_schema_version": action_module.action_schema_version,
        "horizon_bars": horizon_bars,
        "cadence": cadence.as_dict(),
        "grounding": grounding.as_dict(),
        "price_spec_ref": price_spec_ref,
    }
    return normalized, context, exit_dag


def _normalize_cadence(body: Any) -> Cadence:
    if not isinstance(body, Mapping):
        raise RuleValidationError("cadence must be a mapping")
    extra = set(body.keys()) - _CADENCE_KEYS
    missing = _CADENCE_KEYS - set(body.keys())
    if extra or missing:
        raise RuleValidationError(
            "cadence has wrong keys; "
            f"missing={sorted(missing)}, extra={sorted(extra)}"
        )
    kind = body["kind"]
    if kind != "fixed_step":
        raise RuleValidationError("cadence.kind must be fixed_step")
    step_seconds = body["step_seconds"]
    if not isinstance(step_seconds, int) or step_seconds <= 0:
        raise RuleValidationError("cadence.step_seconds must be a positive int")
    return Cadence(kind=kind, step_seconds=step_seconds)


def _normalize_dag(
    body: Any,
    registry: Mapping[str, DagOp],
    *,
    section: str,
    expected_root_type: str,
) -> RuleDag:
    if not isinstance(body, Mapping):
        raise RuleValidationError(f"{section} must be a mapping")
    extra = set(body.keys()) - _DAG_KEYS
    missing = _DAG_KEYS - set(body.keys())
    if extra or missing:
        raise RuleValidationError(
            f"{section} has wrong keys; missing={sorted(missing)}, extra={sorted(extra)}"
        )
    raw_nodes = body["nodes"]
    if not isinstance(raw_nodes, list) or not raw_nodes:
        raise RuleValidationError(f"{section}.nodes must be a non-empty list")

    normalized_nodes: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw_nodes:
        if not isinstance(item, Mapping):
            raise RuleValidationError(f"{section} node must be a mapping")
        node_extra = set(item.keys()) - _NODE_KEYS
        node_missing = _NODE_KEYS - set(item.keys())
        if node_extra or node_missing:
            raise RuleValidationError(
                f"{section} node has wrong keys; "
                f"missing={sorted(node_missing)}, extra={sorted(node_extra)}"
            )
        node_id = item["id"]
        if not isinstance(node_id, str) or not node_id:
            raise RuleValidationError(f"{section} node id must be a non-empty string")
        if node_id in seen:
            raise RuleValidationError(f"{section} duplicate node id: {node_id}")
        seen.add(node_id)

        op_name = item["op"]
        if not isinstance(op_name, str) or not op_name:
            raise RuleValidationError(f"{section} node {node_id}: op must be a string")
        op = registry.get(op_name)
        if op is None:
            raise RuleValidationError(f"{section} node {node_id}: unknown op {op_name!r}")

        args = item["args"]
        if not isinstance(args, Mapping):
            raise RuleValidationError(f"{section} node {node_id}: args must be a mapping")
        normalized_args = dict(args)
        try:
            canonicalize(normalized_args)
        except (TypeError, ValueError) as exc:
            raise RuleValidationError(
                f"{section} node {node_id}: args must be canonical-JSON-serializable"
            ) from exc

        inputs = item["inputs"]
        if not isinstance(inputs, list) or any(not isinstance(inp, str) or not inp for inp in inputs):
            raise RuleValidationError(f"{section} node {node_id}: inputs must be string ids")
        try:
            op.validate(node_id=node_id, args=normalized_args, input_count=len(inputs))
        except ValueError as exc:
            raise RuleValidationError(str(exc)) from exc
        normalized_nodes.append(
            {
                "id": node_id,
                "op": op_name,
                "args": normalized_args,
                "inputs": list(inputs),
            }
        )

    node_ids = {node["id"] for node in normalized_nodes}
    for node in normalized_nodes:
        for input_id in node["inputs"]:
            if input_id not in node_ids:
                raise RuleValidationError(
                    f"{section} node {node['id']}: unknown input node id {input_id!r}"
                )
    output = body["output"]
    if not isinstance(output, str) or output not in node_ids:
        raise RuleValidationError(f"{section}.output must name an existing node id")

    normalized_nodes.sort(key=lambda node: node["id"])
    topological_order = _topological_order(normalized_nodes, section=section)
    execution_order = _execution_order(
        output=output,
        nodes={node["id"]: node for node in normalized_nodes},
        topological_order=topological_order,
    )
    result_types = _infer_types(
        nodes={node["id"]: node for node in normalized_nodes},
        topological_order=topological_order,
        registry=registry,
        section=section,
    )
    if result_types[output] != expected_root_type:
        raise RuleValidationError(f"{section} root must be bool-typed")
    resolved_nodes = tuple(
        RuleNode(
            id=node["id"],
            op=node["op"],
            op_version=registry[node["op"]].op_version,
            args=dict(node["args"]),
            inputs=tuple(node["inputs"]),
            result_type=result_types[node["id"]],
        )
        for node in normalized_nodes
    )
    return RuleDag(
        nodes=resolved_nodes,
        output=output,
        topological_order=topological_order,
        execution_order=execution_order,
    )


def _topological_order(nodes: list[dict[str, Any]], *, section: str) -> tuple[str, ...]:
    indegree = {node["id"]: 0 for node in nodes}
    children = {node["id"]: [] for node in nodes}
    for node in nodes:
        for input_id in node["inputs"]:
            indegree[node["id"]] += 1
            children[input_id].append(node["id"])

    ready = deque(sorted(node_id for node_id, degree in indegree.items() if degree == 0))
    ordered: list[str] = []
    while ready:
        node_id = ready.popleft()
        ordered.append(node_id)
        for child in sorted(children[node_id]):
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)
    if len(ordered) != len(nodes):
        raise RuleValidationError(f"{section} graph must be acyclic")
    return tuple(ordered)


def _execution_order(
    *,
    output: str,
    nodes: Mapping[str, dict[str, Any]],
    topological_order: tuple[str, ...],
) -> tuple[str, ...]:
    required: set[str] = set()

    def visit(node_id: str) -> None:
        if node_id in required:
            return
        required.add(node_id)
        for input_id in nodes[node_id]["inputs"]:
            visit(input_id)

    visit(output)
    return tuple(node_id for node_id in topological_order if node_id in required)


def _infer_types(
    *,
    nodes: Mapping[str, dict[str, Any]],
    topological_order: tuple[str, ...],
    registry: Mapping[str, DagOp],
    section: str,
) -> dict[str, str]:
    result_types: dict[str, str] = {}
    for node_id in topological_order:
        node = nodes[node_id]
        op = registry[node["op"]]
        input_types = [result_types[input_id] for input_id in node["inputs"]]
        try:
            result_types[node_id] = op.result_type(args=node["args"], input_types=input_types)
        except ValueError as exc:
            raise RuleValidationError(f"{section} node {node_id}: {exc}") from exc
    return result_types


def _compute_rule_id(normalized: dict[str, Any], context: RuleDag, exit_dag: RuleDag) -> str:
    hash_body = dict(normalized)
    hash_body["context"] = _hash_dag_body(normalized["context"], context)
    hash_body["exit"] = _hash_dag_body(normalized["exit"], exit_dag)
    return hashlib.sha256(canonicalize(hash_body)).hexdigest()


def _hash_dag_body(public_body: dict[str, Any], dag: RuleDag) -> dict[str, Any]:
    op_versions = {node.id: node.op_version for node in dag.nodes}
    hash_nodes = []
    for node in public_body["nodes"]:
        hash_nodes.append(
            {
                "id": node["id"],
                "op": node["op"],
                "op_version": op_versions[node["id"]],
                "args": node["args"],
                "inputs": node["inputs"],
            }
        )
    return {
        "nodes": hash_nodes,
        "output": public_body["output"],
    }


def _ensure_aware_datetime(raw: datetime, field: str) -> None:
    if not isinstance(raw, datetime):
        raise TypeError(f"{field} must be a datetime")
    if raw.tzinfo is None:
        raise ValueError(f"{field} must be timezone-aware")
