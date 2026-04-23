from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Mapping

import numpy as np

from access import utc_now
from pipeline import CostCeiling, InvariantViolation, Stage, StageContext

from .llm_client import LLMClient
from .ops import DEFAULT_OPS, PrimitiveOp
from .pricing import realized_usd
from .registry import SpecRegistry
from .spec import Spec, SpecValidationError


COMPUTE_COST_PER_NODE_USD = 0.000001


class DependencyEnvelopeError(RuntimeError):
    """Raised when a spec reads outside its declared dependency envelope."""


@dataclass(frozen=True)
class RepresentCostUsed:
    compute_usd: float
    llm_usd: float
    data_reads: int
    storage_bytes: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "compute_usd": self.compute_usd,
            "llm_usd": self.llm_usd,
            "data_reads": self.data_reads,
            "storage_bytes": self.storage_bytes,
        }


@dataclass(frozen=True)
class RepresentInput:
    spec_version: str
    query_time: str


@dataclass
class RepresentOutput:
    tensor: np.ndarray
    spec_version: str
    input_hashes: tuple[str, ...]
    cost_used: RepresentCostUsed


@dataclass(frozen=True)
class LLMCallTrace:
    model: str
    prompt_hash: str
    params_hash: str
    bytes_hash: str
    declared_cost_usd: float
    cost_tolerance: float
    input_tokens: int
    output_tokens: int


@dataclass
class _ExecutionContext:
    stage_ctx: StageContext
    query_time: datetime
    allowed_hashes: frozenset[str]
    read_hashes: set[str]
    llm_client: LLMClient | None
    fetch_time_provider: Callable[[], datetime]
    llm_calls: dict[str, LLMCallTrace]
    current_node_id: str | None = None

    @property
    def access(self) -> Any:
        return self.stage_ctx.access

    def read_raw(self, hash_value: str) -> bytes:
        if hash_value not in self.allowed_hashes:
            raise DependencyEnvelopeError(
                f"raw_get hash {hash_value} is outside the declared deps envelope"
            )
        if self.stage_ctx.access is None:
            raise RuntimeError("RepresentStage requires an AccessLayer")
        self.stage_ctx.charge_data_read(1)
        payload = self.stage_ctx.access.get(hash_value, query_time=self.query_time)
        self.read_hashes.add(hash_value)
        return payload

    def set_current_node(self, node_id: str) -> None:
        self.current_node_id = node_id

    def lookup_llm(self, model_id: str, prompt_hash: str, params_hash: str) -> str | None:
        if self.stage_ctx.access is None:
            raise RuntimeError("RepresentStage requires an AccessLayer")
        self.stage_ctx.charge_data_read(1)
        return self.stage_ctx.access.lookup_llm(
            model_id,
            prompt_hash,
            params_hash,
            self.query_time,
        )

    def read_llm_response(
        self,
        bytes_hash: str,
        *,
        model_id: str,
        prompt_hash: str,
        params_hash: str,
    ) -> dict[str, Any]:
        if self.stage_ctx.access is None:
            raise RuntimeError("RepresentStage requires an AccessLayer")
        self.stage_ctx.charge_data_read(1)
        payload = self.stage_ctx.access.get(bytes_hash, query_time=self.query_time)
        self.read_hashes.add(bytes_hash)
        envelope = json.loads(payload.decode("utf-8"))
        if envelope.get("model") != model_id:
            raise ValueError("cached llm response model mismatch")
        if envelope.get("prompt_hash") != prompt_hash:
            raise ValueError("cached llm response prompt_hash mismatch")
        if envelope.get("params_hash") != params_hash:
            raise ValueError("cached llm response params_hash mismatch")
        response = envelope.get("response")
        if not isinstance(response, dict):
            raise ValueError("cached llm response must contain a response object")
        return response

    def complete_llm(self, *, model: str, prompt: str, params: dict[str, Any]) -> Any:
        if self.llm_client is None:
            raise RuntimeError("RepresentStage requires an llm_client for llm_call cache misses")
        return self.llm_client.complete(model=model, prompt=prompt, params=params)

    def write_llm_response(
        self,
        *,
        body: bytes,
        model_id: str,
        prompt_hash: str,
        params_hash: str,
    ) -> str:
        if self.stage_ctx.writer is None:
            raise RuntimeError("RepresentStage requires a writer for llm_call nodes")
        bytes_hash = self.stage_ctx.writer.put_llm_response(
            body=body,
            model_id=model_id,
            prompt_hash=prompt_hash,
            params_hash=params_hash,
            fetch_time=self.fetch_time_provider(),
        )
        self.stage_ctx.charge_data_read(1)
        self.read_hashes.add(bytes_hash)
        return bytes_hash

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
        if self.current_node_id is None:
            raise RuntimeError("llm_call ran without a current node id")
        self.llm_calls[self.current_node_id] = LLMCallTrace(
            model=model,
            prompt_hash=prompt_hash,
            params_hash=params_hash,
            bytes_hash=bytes_hash,
            declared_cost_usd=declared_cost_usd,
            cost_tolerance=cost_tolerance,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )


