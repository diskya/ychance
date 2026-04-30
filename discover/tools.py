from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

import numpy as np

from access import AccessLayer
from audit import AuditLog, canonicalize
from pattern import (
    ObservationWindow,
    PatternValidationError,
    finalize_pattern,
    load_assertion,
    load_pattern,
    serialize_pattern,
)
from pipeline import ArtifactStore, StageContext
from represent import RepresentInput, RepresentStage, SpecRegistry

from . import audit as discover_audit
from .budget import CycleBudget


CHEAP_TOOLS = frozenset({"inspect_spec", "compute", "propose_spec", "test_assertion"})
FRONTIER_TOOLS = frozenset({"submit_pattern"})
ALLOWED_TOOLS = CHEAP_TOOLS | FRONTIER_TOOLS


class ToolCallError(RuntimeError):
    """Raised after the tool call has been audited."""

    def __init__(
        self,
        message: str,
        *,
        error_type: str,
        record: discover_audit.ToolCallRecord | None = None,
    ) -> None:
        self.error_type = error_type
        self.record = record
        super().__init__(message)


@dataclass(frozen=True)
class DiscoverWindow:
    t0: str
    t1: str

    def as_dict(self) -> dict[str, str]:
        return {"t0": self.t0, "t1": self.t1}

    def as_datetimes(self) -> tuple[datetime, datetime]:
        return datetime.fromisoformat(self.t0), datetime.fromisoformat(self.t1)


@dataclass(frozen=True)
class InspectSpecResult:
    spec_id: str
    name: str
    output_schema: dict[str, Any]
    declared_cost: dict[str, Any]
    sample_summary: dict[str, Any]
    cost_estimate_usd: float


@dataclass(frozen=True)
class ComputeResult:
    spec_id: str
    window: dict[str, str]
    output_artifact_hash: str
    lineage_hashes: tuple[str, ...]
    summary_stats: dict[str, Any]
    sample_values: tuple[Any, ...]
    cost_used: dict[str, Any]


@dataclass(frozen=True)
class ProposeSpecResult:
    spec_id: str
    registered: bool
    declared_cost: dict[str, Any]


@dataclass(frozen=True)
class AssertionFingerprint:
    fingerprint_hash: str
    spec_ref: str
    assertion_hash: str
    assertion: dict[str, Any]
    window: dict[str, str]
    result: bool
    summary_hash: str
    lineage_hashes: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TestAssertionResult:
    spec_ref: str
    assertion: dict[str, Any]
    window: dict[str, str]
    result: bool
    fingerprint_hash: str
    summary_hash: str
    lineage_hashes: tuple[str, ...]


@dataclass(frozen=True)
class SubmitPatternResult:
    pattern_id: str
    pattern_artifact_hash: str
    pattern_body_hash: str
    source_tool_call_ids: tuple[str, ...]
    fingerprint_hash: str
    observation_window: dict[str, str]
    reserved_windows: tuple[dict[str, str], ...]
    rationale_hash: str | None


@dataclass
class DiscoverToolState:
    cycle_id: str
    query_time: str
    successful_assertions: dict[str, AssertionFingerprint] = field(default_factory=dict)
    assertion_source_tools: dict[str, tuple[str, ...]] = field(default_factory=dict)
    touched_windows: set[DiscoverWindow] = field(default_factory=set)
    submitted_patterns: list[SubmitPatternResult] = field(default_factory=list)
    current_rationale_hash: str | None = None

    @property
    def tested_drafts(self) -> tuple[dict[str, Any], ...]:
        return tuple(fp.as_dict() for fp in self.successful_assertions.values())


@dataclass(frozen=True)
class ToolCallOutcome:
    result: Any
    record: discover_audit.ToolCallRecord


