from __future__ import annotations

import hashlib
from collections import deque
from dataclasses import dataclass
from typing import Any, Mapping

from audit import canonicalize

from .ops import DEFAULT_OPS, PrimitiveOp


class SpecValidationError(ValueError):
    """Raised when a feature-family spec fails validation."""


_SPEC_KEYS = frozenset(
    {
        "schema_version",
        "name",
        "graph",
        "deps",
        "cost",
        "output_schema",
    }
)
_GRAPH_KEYS = frozenset({"nodes", "output"})
_NODE_KEYS = frozenset({"id", "op", "args", "inputs"})
_COST_KEYS = frozenset({"compute_usd", "llm_usd", "storage_bytes"})
_OUTPUT_SCHEMA_KEYS = frozenset({"dtype", "shape"})


@dataclass(frozen=True)
class SpecCost:
    compute_usd: float
    llm_usd: float
    storage_bytes: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "compute_usd": self.compute_usd,
            "llm_usd": self.llm_usd,
            "storage_bytes": self.storage_bytes,
        }


@dataclass(frozen=True)
class SpecOutputSchema:
    dtype: str
    shape: tuple[int | str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "dtype": self.dtype,
            "shape": list(self.shape),
        }


@dataclass(frozen=True)
class SpecNode:
    id: str
    op: str
    op_version: str
    args: dict[str, Any]
    inputs: tuple[str, ...]

    def public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "op": self.op,
            "args": self.args,
            "inputs": list(self.inputs),
        }


@dataclass(frozen=True)
class Spec:
    spec_id: str
    schema_version: int
    name: str
    nodes: tuple[SpecNode, ...]
    output: str
    deps: tuple[str, ...]
    cost: SpecCost
    output_schema: SpecOutputSchema
    topological_order: tuple[str, ...]
    execution_order: tuple[str, ...]

    @property
    def nodes_by_id(self) -> dict[str, SpecNode]:
        return {node.id: node for node in self.nodes}

    def public_body(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "name": self.name,
            "graph": {
                "nodes": [node.public_dict() for node in self.nodes],
                "output": self.output,
            },
            "deps": list(self.deps),
            "cost": self.cost.as_dict(),
            "output_schema": self.output_schema.as_dict(),
        }

    def public_dict(self) -> dict[str, Any]:
        data = self.public_body()
        data["spec_id"] = self.spec_id
        return data


def finalize_spec(
    body: Mapping[str, Any],
    *,
    op_registry: Mapping[str, PrimitiveOp] | None = None,
) -> dict[str, Any]:
    registry = dict(op_registry or DEFAULT_OPS)
    normalized, resolved_nodes, _, _ = _normalize_and_resolve(body, registry)
    spec_id = _compute_spec_id(normalized, resolved_nodes)
    finalized = dict(normalized)
    finalized["spec_id"] = spec_id
    return finalized


def load_spec(
    document: Mapping[str, Any] | Spec,
    *,
    op_registry: Mapping[str, PrimitiveOp] | None = None,
) -> Spec:
    if isinstance(document, Spec):
        return document

    if not isinstance(document, Mapping):
        raise SpecValidationError("spec must be a mapping")

    registry = dict(op_registry or DEFAULT_OPS)
    doc = dict(document)
    spec_id = doc.pop("spec_id", None)
    if not isinstance(spec_id, str) or len(spec_id) != 64:
        raise SpecValidationError("spec_id must be a 64-character hex string")

    normalized, resolved_nodes, topological_order, execution_order = _normalize_and_resolve(
        doc,
        registry,
    )
    expected = _compute_spec_id(normalized, resolved_nodes)
    if spec_id != expected:
        raise SpecValidationError("spec_id does not match the canonical spec body")

    return Spec(
        spec_id=spec_id,
        schema_version=normalized["schema_version"],
        name=normalized["name"],
        nodes=tuple(resolved_nodes),
        output=normalized["graph"]["output"],
        deps=tuple(normalized["deps"]),
        cost=SpecCost(**normalized["cost"]),
        output_schema=SpecOutputSchema(
            dtype=normalized["output_schema"]["dtype"],
            shape=tuple(normalized["output_schema"]["shape"]),
        ),
        topological_order=topological_order,
        execution_order=execution_order,
    )


