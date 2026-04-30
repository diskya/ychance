from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal, Mapping, Protocol

from audit import canonicalize
from pipeline import CostCeiling, InvariantViolation, Stage, StageContext
from represent import LLMResponse, SpecRegistry
from represent.llm_client import params_hash, prompt_hash

from . import audit as discover_audit
from .budget import BudgetKill, CycleBudget, DiscoverCostUsed
from .input_shape import classify_operator_input
from .prompts import (
    CHEAP_ITERATION_PROMPT_TEMPLATE,
    FRONTIER_SUBMISSION_PROMPT_TEMPLATE,
    build_cheap_iteration_prompt,
    build_frontier_submission_prompt,
)
from .tools import DiscoverToolRouter, DiscoverToolState, SubmitPatternResult, ToolCallError


class DiscoverLLMClient(Protocol):
    def complete(self, *, model: str, prompt: str, params: dict[str, Any]) -> LLMResponse:
        ...


@dataclass(frozen=True)
class DiscoverInput:
    cycle_id: str
    query_time: str
    spec_ids: tuple[str, ...]
    archive_snapshot_hash: str | None
    anti_pattern_list_hash: str | None
    operator_inputs: tuple[str, ...]
    max_patterns: int


@dataclass(frozen=True)
class DiscoverOutput:
    status: Literal["submitted", "no_pattern", "killed_budget", "error"]
    pattern_ids: tuple[str, ...]
    pattern_artifact_hashes: tuple[str, ...]
    tool_trace_hash: str
    cost_used: DiscoverCostUsed
    no_pattern_reason: str | None


@dataclass(frozen=True)
class _AgentAction:
    tool_name: str
    args: dict[str, Any]


@dataclass(frozen=True)
class _AgentDecision:
    actions: tuple[_AgentAction, ...]
    final: str | None
    rationale: str | None


