from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any, Mapping

from .stats import GroundingStats, decode_number, encode_atom, hash_payload


_OPS = frozenset(
    {
        "stat",
        "literal",
        "lt",
        "le",
        "gt",
        "ge",
        "eq",
        "ne",
        "and",
        "or",
        "not",
        "add",
        "sub",
        "mul",
        "div",
        "abs",
    }
)


@dataclass(frozen=True)
class MatcherNode:
    id: str
    op: str
    args: dict[str, Any]
    inputs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id:
            raise ValueError("node id must be a non-empty string")
        if self.op not in _OPS:
            raise ValueError(f"unknown op {self.op!r}")
        object.__setattr__(self, "args", dict(self.args))
        object.__setattr__(self, "inputs", tuple(self.inputs))

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "op": self.op,
            "args": encode_atom(self.args),
            "inputs": list(self.inputs),
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "MatcherNode":
        return cls(
            id=str(raw["id"]),
            op=str(raw["op"]),
            args=_decode_args(raw.get("args", {})),
            inputs=tuple(raw.get("inputs", ())),
        )


@dataclass(frozen=True)
class MatcherDag:
    nodes: tuple[MatcherNode, ...]
    output: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "nodes", tuple(self.nodes))
        if not self.nodes:
            raise ValueError("nodes must not be empty")
        ids = [node.id for node in self.nodes]
        if len(ids) != len(set(ids)):
            raise ValueError("node ids must be unique")
        if self.output not in set(ids):
            raise ValueError("output must name a node")
        _topological_order(self.nodes)

    def as_dict(self) -> dict[str, Any]:
        return {
            "nodes": [node.as_dict() for node in sorted(self.nodes, key=lambda node: node.id)],
            "output": self.output,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "MatcherDag":
        return cls(
            nodes=tuple(MatcherNode.from_dict(item) for item in raw["nodes"]),
            output=str(raw["output"]),
        )


@dataclass(frozen=True)
class MatcherTraceStep:
    node_id: str
    op: str
    out: Any
    inputs: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "op": self.op,
            "out": encode_atom(self.out),
            "inputs": list(self.inputs),
        }


@dataclass(frozen=True)
class MatcherTrace:
    result: bool
    steps: tuple[MatcherTraceStep, ...]
    trace_hash: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "result": self.result,
            "steps": [step.as_dict() for step in self.steps],
            "trace_hash": self.trace_hash,
        }


def evaluate_matcher(dag: MatcherDag, stats: GroundingStats) -> tuple[bool, MatcherTrace]:
    node_by_id = {node.id: node for node in dag.nodes}
    outs: dict[str, Any] = {}
    steps: list[MatcherTraceStep] = []
    for node_id in _required_order(dag):
        node = node_by_id[node_id]
        args = node.args
        ins = [outs[input_id] for input_id in node.inputs]
        out = _run_op(node.op, args, ins, stats)
        outs[node_id] = out
        steps.append(
            MatcherTraceStep(
                node_id=node.id,
                op=node.op,
                out=out,
                inputs=node.inputs,
            )
        )
    result = bool(outs[dag.output])
    trace_steps = tuple(steps)
    trace_hash = hash_payload(
        {
            "result": result,
            "steps": [step.as_dict() for step in trace_steps],
        }
    )
    return result, MatcherTrace(result=result, steps=trace_steps, trace_hash=trace_hash)


def stat(name: str, node_id: str = "stat") -> MatcherNode:
    return MatcherNode(id=node_id, op="stat", args={"name": name}, inputs=())


def literal(item: Any, node_id: str = "literal") -> MatcherNode:
    return MatcherNode(id=node_id, op="literal", args={"item": item}, inputs=())


def unary(node_id: str, op: str, child: str) -> MatcherNode:
    return MatcherNode(id=node_id, op=op, args={}, inputs=(child,))