class RepresentStage(Stage):
    name = "represent_runner"
    version = "1"
    audit_stage = "Represent"
    cost_ceiling = CostCeiling(compute_usd=1.0, llm_usd=1.0, data_reads=1024)
    InputType = RepresentInput
    OutputType = RepresentOutput

    def __init__(
        self,
        *,
        registry: SpecRegistry,
        artifacts,
        audit,
        access,
        writer=None,
        llm_client: LLMClient | None = None,
        fetch_time_provider: Callable[[], datetime] = utc_now,
        op_registry: Mapping[str, PrimitiveOp] | None = None,
    ) -> None:
        if not isinstance(registry, SpecRegistry):
            raise TypeError("registry must be a SpecRegistry")
        super().__init__(artifacts=artifacts, audit=audit, access=access, writer=writer)
        self._registry = registry
        self._ops = dict(op_registry or DEFAULT_OPS)
        self._llm_client = llm_client
        self._fetch_time_provider = fetch_time_provider

    def compute(self, inputs: RepresentInput, ctx: StageContext) -> RepresentOutput:
        spec = self._registry.get(inputs.spec_version)
        self._validate_declared_deps(spec)
        if _has_llm_call(spec):
            if ctx.writer is None:
                raise RuntimeError("RepresentStage requires a writer for llm_call nodes")
            if ctx.access is None:
                raise RuntimeError("RepresentStage requires an AccessLayer")
        query_time = _parse_query_time(inputs.query_time)
        exec_ctx = _ExecutionContext(
            stage_ctx=ctx,
            query_time=query_time,
            allowed_hashes=frozenset(spec.deps),
            read_hashes=set(),
            llm_client=self._llm_client,
            fetch_time_provider=self._fetch_time_provider,
            llm_calls={},
        )

        node_values: dict[str, Any] = {}
        for node_id in spec.execution_order:
            node = spec.nodes_by_id[node_id]
            op = self._ops.get(node.op)
            if op is None:
                raise SpecValidationError(f"spec {spec.spec_id}: unknown op {node.op!r}")
            if op.op_version != node.op_version:
                raise SpecValidationError(
                    f"spec {spec.spec_id}: op {node.op!r} version drift "
                    f"({node.op_version} != {op.op_version})"
                )
            ctx.charge_compute(COMPUTE_COST_PER_NODE_USD)
            input_values = [node_values[input_id] for input_id in node.inputs]
            exec_ctx.set_current_node(node_id)
            node_values[node_id] = op.run(node.args, input_values, exec_ctx)
            if node.op == "llm_call":
                self._handle_llm_cost(
                    spec=spec,
                    node_id=node_id,
                    trace=exec_ctx.llm_calls[node_id],
                    ctx=ctx,
                )

        tensor = _as_output_tensor(node_values[spec.output])
        cost_used = RepresentCostUsed(
            compute_usd=ctx.usage.compute_usd,
            llm_usd=ctx.usage.llm_usd,
            data_reads=ctx.usage.data_reads,
            storage_bytes=tensor.nbytes,
        )
        return RepresentOutput(
            tensor=tensor,
            spec_version=spec.spec_id,
            input_hashes=tuple(sorted(exec_ctx.read_hashes)),
            cost_used=cost_used,
        )

    def invariant(self, inputs: RepresentInput, outputs: RepresentOutput) -> None:
        spec = self._registry.get(inputs.spec_version)
        if outputs.spec_version != spec.spec_id:
            raise InvariantViolation("output spec_version does not match the registered spec")
        self._validate_declared_deps(spec)
        expected_dtype = np.dtype(spec.output_schema.dtype)
        actual_dtype = np.dtype(outputs.tensor.dtype)
        if actual_dtype != expected_dtype:
            raise InvariantViolation(
                f"output dtype mismatch: expected {expected_dtype.name}, got {actual_dtype.name}"
            )
        _assert_shape_matches(
            expected_shape=spec.output_schema.shape,
            actual_shape=outputs.tensor.shape,
        )
        if outputs.cost_used.storage_bytes != outputs.tensor.nbytes:
            raise InvariantViolation("reported storage_bytes does not match tensor bytes")

    def audit_extra_payload(
        self,
        inputs: RepresentInput,
        outputs: RepresentOutput,
        ctx: StageContext,
        *,
        inputs_hash: str,
        output_hash: str,
    ) -> dict[str, Any]:
        spec = self._registry.get(inputs.spec_version)
        return {
            "spec_version": outputs.spec_version,
            "declared_cost": spec.cost.as_dict(),
            "cost_used": outputs.cost_used.as_dict(),
            "hashes_read": list(outputs.input_hashes),
            "output_dtype": np.dtype(outputs.tensor.dtype).name,
            "output_shape": list(outputs.tensor.shape),
        }

    def _serialize_output(self, outputs: RepresentOutput) -> bytes:
        header = {
            "spec_version": outputs.spec_version,
            "input_hashes": list(outputs.input_hashes),
            "cost_used": outputs.cost_used.as_dict(),
            "dtype": np.dtype(outputs.tensor.dtype).str,
            "shape": list(outputs.tensor.shape),
        }
        header_bytes = json.dumps(
            header,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        return len(header_bytes).to_bytes(8, byteorder="big") + header_bytes + outputs.tensor.tobytes(
            order="C"
        )

    def _deserialize_output(self, data: bytes) -> RepresentOutput:
        header_size = int.from_bytes(data[:8], byteorder="big")
        header = json.loads(data[8 : 8 + header_size].decode("utf-8"))
        tensor_bytes = data[8 + header_size :]
        array = np.frombuffer(tensor_bytes, dtype=np.dtype(header["dtype"])).copy()
        array = np.array(array.reshape(tuple(header["shape"])), copy=True, order="C")
        cost = header["cost_used"]
        return RepresentOutput(
            tensor=array,
            spec_version=header["spec_version"],
            input_hashes=tuple(header["input_hashes"]),
            cost_used=RepresentCostUsed(
                compute_usd=float(cost["compute_usd"]),
                llm_usd=float(cost["llm_usd"]),
                data_reads=int(cost["data_reads"]),
                storage_bytes=int(cost["storage_bytes"]),
            ),
        )

    @staticmethod
    def _validate_declared_deps(spec: Spec) -> None:
        deps = set(spec.deps)
        for node in spec.nodes:
            if node.op != "raw_get":
                continue
            hash_value = node.args["hash"]
            if hash_value not in deps:
                raise DependencyEnvelopeError(
                    f"spec {spec.spec_id}: raw_get hash {hash_value} is outside deps"
                )

    def _handle_llm_cost(
        self,
        *,
        spec: Spec,
        node_id: str,
        trace: LLMCallTrace,
        ctx: StageContext,
    ) -> None:
        realized = realized_usd(
            model=trace.model,
            input_tokens=trace.input_tokens,
            output_tokens=trace.output_tokens,
        )
        ctx.charge_llm(realized)
        drift_ratio = realized / trace.declared_cost_usd
        if drift_ratio <= 1.0 + trace.cost_tolerance:
            return
        self._audit.append(
            {
                "category": "CostDrift",
                "stage": "Represent",
                "envelope": dict(ctx.envelope),
                "spec_version": spec.spec_id,
                "node_id": node_id,
                "model": trace.model,
                "declared_usd": trace.declared_cost_usd,
                "realized_usd": realized,
                "drift_ratio": drift_ratio,
                "prompt_hash": trace.prompt_hash,
                "params_hash": trace.params_hash,
            }
        )


def _parse_query_time(value: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise TypeError("query_time must be a non-empty ISO-8601 string")
    query_time = datetime.fromisoformat(value)
    if query_time.tzinfo is None:
        raise ValueError("query_time must be timezone-aware")
    return query_time


def _has_llm_call(spec: Spec) -> bool:
    return any(node.op == "llm_call" for node in spec.nodes)


def _as_output_tensor(value: Any) -> np.ndarray:
    return np.array(value, copy=True, order="C")


def _assert_shape_matches(
    *,
    expected_shape: tuple[int | str, ...],
    actual_shape: tuple[int, ...],
) -> None:
    if len(expected_shape) != len(actual_shape):
        raise InvariantViolation(
            f"output rank mismatch: expected {len(expected_shape)}, got {len(actual_shape)}"
        )
    symbols: dict[str, int] = {}
    for expected, actual in zip(expected_shape, actual_shape, strict=True):
        if isinstance(expected, int):
            if actual != expected:
                raise InvariantViolation(
                    f"output shape mismatch: expected dimension {expected}, got {actual}"
                )
            continue
        prior = symbols.setdefault(expected, actual)
        if prior != actual:
            raise InvariantViolation(
                f"symbolic output dimension {expected!r} expected {prior}, got {actual}"
            )