class DiscoverToolRouter:
    """Fixed tool surface for Discover."""

    def __init__(
        self,
        *,
        registry: SpecRegistry,
        artifacts: ArtifactStore,
        audit: AuditLog,
        access: AccessLayer | None,
        writer: Any = None,
        represent_llm_client: Any = None,
        inspect_cost_usd: float = 0.000001,
        propose_cost_usd: float = 0.00001,
        submit_cost_usd: float = 0.000005,
    ) -> None:
        if not isinstance(registry, SpecRegistry):
            raise TypeError("registry must be a SpecRegistry")
        if not isinstance(artifacts, ArtifactStore):
            raise TypeError("artifacts must be an ArtifactStore")
        if not isinstance(audit, AuditLog):
            raise TypeError("audit must be an AuditLog")
        if access is not None and not isinstance(access, AccessLayer):
            raise TypeError("access must be an AccessLayer or None")
        self._registry = registry
        self._artifacts = artifacts
        self._audit = audit
        self._access = access
        self._writer = writer
        self._represent_llm_client = represent_llm_client
        self._inspect_cost_usd = float(inspect_cost_usd)
        self._propose_cost_usd = float(propose_cost_usd)
        self._submit_cost_usd = float(submit_cost_usd)

    def call(
        self,
        *,
        tool_name: str,
        args: Mapping[str, Any],
        phase: str,
        step_index: int,
        envelope: dict[str, str],
        state: DiscoverToolState,
        budget: CycleBudget,
        ctx: StageContext,
    ) -> ToolCallOutcome:
        if not isinstance(args, Mapping):
            args = {}
        normalized_args = _canonical_copy(dict(args))
        args_hash = discover_audit.digest_jsonable(normalized_args)
        cost_before = budget.snapshot()
        tool_call_id = f"{state.cycle_id}:tool:{step_index}"

        if tool_name not in ALLOWED_TOOLS:
            return self._reject(
                tool_call_id=tool_call_id,
                step_index=step_index,
                phase=phase,
                tool_name=tool_name,
                args_hash=args_hash,
                envelope=envelope,
                cost_before=cost_before,
                budget=budget,
                error_type="UnknownTool",
                message=f"unknown Discover tool {tool_name!r}",
            )
        if phase == "cheap_iteration" and tool_name not in CHEAP_TOOLS:
            return self._reject(
                tool_call_id=tool_call_id,
                step_index=step_index,
                phase=phase,
                tool_name=tool_name,
                args_hash=args_hash,
                envelope=envelope,
                cost_before=cost_before,
                budget=budget,
                error_type="PhaseToolViolation",
                message=f"{tool_name} is not allowed in cheap_iteration",
            )
        if phase == "frontier_submission" and tool_name not in FRONTIER_TOOLS:
            return self._reject(
                tool_call_id=tool_call_id,
                step_index=step_index,
                phase=phase,
                tool_name=tool_name,
                args_hash=args_hash,
                envelope=envelope,
                cost_before=cost_before,
                budget=budget,
                error_type="PhaseToolViolation",
                message=f"{tool_name} is not allowed in frontier_submission",
            )

        estimate = self._estimate_tool_cost(tool_name, normalized_args)
        reservation = budget.reserve(kind="compute", action=f"tool:{tool_name}", usd=estimate)
        access_before = self._access.reads_used if self._access is not None else 0
        start_hash = discover_audit.append_tool_start(
            self._audit,
            envelope=envelope,
            tool_call_id=tool_call_id,
            step_index=step_index,
            phase=phase,
            tool_name=tool_name,
            args_hash=args_hash,
            cost_before=cost_before,
        )
        try:
            result, compute_usd, llm_usd, data_reads = self._dispatch(
                tool_name=tool_name,
                args=normalized_args,
                state=state,
                tool_call_id=tool_call_id,
            )
            budget.charge_usage(
                reservation,
                compute_usd=compute_usd,
                llm_usd=llm_usd,
                data_reads=data_reads,
            )
            if compute_usd:
                ctx.charge_compute(compute_usd)
            if llm_usd:
                ctx.charge_llm(llm_usd)
            if data_reads:
                ctx.charge_data_read(data_reads)
            outcome = "ok"
            error_type = None
            payload = _result_payload(result)
        except Exception as exc:
            budget.charge_usage(
                reservation,
                compute_usd=0.0,
                llm_usd=0.0,
                data_reads=0,
            )
            outcome = "error"
            error_type = type(exc).__name__
            payload = {"error": error_type, "message": str(exc)}
            result = payload

        result_hash = discover_audit.digest_jsonable(payload)
        access_after = self._access.reads_used if self._access is not None else 0
        cost_after = budget.snapshot()
        end_hash = discover_audit.append_tool_end(
            self._audit,
            envelope=envelope,
            tool_call_id=tool_call_id,
            step_index=step_index,
            phase=phase,
            tool_name=tool_name,
            args_hash=args_hash,
            result_hash=result_hash,
            outcome=outcome,
            error_type=error_type,
            cost_before=cost_before,
            cost_after=cost_after,
            access_read_count_delta=max(0, access_after - access_before),
            start_record_hash=start_hash,
        )
        record = discover_audit.ToolCallRecord(
            tool_call_id=tool_call_id,
            step_index=step_index,
            phase=phase,
            tool_name=tool_name,
            args_hash=args_hash,
            result_hash=result_hash,
            outcome=outcome,
            error_type=error_type,
            cost_before=cost_before,
            cost_after=cost_after,
            start_record_hash=start_hash,
            end_record_hash=end_hash,
        )
        if outcome != "ok":
            raise ToolCallError(
                str(payload),
                error_type=error_type or "ToolError",
                record=record,
            )
        return ToolCallOutcome(result=result, record=record)

    def inspect_spec(
        self,
        spec_id: str,
        *,
        phase: str,
        step_index: int,
        envelope: dict[str, str],
        state: DiscoverToolState,
        budget: CycleBudget,
        ctx: StageContext,
    ) -> ToolCallOutcome:
        return self.call(
            tool_name="inspect_spec",
            args={"spec_id": spec_id},
            phase=phase,
            step_index=step_index,
            envelope=envelope,
            state=state,
            budget=budget,
            ctx=ctx,
        )

    def compute(
        self,
        spec_id: str,
        window: Mapping[str, Any],
        *,
        phase: str,
        step_index: int,
        envelope: dict[str, str],
        state: DiscoverToolState,
        budget: CycleBudget,
        ctx: StageContext,
    ) -> ToolCallOutcome:
        return self.call(
            tool_name="compute",
            args={"spec_id": spec_id, "window": dict(window)},
            phase=phase,
            step_index=step_index,
            envelope=envelope,
            state=state,
            budget=budget,
            ctx=ctx,
        )

    def propose_spec(
        self,
        body: Mapping[str, Any],
        *,
        phase: str,
        step_index: int,
        envelope: dict[str, str],
        state: DiscoverToolState,
        budget: CycleBudget,
        ctx: StageContext,
    ) -> ToolCallOutcome:
        return self.call(
            tool_name="propose_spec",
            args={"body": dict(body)},
            phase=phase,
            step_index=step_index,
            envelope=envelope,
            state=state,
            budget=budget,
            ctx=ctx,
        )

    def test_assertion(
        self,
        spec_ref: str,
        assertion: Mapping[str, Any],
        window: Mapping[str, Any],
        *,
        phase: str,
        step_index: int,
        envelope: dict[str, str],
        state: DiscoverToolState,
        budget: CycleBudget,
        ctx: StageContext,
    ) -> ToolCallOutcome:
        return self.call(
            tool_name="test_assertion",
            args={
                "spec_ref": spec_ref,
                "assertion": dict(assertion),
                "window": dict(window),
            },
            phase=phase,
            step_index=step_index,
            envelope=envelope,
            state=state,
            budget=budget,
            ctx=ctx,
        )

    def submit_pattern(
        self,
        pattern_body: Mapping[str, Any],
        *,
        phase: str,
        step_index: int,
        envelope: dict[str, str],
        state: DiscoverToolState,
        budget: CycleBudget,
        ctx: StageContext,
    ) -> ToolCallOutcome:
        return self.call(
            tool_name="submit_pattern",
            args={"pattern_body": dict(pattern_body)},
            phase=phase,
            step_index=step_index,
            envelope=envelope,
            state=state,
            budget=budget,
            ctx=ctx,
        )

    def _reject(
        self,
        *,
        tool_call_id: str,
        step_index: int,
        phase: str,
        tool_name: str,
        args_hash: str,
        envelope: dict[str, str],
        cost_before: dict[str, Any],
        budget: CycleBudget,
        error_type: str,
        message: str,
    ) -> ToolCallOutcome:
        start_hash = discover_audit.append_tool_start(
            self._audit,
            envelope=envelope,
            tool_call_id=tool_call_id,
            step_index=step_index,
            phase=phase,
            tool_name=tool_name,
            args_hash=args_hash,
            cost_before=cost_before,
        )
        payload = {"error": error_type, "message": message}
        result_hash = discover_audit.digest_jsonable(payload)
        end_hash = discover_audit.append_tool_end(
            self._audit,
            envelope=envelope,
            tool_call_id=tool_call_id,
            step_index=step_index,
            phase=phase,
            tool_name=tool_name,
            args_hash=args_hash,
            result_hash=result_hash,
            outcome="rejected",
            error_type=error_type,
            cost_before=cost_before,
            cost_after=budget.snapshot(),
            access_read_count_delta=0,
            start_record_hash=start_hash,
        )
        record = discover_audit.ToolCallRecord(
            tool_call_id=tool_call_id,
            step_index=step_index,
            phase=phase,
            tool_name=tool_name,
            args_hash=args_hash,
            result_hash=result_hash,
            outcome="rejected",
            error_type=error_type,
            cost_before=cost_before,
            cost_after=budget.snapshot(),
            start_record_hash=start_hash,
            end_record_hash=end_hash,
        )
        raise ToolCallError(message, error_type=error_type, record=record)

    def _estimate_tool_cost(self, tool_name: str, args: Mapping[str, Any]) -> float:
        if tool_name == "inspect_spec":
            return self._inspect_cost_usd
        if tool_name == "propose_spec":
            return self._propose_cost_usd
        if tool_name == "submit_pattern":
            return self._submit_cost_usd
        if tool_name in {"compute", "test_assertion"}:
            spec_id = _required_str(args, "spec_id" if tool_name == "compute" else "spec_ref")
            spec = self._registry.get(spec_id)
            data_read_cost = len(spec.deps) * self._inspect_cost_usd
            multiplier = 2.0 if tool_name == "test_assertion" else 1.0
            return multiplier * (
                float(spec.cost.compute_usd) + float(spec.cost.llm_usd) + data_read_cost
            )
        raise ValueError(f"unknown tool {tool_name!r}")

    def _dispatch(
        self,
        *,
        tool_name: str,
        args: Mapping[str, Any],
        state: DiscoverToolState,
        tool_call_id: str,
    ) -> tuple[Any, float, float, int]:
        if tool_name == "inspect_spec":
            return self._inspect_spec(args)
        if tool_name == "compute":
            return self._compute(args, state)
        if tool_name == "propose_spec":
            return self._propose_spec(args)
        if tool_name == "test_assertion":
            return self._test_assertion(args, state, tool_call_id)
        if tool_name == "submit_pattern":
            return self._submit_pattern(args, state)
        raise ValueError(f"unknown tool {tool_name!r}")

    def _inspect_spec(self, args: Mapping[str, Any]) -> tuple[InspectSpecResult, float, float, int]:
        spec_id = _required_str(args, "spec_id")
        spec = self._registry.get(spec_id)
        result = InspectSpecResult(
            spec_id=spec.spec_id,
            name=spec.name,
            output_schema=spec.output_schema.as_dict(),
            declared_cost=spec.cost.as_dict(),
            sample_summary={"bounded": True, "sample_values": []},
            cost_estimate_usd=self._inspect_cost_usd,
        )
        return result, self._inspect_cost_usd, 0.0, 0

    def _compute(self, args: Mapping[str, Any], state: DiscoverToolState) -> tuple[ComputeResult, float, float, int]:
        spec_id = _required_str(args, "spec_id")
        window = _parse_window(args.get("window"))
        state.touched_windows.add(window)
        if self._access is None:
            raise RuntimeError("compute requires an AccessLayer")
        stage = RepresentStage(
            registry=self._registry,
            artifacts=self._artifacts,
            audit=self._audit,
            access=self._access,
            writer=self._writer,
            llm_client=self._represent_llm_client,
        )
        result = stage.run(
            RepresentInput(spec_version=spec_id, query_time=state.query_time),
            envelope={"cycle_id": state.cycle_id},
        )
        output = result.outputs
        summary = _summary_stats(output.tensor)
        current_cost = {
            "compute_usd": float(result.cost_used.compute_usd),
            "llm_usd": float(result.cost_used.llm_usd),
            "data_reads": int(result.cost_used.data_reads),
            "storage_bytes": int(output.cost_used.storage_bytes),
        }
        payload = ComputeResult(
            spec_id=spec_id,
            window=window.as_dict(),
            output_artifact_hash=result.output_hash,
            lineage_hashes=tuple(output.input_hashes),
            summary_stats=summary,
            sample_values=_sample_values(output.tensor),
            cost_used=current_cost,
        )
        return (
            payload,
            float(result.cost_used.compute_usd),
            float(result.cost_used.llm_usd),
            int(result.cost_used.data_reads),
        )

    def _propose_spec(self, args: Mapping[str, Any]) -> tuple[ProposeSpecResult, float, float, int]:
        body = args.get("body", args)
        if not isinstance(body, Mapping):
            raise ValueError("propose_spec body must be a mapping")
        _reject_open_ended_llm_prompts(body)
        spec_id = self._registry.register(body)
        spec = self._registry.get(spec_id)
        result = ProposeSpecResult(
            spec_id=spec_id,
            registered=True,
            declared_cost=spec.cost.as_dict(),
        )
        return result, self._propose_cost_usd, 0.0, 0

    def _test_assertion(
        self,
        args: Mapping[str, Any],
        state: DiscoverToolState,
        tool_call_id: str,
    ) -> tuple[TestAssertionResult, float, float, int]:
        spec_ref = _required_str(args, "spec_ref")
        assertion_body = args.get("assertion")
        if not isinstance(assertion_body, Mapping):
            raise ValueError("test_assertion assertion must be a mapping")
        assertion = load_assertion(assertion_body)
        window = _parse_window(args.get("window"))
        compute_result, compute_usd, llm_usd, data_reads = self._compute(
            {"spec_id": spec_ref, "window": window.as_dict()},
            state,
        )
        if not isinstance(compute_result, ComputeResult):
            raise RuntimeError("compute did not return ComputeResult")
        output = self._artifacts.get(compute_result.output_artifact_hash)
        represented = RepresentStage(
            registry=self._registry,
            artifacts=self._artifacts,
            audit=self._audit,
            access=self._access,
            writer=self._writer,
            llm_client=self._represent_llm_client,
        )._deserialize_output(output)
        result = bool(assertion.evaluate(represented.tensor))
        assertion_hash = discover_audit.digest_jsonable(assertion.hash_dict())
        summary_hash = discover_audit.digest_jsonable(compute_result.summary_stats)
        fingerprint_hash = discover_audit.digest_jsonable(
            {
                "spec_ref": spec_ref,
                "assertion_hash": assertion_hash,
                "window": window.as_dict(),
                "result": result,
                "summary_hash": summary_hash,
                "lineage_hashes": list(compute_result.lineage_hashes),
            }
        )
        fingerprint = AssertionFingerprint(
            fingerprint_hash=fingerprint_hash,
            spec_ref=spec_ref,
            assertion_hash=assertion_hash,
            assertion=assertion.public_dict(),
            window=window.as_dict(),
            result=result,
            summary_hash=summary_hash,
            lineage_hashes=compute_result.lineage_hashes,
        )
        if result:
            key = _assertion_key(spec_ref, assertion.public_dict(), window.as_dict())
            state.successful_assertions[key] = fingerprint
            prior = state.assertion_source_tools.get(key, ())
            state.assertion_source_tools[key] = prior + (tool_call_id,)
        payload = TestAssertionResult(
            spec_ref=spec_ref,
            assertion=assertion.public_dict(),
            window=window.as_dict(),
            result=result,
            fingerprint_hash=fingerprint_hash,
            summary_hash=summary_hash,
            lineage_hashes=compute_result.lineage_hashes,
        )
        return payload, compute_usd, llm_usd, data_reads

    def _submit_pattern(self, args: Mapping[str, Any], state: DiscoverToolState) -> tuple[SubmitPatternResult, float, float, int]:
        pattern_payload = args.get("pattern_body", args)
        if not isinstance(pattern_payload, Mapping):
            raise PatternValidationError("submit_pattern requires a Pattern body")
        if "pattern_id" in pattern_payload:
            pattern = load_pattern(pattern_payload)
            finalized = pattern.as_dict()
        else:
            finalized = finalize_pattern(pattern_payload)
            pattern = load_pattern(finalized)
        key = _assertion_key(
            pattern.spec_ref,
            pattern.assertion.public_dict(),
            pattern.observation_window.as_dict(),
        )
        fingerprint = state.successful_assertions.get(key)
        if fingerprint is None:
            raise PermissionError(
                "submit_pattern requires a prior successful test_assertion "
                "for the same spec_ref, assertion, and observation_window"
            )
        pattern_bytes = serialize_pattern(pattern)
        pattern_artifact_hash = self._artifacts.put(pattern_bytes)
        reserved = self._reserve_discover_windows(pattern.pattern_id, pattern.observation_window, state)
        result = SubmitPatternResult(
            pattern_id=pattern.pattern_id,
            pattern_artifact_hash=pattern_artifact_hash,
            pattern_body_hash=discover_audit.digest_jsonable(finalized),
            source_tool_call_ids=state.assertion_source_tools.get(key, ()),
            fingerprint_hash=fingerprint.fingerprint_hash,
            observation_window=pattern.observation_window.as_dict(),
            reserved_windows=reserved,
            rationale_hash=state.current_rationale_hash,
        )
        state.submitted_patterns.append(result)
        return result, self._submit_cost_usd, 0.0, 0

    def _reserve_discover_windows(
        self,
        pattern_id: str,
        observation_window: ObservationWindow,
        state: DiscoverToolState,
    ) -> tuple[dict[str, str], ...]:
        if self._access is None:
            raise RuntimeError("submit_pattern requires an AccessLayer")
        windows = {DiscoverWindow(**observation_window.as_dict())}
        windows.update(state.touched_windows)
        reservations: list[dict[str, str]] = []
        for window in sorted(windows, key=lambda item: (item.t0, item.t1)):
            t0, t1 = window.as_datetimes()
            reservation = self._access.reserve_window(
                pattern_id=pattern_id,
                stage="Discover",
                t0=t0,
                t1=t1,
            )
            reservations.append(reservation.as_dict())
        return tuple(reservations)