class DiscoverStage(Stage):
    name = "discover"
    version = "1"
    audit_stage = "Discover"
    cost_ceiling = CostCeiling(compute_usd=10.0, llm_usd=10.0, data_reads=100_000)
    InputType = DiscoverInput
    OutputType = DiscoverOutput

    def __init__(
        self,
        *,
        registry: SpecRegistry,
        artifacts,
        audit,
        access,
        writer=None,
        cheap_client: DiscoverLLMClient,
        frontier_client: DiscoverLLMClient,
        cheap_model: str = "qwen-plus",
        frontier_model: str = "qwen-plus-frontier",
        cheap_params: Mapping[str, Any] | None = None,
        frontier_params: Mapping[str, Any] | None = None,
        cheap_call_reserved_usd: float = 0.001,
        frontier_call_reserved_usd: float = 0.01,
        cycle_cost_cap_usd: float = 0.05,
        data_read_usd: float = 0.0,
        max_cheap_steps: int = 8,
        represent_llm_client: Any = None,
    ) -> None:
        if not isinstance(registry, SpecRegistry):
            raise TypeError("registry must be a SpecRegistry")
        if max_cheap_steps < 0:
            raise ValueError("max_cheap_steps must be non-negative")
        super().__init__(artifacts=artifacts, audit=audit, access=access, writer=writer)
        self._registry = registry
        self._cheap_client = cheap_client
        self._frontier_client = frontier_client
        self._cheap_model = cheap_model
        self._frontier_model = frontier_model
        self._cheap_params = dict(cheap_params or {"temperature": 0, "max_tokens": 512})
        self._frontier_params = dict(frontier_params or {"temperature": 0, "max_tokens": 512})
        self._cheap_call_reserved_usd = float(cheap_call_reserved_usd)
        self._frontier_call_reserved_usd = float(frontier_call_reserved_usd)
        self._cycle_cost_cap_usd = float(cycle_cost_cap_usd)
        self._data_read_usd = float(data_read_usd)
        self._max_cheap_steps = int(max_cheap_steps)
        self._represent_llm_client = represent_llm_client
        self._last_tool_records: tuple[discover_audit.ToolCallRecord, ...] = ()

    def compute(self, inputs: DiscoverInput, ctx: StageContext) -> DiscoverOutput:
        envelope = {"cycle_id": inputs.cycle_id}
        if ctx.access is not None:
            ctx.access.begin_cycle(inputs.cycle_id)

        budget = CycleBudget(
            cap_usd=self._cycle_cost_cap_usd,
            data_read_usd=self._data_read_usd,
        )
        tool_records: list[discover_audit.ToolCallRecord] = []
        state = DiscoverToolState(cycle_id=inputs.cycle_id, query_time=inputs.query_time)
        router = DiscoverToolRouter(
            registry=self._registry,
            artifacts=self._artifacts,
            audit=self._audit,
            access=ctx.access,
            writer=ctx.writer,
            represent_llm_client=self._represent_llm_client,
        )
        discover_audit.append_cycle_start(
            self._audit,
            envelope=envelope,
            cycle_id=inputs.cycle_id,
            query_time=inputs.query_time,
            caps={
                "cycle_cost_cap_usd": self._cycle_cost_cap_usd,
                "data_read_usd": self._data_read_usd,
                "max_cheap_steps": self._max_cheap_steps,
                "max_patterns": inputs.max_patterns,
            },
            model_ids={
                "cheap_iteration": self._cheap_model,
                "frontier_submission": self._frontier_model,
            },
            prompt_hashes={
                "cheap_iteration": prompt_hash(CHEAP_ITERATION_PROMPT_TEMPLATE),
                "frontier_submission": prompt_hash(FRONTIER_SUBMISSION_PROMPT_TEMPLATE),
            },
            archive_snapshot_hash=inputs.archive_snapshot_hash,
            anti_pattern_list_hash=inputs.anti_pattern_list_hash,
            spec_snapshot_hash=discover_audit.digest_jsonable(list(inputs.spec_ids)),
        )

        directives = self._log_operator_inputs(inputs, envelope)
        if inputs.max_patterns <= 0:
            return self._no_pattern(
                envelope=envelope,
                reason="max_patterns_is_zero",
                steps_used=0,
                budget=budget,
                tool_records=tool_records,
            )

        step_index = 0
        try:
            for _ in range(self._max_cheap_steps):
                if state.successful_assertions:
                    break
                trace_summary = _trace_summary(tool_records)
                prompt = build_cheap_iteration_prompt(
                    cycle_id=inputs.cycle_id,
                    spec_ids=inputs.spec_ids,
                    normalized_directives=directives,
                    trace_summary=trace_summary,
                    max_patterns=inputs.max_patterns,
                )
                response = self._call_model(
                    phase="cheap_iteration",
                    client=self._cheap_client,
                    model=self._cheap_model,
                    params=self._cheap_params,
                    prompt=prompt,
                    reserved_usd=self._cheap_call_reserved_usd,
                    envelope=envelope,
                    budget=budget,
                    ctx=ctx,
                )
                decision = _parse_agent_decision(response.text)
                self._log_rationale(decision, envelope, "cheap_iteration", state)
                if _is_no_pattern(decision.final):
                    return self._no_pattern(
                        envelope=envelope,
                        reason="cheap_model_returned_no_pattern",
                        steps_used=step_index,
                        budget=budget,
                        tool_records=tool_records,
                    )
                if not decision.actions:
                    break
                for action in decision.actions:
                    outcome = router.call(
                        tool_name=action.tool_name,
                        args=action.args,
                        phase="cheap_iteration",
                        step_index=step_index,
                        envelope=envelope,
                        state=state,
                        budget=budget,
                        ctx=ctx,
                    )
                    tool_records.append(outcome.record)
                    step_index += 1
                    if state.successful_assertions:
                        break

            if not state.successful_assertions:
                return self._no_pattern(
                    envelope=envelope,
                    reason="no_successful_test_assertion",
                    steps_used=step_index,
                    budget=budget,
                    tool_records=tool_records,
                )

            prompt = build_frontier_submission_prompt(
                cycle_id=inputs.cycle_id,
                tested_drafts=state.tested_drafts,
                max_patterns=inputs.max_patterns,
            )
            response = self._call_model(
                phase="frontier_submission",
                client=self._frontier_client,
                model=self._frontier_model,
                params=self._frontier_params,
                prompt=prompt,
                reserved_usd=self._frontier_call_reserved_usd,
                envelope=envelope,
                budget=budget,
                ctx=ctx,
            )
            decision = _parse_agent_decision(response.text)
            self._log_rationale(decision, envelope, "frontier_submission", state)
            if _is_no_pattern(decision.final) or not decision.actions:
                return self._no_pattern(
                    envelope=envelope,
                    reason="frontier_model_returned_no_pattern",
                    steps_used=step_index,
                    budget=budget,
                    tool_records=tool_records,
                )

            submitted: list[SubmitPatternResult] = []
            for action in decision.actions:
                outcome = router.call(
                    tool_name=action.tool_name,
                    args=action.args,
                    phase="frontier_submission",
                    step_index=step_index,
                    envelope=envelope,
                    state=state,
                    budget=budget,
                    ctx=ctx,
                )
                tool_records.append(outcome.record)
                step_index += 1
                if isinstance(outcome.result, SubmitPatternResult):
                    submitted.append(outcome.result)
                    discover_audit.append_submission(
                        self._audit,
                        envelope=envelope,
                        pattern_id=outcome.result.pattern_id,
                        pattern_body_hash=outcome.result.pattern_body_hash,
                        source_tool_call_ids=outcome.result.source_tool_call_ids,
                        fingerprint_hash=outcome.result.fingerprint_hash,
                        reserved_windows=outcome.result.reserved_windows,
                        rationale_hash=outcome.result.rationale_hash,
                    )
                if len(submitted) >= inputs.max_patterns:
                    break

            if not submitted:
                return self._no_pattern(
                    envelope=envelope,
                    reason="frontier_did_not_submit",
                    steps_used=step_index,
                    budget=budget,
                    tool_records=tool_records,
                )
            self._last_tool_records = tuple(tool_records)
            return DiscoverOutput(
                status="submitted",
                pattern_ids=tuple(item.pattern_id for item in submitted),
                pattern_artifact_hashes=tuple(item.pattern_artifact_hash for item in submitted),
                tool_trace_hash=discover_audit.stable_tool_trace_hash(tool_records),
                cost_used=budget.used(),
                no_pattern_reason=None,
            )
        except BudgetKill as exc:
            discover_audit.append_budget_kill(
                self._audit,
                envelope=envelope,
                attempted_action=exc.attempted_action,
                requested_usd=exc.requested_usd,
                remaining_usd=exc.remaining_usd,
                cost_used=budget.used().as_dict(),
            )
            self._last_tool_records = tuple(tool_records)
            return DiscoverOutput(
                status="killed_budget",
                pattern_ids=(),
                pattern_artifact_hashes=(),
                tool_trace_hash=discover_audit.stable_tool_trace_hash(tool_records),
                cost_used=budget.used(),
                no_pattern_reason="budget_exhausted",
            )
        except ToolCallError as exc:
            if exc.record is not None and all(
                item.tool_call_id != exc.record.tool_call_id for item in tool_records
            ):
                tool_records.append(exc.record)
            if exc.error_type in {"BudgetKill", "RateLimitExceeded", "CostCeilingExceeded"}:
                discover_audit.append_budget_kill(
                    self._audit,
                    envelope=envelope,
                    attempted_action=f"tool:{exc.record.tool_name}" if exc.record else "tool",
                    requested_usd=0.0,
                    remaining_usd=budget.remaining_usd,
                    cost_used=budget.used().as_dict(),
                )
                self._last_tool_records = tuple(tool_records)
                return DiscoverOutput(
                    status="killed_budget",
                    pattern_ids=(),
                    pattern_artifact_hashes=(),
                    tool_trace_hash=discover_audit.stable_tool_trace_hash(tool_records),
                    cost_used=budget.used(),
                    no_pattern_reason="budget_exhausted",
                )
            self._last_tool_records = tuple(tool_records)
            return DiscoverOutput(
                status="error",
                pattern_ids=(),
                pattern_artifact_hashes=(),
                tool_trace_hash=discover_audit.stable_tool_trace_hash(tool_records),
                cost_used=budget.used(),
                no_pattern_reason=None,
            )
        except Exception as exc:
            discover_audit.append_error(
                self._audit,
                envelope=envelope,
                error_type=type(exc).__name__,
                message=str(exc),
                cost_used=budget.used().as_dict(),
            )
            self._last_tool_records = tuple(tool_records)
            return DiscoverOutput(
                status="error",
                pattern_ids=(),
                pattern_artifact_hashes=(),
                tool_trace_hash=discover_audit.stable_tool_trace_hash(tool_records),
                cost_used=budget.used(),
                no_pattern_reason=None,
            )

    def invariant(self, inputs: DiscoverInput, outputs: DiscoverOutput) -> None:
        if outputs.status not in {"submitted", "no_pattern", "killed_budget", "error"}:
            raise InvariantViolation("Discover output status is invalid")
        if len(outputs.tool_trace_hash) != 64:
            raise InvariantViolation("tool_trace_hash must be a sha256 hex digest")
        if len(outputs.pattern_ids) != len(outputs.pattern_artifact_hashes):
            raise InvariantViolation("pattern id and artifact hash counts differ")
        if len(outputs.pattern_ids) > inputs.max_patterns:
            raise InvariantViolation("Discover submitted more patterns than max_patterns")
        if outputs.status == "submitted" and not outputs.pattern_ids:
            raise InvariantViolation("submitted status requires at least one pattern")
        if outputs.status == "no_pattern" and outputs.no_pattern_reason is None:
            raise InvariantViolation("no_pattern status requires a reason")
        if outputs.cost_used.realized_usd > outputs.cost_used.cap_usd:
            raise InvariantViolation("Discover output exceeded its cycle cap")

    def audit_extra_payload(
        self,
        inputs: DiscoverInput,
        outputs: DiscoverOutput,
        ctx: StageContext,
        *,
        inputs_hash: str,
        output_hash: str,
    ) -> dict[str, Any]:
        return {
            "status": outputs.status,
            "pattern_ids": list(outputs.pattern_ids),
            "pattern_artifact_hashes": list(outputs.pattern_artifact_hashes),
            "tool_trace_hash": outputs.tool_trace_hash,
            "cost_used": outputs.cost_used.as_dict(),
            "no_pattern_reason": outputs.no_pattern_reason,
        }

    def _log_operator_inputs(
        self,
        inputs: DiscoverInput,
        envelope: dict[str, str],
    ) -> tuple[str, ...]:
        directives: list[str] = []
        for text in inputs.operator_inputs:
            classification = classify_operator_input(text)
            if classification.shape_classification == "flagged":
                response = "rejected: content-shaped input withheld from agent"
            else:
                response = "accepted: normalized directive passed to agent"
                if classification.normalized_directive is not None:
                    directives.append(classification.normalized_directive)
            discover_audit.append_operator_input(
                self._audit,
                envelope=envelope,
                input_text=text,
                shape_classification=classification.shape_classification,
                normalized_directive=classification.normalized_directive,
                rejection_reason=classification.rejection_reason,
                agent_response=response,
            )
        return tuple(directives)

    def _call_model(
        self,
        *,
        phase: str,
        client: DiscoverLLMClient,
        model: str,
        params: dict[str, Any],
        prompt: str,
        reserved_usd: float,
        envelope: dict[str, str],
        budget: CycleBudget,
        ctx: StageContext,
    ) -> LLMResponse:
        reservation = budget.reserve(kind="llm", action=f"model:{phase}", usd=reserved_usd)
        try:
            response = client.complete(model=model, prompt=prompt, params=dict(params))
        except Exception as exc:
            budget.charge(reservation, realized_usd=0.0)
            discover_audit.append_model_call(
                self._audit,
                envelope=envelope,
                phase=phase,
                model_id=model,
                prompt_hash=prompt_hash(prompt),
                params_hash=params_hash(model=model, params=params),
                input_tokens=0,
                output_tokens=0,
                reserved_cost=reserved_usd,
                realized_cost=0.0,
                output_hash=discover_audit.digest_jsonable(
                    {"error": type(exc).__name__, "message": str(exc)}
                ),
            )
            raise
        if not isinstance(response, LLMResponse):
            budget.charge(reservation, realized_usd=0.0)
            raise TypeError("Discover LLM client must return LLMResponse")
        realized = _realized_model_cost(response, reserved_usd)
        budget.charge(reservation, realized_usd=realized)
        if realized:
            ctx.charge_llm(realized)
        discover_audit.append_model_call(
            self._audit,
            envelope=envelope,
            phase=phase,
            model_id=model,
            prompt_hash=prompt_hash(prompt),
            params_hash=params_hash(model=model, params=params),
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            reserved_cost=reserved_usd,
            realized_cost=realized,
            output_hash=discover_audit.digest_jsonable(response.text),
        )
        return response

    def _log_rationale(
        self,
        decision: _AgentDecision,
        envelope: dict[str, str],
        phase: str,
        state: DiscoverToolState,
    ) -> None:
        if not decision.rationale:
            return
        discover_audit.append_rationale(
            self._audit,
            envelope=envelope,
            phase=phase,
            rationale_text=decision.rationale,
        )
        state.current_rationale_hash = discover_audit.digest_jsonable(decision.rationale)

    def _no_pattern(
        self,
        *,
        envelope: dict[str, str],
        reason: str,
        steps_used: int,
        budget: CycleBudget,
        tool_records: list[discover_audit.ToolCallRecord],
    ) -> DiscoverOutput:
        discover_audit.append_no_pattern(
            self._audit,
            envelope=envelope,
            reason=reason,
            steps_used=steps_used,
            budget_remaining=budget.remaining_usd,
        )
        self._last_tool_records = tuple(tool_records)
        return DiscoverOutput(
            status="no_pattern",
            pattern_ids=(),
            pattern_artifact_hashes=(),
            tool_trace_hash=discover_audit.stable_tool_trace_hash(tool_records),
            cost_used=budget.used(),
            no_pattern_reason=reason,
        )


