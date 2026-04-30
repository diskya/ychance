from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from typing import Any, Iterable

from audit import AuditLog, canonicalize


def digest_jsonable(value: Any) -> str:
    return hashlib.sha256(canonicalize(value)).hexdigest()


@dataclass(frozen=True)
class ToolCallRecord:
    tool_call_id: str
    step_index: int
    phase: str
    tool_name: str
    args_hash: str
    result_hash: str
    outcome: str
    error_type: str | None
    cost_before: dict[str, Any]
    cost_after: dict[str, Any]
    start_record_hash: str
    end_record_hash: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def stable_tool_trace_hash(records: Iterable[ToolCallRecord]) -> str:
    trace: list[dict[str, Any]] = []
    for record in records:
        item = record.as_dict()
        item.pop("start_record_hash", None)
        item.pop("end_record_hash", None)
        trace.append(item)
    return digest_jsonable(trace)


def append_cycle_start(
    audit: AuditLog,
    *,
    envelope: dict[str, str],
    cycle_id: str,
    query_time: str,
    caps: dict[str, Any],
    model_ids: dict[str, str],
    prompt_hashes: dict[str, str],
    archive_snapshot_hash: str | None,
    anti_pattern_list_hash: str | None,
    spec_snapshot_hash: str,
) -> str:
    return audit.append(
        {
            "category": "Discover",
            "stage": "Discover",
            "envelope": envelope,
            "kind": "DiscoverCycleStart",
            "cycle_id": cycle_id,
            "query_time": query_time,
            "caps": caps,
            "model_ids": model_ids,
            "prompt_hashes": prompt_hashes,
            "archive_snapshot_hash": archive_snapshot_hash,
            "anti_pattern_list_hash": anti_pattern_list_hash,
            "spec_snapshot_hash": spec_snapshot_hash,
        }
    )


def append_operator_input(
    audit: AuditLog,
    *,
    envelope: dict[str, str],
    input_text: str,
    shape_classification: str,
    normalized_directive: str | None,
    rejection_reason: str | None,
    agent_response: str,
) -> str:
    return audit.append(
        {
            "category": "Discover",
            "stage": "Discover",
            "envelope": envelope,
            "kind": "CoResearchInput",
            "input_text": input_text,
            "shape_classification": shape_classification,
            "normalized_directive": normalized_directive,
            "rejection_reason": rejection_reason,
            "agent_response": agent_response,
        }
    )


def append_model_call(
    audit: AuditLog,
    *,
    envelope: dict[str, str],
    phase: str,
    model_id: str,
    prompt_hash: str,
    params_hash: str,
    input_tokens: int,
    output_tokens: int,
    reserved_cost: float,
    realized_cost: float,
    output_hash: str,
) -> str:
    return audit.append(
        {
            "category": "Discover",
            "stage": "Discover",
            "envelope": envelope,
            "kind": "DiscoverModelCall",
            "phase": phase,
            "model_id": model_id,
            "prompt_hash": prompt_hash,
            "params_hash": params_hash,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "reserved_cost": reserved_cost,
            "realized_cost": realized_cost,
            "output_hash": output_hash,
        }
    )


def append_rationale(
    audit: AuditLog,
    *,
    envelope: dict[str, str],
    phase: str,
    rationale_text: str,
) -> str:
    return audit.append(
        {
            "category": "Discover",
            "stage": "Discover",
            "envelope": envelope,
            "kind": "DiscoverRationale",
            "phase": phase,
            "rationale_hash": digest_jsonable(rationale_text),
            "rationale_text": rationale_text,
            "withheld_from_council": True,
        }
    )


def append_tool_start(
    audit: AuditLog,
    *,
    envelope: dict[str, str],
    tool_call_id: str,
    step_index: int,
    phase: str,
    tool_name: str,
    args_hash: str,
    cost_before: dict[str, Any],
) -> str:
    return audit.append(
        {
            "category": "Discover",
            "stage": "Discover",
            "envelope": envelope,
            "kind": "DiscoverToolCallStart",
            "tool_call_id": tool_call_id,
            "step_index": step_index,
            "phase": phase,
            "tool_name": tool_name,
            "args_hash": args_hash,
            "cost_before": cost_before,
        }
    )


def append_tool_end(
    audit: AuditLog,
    *,
    envelope: dict[str, str],
    tool_call_id: str,
    step_index: int,
    phase: str,
    tool_name: str,
    args_hash: str,
    result_hash: str,
    outcome: str,
    error_type: str | None,
    cost_before: dict[str, Any],
    cost_after: dict[str, Any],
    access_read_count_delta: int,
    start_record_hash: str,
) -> str:
    return audit.append(
        {
            "category": "Discover",
            "stage": "Discover",
            "envelope": envelope,
            "kind": "DiscoverToolCallEnd",
            "tool_call_id": tool_call_id,
            "step_index": step_index,
            "phase": phase,
            "tool_name": tool_name,
            "args_hash": args_hash,
            "result_hash": result_hash,
            "outcome": outcome,
            "error_type": error_type,
            "cost_before": cost_before,
            "cost_after": cost_after,
            "access_read_count_delta": access_read_count_delta,
            "start_record_hash": start_record_hash,
        }
    )


def append_no_pattern(
    audit: AuditLog,
    *,
    envelope: dict[str, str],
    reason: str,
    steps_used: int,
    budget_remaining: float,
) -> str:
    return audit.append(
        {
            "category": "Discover",
            "stage": "Discover",
            "envelope": envelope,
            "kind": "DiscoverNoPattern",
            "reason": reason,
            "steps_used": steps_used,
            "budget_remaining": budget_remaining,
        }
    )


def append_budget_kill(
    audit: AuditLog,
    *,
    envelope: dict[str, str],
    attempted_action: str,
    requested_usd: float,
    remaining_usd: float,
    cost_used: dict[str, Any],
) -> str:
    return audit.append(
        {
            "category": "Discover",
            "stage": "Discover",
            "envelope": envelope,
            "kind": "DiscoverBudgetKill",
            "attempted_action": attempted_action,
            "requested_usd": requested_usd,
            "remaining_usd": remaining_usd,
            "cost_used": cost_used,
        }
    )


def append_submission(
    audit: AuditLog,
    *,
    envelope: dict[str, str],
    pattern_id: str,
    pattern_body_hash: str,
    source_tool_call_ids: tuple[str, ...],
    fingerprint_hash: str,
    reserved_windows: tuple[dict[str, str], ...],
    rationale_hash: str | None,
) -> str:
    return audit.append(
        {
            "category": "Discover",
            "stage": "Discover",
            "envelope": envelope | {"pattern_id": pattern_id},
            "kind": "DiscoverSubmission",
            "pattern_id": pattern_id,
            "pattern_body_hash": pattern_body_hash,
            "source_tool_call_ids": list(source_tool_call_ids),
            "fingerprint_hash": fingerprint_hash,
            "reserved_windows": list(reserved_windows),
            "rationale_hash": rationale_hash,
        }
    )


def append_error(
    audit: AuditLog,
    *,
    envelope: dict[str, str],
    error_type: str,
    message: str,
    cost_used: dict[str, Any],
) -> str:
    return audit.append(
        {
            "category": "Discover",
            "stage": "Discover",
            "envelope": envelope,
            "kind": "DiscoverError",
            "error_type": error_type,
            "message": message,
            "cost_used": cost_used,
        }
    )