def binary(node_id: str, op: str, left: str, right: str) -> MatcherNode:
    return MatcherNode(id=node_id, op=op, args={}, inputs=(left, right))


def _run_op(op: str, args: Mapping[str, Any], ins: list[Any], stats: GroundingStats) -> Any:
    if op == "stat":
        _arity(ins, 0, op)
        return stats.stat(str(args["name"]))
    if op == "literal":
        _arity(ins, 0, op)
        return args["item"]
    if op == "not":
        _arity(ins, 1, op)
        return not bool(ins[0])
    if op == "and":
        _arity(ins, 2, op)
        return bool(ins[0]) and bool(ins[1])
    if op == "or":
        _arity(ins, 2, op)
        return bool(ins[0]) or bool(ins[1])
    if op in {"lt", "le", "gt", "ge"}:
        _arity(ins, 2, op)
        left = decode_number(ins[0])
        right = decode_number(ins[1])
        return {
            "lt": left < right,
            "le": left <= right,
            "gt": left > right,
            "ge": left >= right,
        }[op]
    if op == "eq":
        _arity(ins, 2, op)
        return ins[0] == ins[1]
    if op == "ne":
        _arity(ins, 2, op)
        return ins[0] != ins[1]
    if op in {"add", "sub", "mul", "div"}:
        _arity(ins, 2, op)
        left = decode_number(ins[0])
        right = decode_number(ins[1])
        if op == "add":
            return left + right
        if op == "sub":
            return left - right
        if op == "mul":
            return left * right
        if right == 0:
            raise ZeroDivisionError("division by zero")
        return left / right
    if op == "abs":
        _arity(ins, 1, op)
        return abs(decode_number(ins[0]))
    raise AssertionError("unreachable op")


def _arity(ins: list[Any], n: int, op: str) -> None:
    if len(ins) != n:
        raise ValueError(f"{op} requires {n} inputs")


def _topological_order(nodes: tuple[MatcherNode, ...]) -> tuple[str, ...]:
    node_by_id = {node.id: node for node in nodes}
    indegree = {node.id: 0 for node in nodes}
    children = {node.id: [] for node in nodes}
    for node in nodes:
        for input_id in node.inputs:
            if input_id not in node_by_id:
                raise ValueError(f"unknown input node {input_id!r}")
            indegree[node.id] += 1
            children[input_id].append(node.id)
    ready = deque(sorted(node_id for node_id, n in indegree.items() if n == 0))
    ordered: list[str] = []
    while ready:
        node_id = ready.popleft()
        ordered.append(node_id)
        for child_id in sorted(children[node_id]):
            indegree[child_id] -= 1
            if indegree[child_id] == 0:
                ready.append(child_id)
    if len(ordered) != len(nodes):
        raise ValueError("matcher graph must be acyclic")
    return tuple(ordered)


def _required_order(dag: MatcherDag) -> tuple[str, ...]:
    node_by_id = {node.id: node for node in dag.nodes}
    needed: set[str] = set()

    def visit(node_id: str) -> None:
        if node_id in needed:
            return
        needed.add(node_id)
        for input_id in node_by_id[node_id].inputs:
            visit(input_id)

    visit(dag.output)
    return tuple(node_id for node_id in _topological_order(dag.nodes) if node_id in needed)


def _decode_args(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise TypeError("args must be a mapping")
    return {str(key): _decode_atom(raw_item) for key, raw_item in raw.items()}


def _decode_atom(raw: Any) -> Any:
    if isinstance(raw, list):
        return [_decode_atom(item) for item in raw]
    if isinstance(raw, Mapping):
        kind = raw.get("kind")
        if kind == "none":
            return None
        if kind == "bool":
            return bool(raw["item"])
        if kind == "int":
            return int(raw["item"])
        if kind == "float":
            return float(raw["text"])
        if kind == "str":
            return str(raw["text"])
        return {str(key): _decode_atom(raw_item) for key, raw_item in raw.items()}
    return raw