def _parse_agent_decision(text: str) -> _AgentDecision:
    stripped = text.strip()
    if stripped == "NO_PATTERN":
        return _AgentDecision(actions=(), final="NO_PATTERN", rationale=None)
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise ValueError("Discover model response must be JSON or NO_PATTERN") from exc
    if not isinstance(payload, dict):
        raise ValueError("Discover model response must be an object")
    final = payload.get("final") or payload.get("status")
    if final is not None and not isinstance(final, str):
        raise ValueError("Discover model final/status must be a string")
    rationale = payload.get("rationale")
    if rationale is not None and not isinstance(rationale, str):
        raise ValueError("Discover model rationale must be a string")
    raw_actions = payload.get("actions", payload.get("tool_calls", ()))
    if "tool" in payload or "name" in payload:
        raw_actions = [payload]
    if raw_actions is None:
        raw_actions = []
    if not isinstance(raw_actions, list):
        raise ValueError("Discover model actions/tool_calls must be a list")
    actions: list[_AgentAction] = []
    for item in raw_actions:
        if not isinstance(item, Mapping):
            raise ValueError("every Discover action must be an object")
        tool_name = item.get("tool") or item.get("name")
        if not isinstance(tool_name, str) or not tool_name:
            raise ValueError("every Discover action requires a tool/name")
        args = item.get("args", {})
        if not isinstance(args, Mapping):
            raise ValueError("Discover action args must be an object")
        actions.append(
            _AgentAction(
                tool_name=tool_name,
                args=json.loads(canonicalize(dict(args)).decode("utf-8")),
            )
        )
    return _AgentDecision(actions=tuple(actions), final=final, rationale=rationale)


def _is_no_pattern(value: str | None) -> bool:
    return isinstance(value, str) and value.upper() == "NO_PATTERN"


def _trace_summary(records: list[discover_audit.ToolCallRecord]) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "step_index": item.step_index,
            "phase": item.phase,
            "tool_name": item.tool_name,
            "result_hash": item.result_hash,
            "outcome": item.outcome,
        }
        for item in records
    )


def _realized_model_cost(response: LLMResponse, reserved_usd: float) -> float:
    for key in ("realized_cost_usd", "cost_usd"):
        value = response.raw_json.get(key)
        if isinstance(value, (int, float)) and value >= 0.0:
            return float(value)
    return float(reserved_usd)