def _result_payload(result: Any) -> Any:
    if hasattr(result, "as_dict"):
        return result.as_dict()
    if hasattr(result, "__dataclass_fields__"):
        return asdict(result)
    return result


def _required_str(args: Mapping[str, Any], key: str) -> str:
    value = args.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} must be a non-empty string")
    return value


def _parse_window(raw: Any) -> DiscoverWindow:
    if not isinstance(raw, Mapping) or set(raw.keys()) != {"t0", "t1"}:
        raise ValueError("window must contain t0 and t1")
    start = _parse_time(raw["t0"], "window.t0")
    end = _parse_time(raw["t1"], "window.t1")
    if end < start:
        raise ValueError("window.t1 must be >= t0")
    return DiscoverWindow(t0=start.isoformat(), t1=end.isoformat())


def _parse_time(value: Any, label: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value:
        parsed = datetime.fromisoformat(value)
    else:
        raise ValueError(f"{label} must be an ISO-8601 timestamp")
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _summary_stats(value: Any) -> dict[str, Any]:
    array = np.asarray(value)
    payload: dict[str, Any] = {
        "dtype": str(array.dtype),
        "shape": list(array.shape),
        "size": int(array.size),
    }
    try:
        numeric = np.asarray(value, dtype=float).reshape(-1)
    except (TypeError, ValueError):
        return payload | {"numeric": False}
    finite = numeric[np.isfinite(numeric)]
    payload["numeric"] = True
    payload["finite_count"] = int(finite.size)
    if finite.size:
        payload["min"] = float(np.min(finite))
        payload["max"] = float(np.max(finite))
        payload["mean"] = float(np.mean(finite))
    return payload


def _sample_values(value: Any, *, limit: int = 5) -> tuple[Any, ...]:
    array = np.asarray(value).reshape(-1)
    sample: list[Any] = []
    for item in array[:limit]:
        if hasattr(item, "item"):
            sample.append(item.item())
        else:
            sample.append(item)
    return tuple(_canonical_copy(sample))


def _assertion_key(spec_ref: str, assertion_body: Mapping[str, Any], window: Mapping[str, str]) -> str:
    assertion = load_assertion(assertion_body)
    return discover_audit.digest_jsonable(
        {
            "spec_ref": spec_ref,
            "assertion_hash": discover_audit.digest_jsonable(assertion.hash_dict()),
            "window": dict(window),
        }
    )


def _reject_open_ended_llm_prompts(body: Mapping[str, Any]) -> None:
    graph = body.get("graph")
    if not isinstance(graph, Mapping):
        return
    nodes = graph.get("nodes")
    if not isinstance(nodes, list):
        return
    blocked = {"discover", "find", "suggest", "explore", "hypothesis", "what about"}
    for node in nodes:
        if not isinstance(node, Mapping) or node.get("op") != "llm_call":
            continue
        args = node.get("args")
        if not isinstance(args, Mapping):
            continue
        template = args.get("prompt_template")
        if not isinstance(template, str):
            continue
        folded = template.lower()
        if any(term in folded for term in blocked):
            raise ValueError("propose_spec rejects open-ended LLM discovery prompts")


def _canonical_copy(value: Any) -> Any:
    return json.loads(canonicalize(value).decode("utf-8"))