def _normalize_and_resolve(
    body: Mapping[str, Any],
    op_registry: Mapping[str, PrimitiveOp],
) -> tuple[dict[str, Any], list[SpecNode], tuple[str, ...], tuple[str, ...]]:
    if not isinstance(body, Mapping):
        raise SpecValidationError("spec body must be a mapping")
    unknown = set(body.keys()) - _SPEC_KEYS
    missing = _SPEC_KEYS - set(body.keys())
    if unknown or missing:
        raise SpecValidationError(
            "spec body must contain exactly "
            f"{sorted(_SPEC_KEYS)}; missing={sorted(missing)}, extra={sorted(unknown)}"
        )

    schema_version = body["schema_version"]
    if not isinstance(schema_version, int) or schema_version != 1:
        raise SpecValidationError("schema_version must be integer 1")

    name = body["name"]
    if not isinstance(name, str) or not name:
        raise SpecValidationError("name must be a non-empty string")

    graph = body["graph"]
    if not isinstance(graph, Mapping):
        raise SpecValidationError("graph must be a mapping")
    graph_unknown = set(graph.keys()) - _GRAPH_KEYS
    graph_missing = _GRAPH_KEYS - set(graph.keys())
    if graph_unknown or graph_missing:
        raise SpecValidationError(
            "graph must contain exactly ['nodes', 'output']; "
            f"missing={sorted(graph_missing)}, extra={sorted(graph_unknown)}"
        )

    raw_nodes = graph["nodes"]
    if not isinstance(raw_nodes, list) or not raw_nodes:
        raise SpecValidationError("graph.nodes must be a non-empty list")

    normalized_nodes: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for item in raw_nodes:
        if not isinstance(item, Mapping):
            raise SpecValidationError("every graph node must be a mapping")
        node_unknown = set(item.keys()) - _NODE_KEYS
        node_missing = _NODE_KEYS - set(item.keys())
        if node_unknown or node_missing:
            raise SpecValidationError(
                "each graph node must contain exactly "
                "['args', 'id', 'inputs', 'op']; "
                f"missing={sorted(node_missing)}, extra={sorted(node_unknown)}"
            )
        node_id = item["id"]
        if not isinstance(node_id, str) or not node_id:
            raise SpecValidationError("node id must be a non-empty string")
        if node_id in seen_ids:
            raise SpecValidationError(f"duplicate node id: {node_id}")
        seen_ids.add(node_id)

        op_name = item["op"]
        if not isinstance(op_name, str) or not op_name:
            raise SpecValidationError(f"node {node_id}: op must be a non-empty string")
        op = op_registry.get(op_name)
        if op is None:
            raise SpecValidationError(f"node {node_id}: unknown op {op_name!r}")

        args = item["args"]
        if not isinstance(args, Mapping):
            raise SpecValidationError(f"node {node_id}: args must be a mapping")
        normalized_args = dict(args)
        try:
            canonicalize(normalized_args)
        except (TypeError, ValueError) as exc:
            raise SpecValidationError(
                f"node {node_id}: args must be canonical-JSON-serializable"
            ) from exc

        inputs = item["inputs"]
        if not isinstance(inputs, list):
            raise SpecValidationError(f"node {node_id}: inputs must be a list")
        if any(not isinstance(inp, str) or not inp for inp in inputs):
            raise SpecValidationError(
                f"node {node_id}: every input id must be a non-empty string"
            )

        op.validate(node_id=node_id, args=normalized_args, input_count=len(inputs))
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
                raise SpecValidationError(
                    f"node {node['id']}: unknown input node id {input_id!r}"
                )

    output = graph["output"]
    if not isinstance(output, str) or output not in node_ids:
        raise SpecValidationError("graph.output must name an existing node id")

    deps = body["deps"]
    if not isinstance(deps, list):
        raise SpecValidationError("deps must be a list")
    dep_set: set[str] = set()
    normalized_deps: list[str] = []
    for dep in deps:
        if not isinstance(dep, str) or len(dep) != 64:
            raise SpecValidationError("deps entries must be 64-character hash strings")
        if dep in dep_set:
            continue
        dep_set.add(dep)
        normalized_deps.append(dep)
    normalized_deps.sort()

    cost = body["cost"]
    if not isinstance(cost, Mapping):
        raise SpecValidationError("cost must be a mapping")
    cost_unknown = set(cost.keys()) - _COST_KEYS
    cost_missing = _COST_KEYS - set(cost.keys())
    if cost_unknown or cost_missing:
        raise SpecValidationError(
            "cost must contain exactly "
            f"{sorted(_COST_KEYS)}; missing={sorted(cost_missing)}, extra={sorted(cost_unknown)}"
        )
    compute_usd = _non_negative_float(cost["compute_usd"], "cost.compute_usd")
    llm_usd = _non_negative_float(cost["llm_usd"], "cost.llm_usd")
    storage_bytes = cost["storage_bytes"]
    if not isinstance(storage_bytes, int) or storage_bytes < 0:
        raise SpecValidationError("cost.storage_bytes must be a non-negative int")

    output_schema = body["output_schema"]
    if not isinstance(output_schema, Mapping):
        raise SpecValidationError("output_schema must be a mapping")
    schema_unknown = set(output_schema.keys()) - _OUTPUT_SCHEMA_KEYS
    schema_missing = _OUTPUT_SCHEMA_KEYS - set(output_schema.keys())
    if schema_unknown or schema_missing:
        raise SpecValidationError(
            "output_schema must contain exactly "
            f"{sorted(_OUTPUT_SCHEMA_KEYS)}; missing={sorted(schema_missing)}, extra={sorted(schema_unknown)}"
        )
    dtype = output_schema["dtype"]
    if not isinstance(dtype, str) or not dtype:
        raise SpecValidationError("output_schema.dtype must be a non-empty string")
    shape = output_schema["shape"]
    if not isinstance(shape, list):
        raise SpecValidationError("output_schema.shape must be a list")
    normalized_shape: list[int | str] = []
    for dim in shape:
        if isinstance(dim, int):
            if dim < 0:
                raise SpecValidationError("output_schema integer dimensions must be >= 0")
            normalized_shape.append(dim)
            continue
        if isinstance(dim, str) and dim:
            normalized_shape.append(dim)
            continue
        raise SpecValidationError(
            "output_schema.shape entries must be non-negative ints or non-empty strings"
        )

    normalized_nodes.sort(key=lambda node: node["id"])
    topological_order = _topological_order(normalized_nodes)
    execution_order = _execution_order(
        output=output,
        nodes={node["id"]: node for node in normalized_nodes},
        topological_order=topological_order,
    )

    resolved_nodes = [
        SpecNode(
            id=node["id"],
            op=node["op"],
            op_version=op_registry[node["op"]].op_version,
            args=dict(node["args"]),
            inputs=tuple(node["inputs"]),
        )
        for node in normalized_nodes
    ]
    normalized = {
        "schema_version": schema_version,
        "name": name,
        "graph": {
            "nodes": normalized_nodes,
            "output": output,
        },
        "deps": normalized_deps,
        "cost": {
            "compute_usd": compute_usd,
            "llm_usd": llm_usd,
            "storage_bytes": storage_bytes,
        },
        "output_schema": {
            "dtype": dtype,
            "shape": normalized_shape,
        },
    }
    return normalized, resolved_nodes, topological_order, execution_order


def _non_negative_float(value: Any, label: str) -> float:
    if not isinstance(value, (int, float)):
        raise SpecValidationError(f"{label} must be numeric")
    result = float(value)
    if result < 0:
        raise SpecValidationError(f"{label} must be >= 0")
    return result


def _topological_order(nodes: list[dict[str, Any]]) -> tuple[str, ...]:
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
        raise SpecValidationError("graph must be acyclic")
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


def _compute_spec_id(normalized: dict[str, Any], resolved_nodes: list[SpecNode]) -> str:
    op_versions = {node.id: node.op_version for node in resolved_nodes}
    hash_nodes = []
    for node in normalized["graph"]["nodes"]:
        hash_nodes.append(
            {
                "id": node["id"],
                "op": node["op"],
                "op_version": op_versions[node["id"]],
                "args": node["args"],
                "inputs": node["inputs"],
            }
        )
    hash_body = {
        "schema_version": normalized["schema_version"],
        "name": normalized["name"],
        "graph": {
            "nodes": hash_nodes,
            "output": normalized["graph"]["output"],
        },
        "deps": normalized["deps"],
        "cost": normalized["cost"],
        "output_schema": normalized["output_schema"],
    }
    return hashlib.sha256(canonicalize(hash_body)).hexdigest()
