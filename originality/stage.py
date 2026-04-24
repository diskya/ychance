from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Mapping

from audit import canonicalize
from pipeline import CostCeiling, InvariantViolation, Stage, StageContext
from rule import Rule, load_rule

from .matcher import evaluate_matcher
from .state import (
    AntiPatternListState,
    OriginalityConfig,
    active_entries,
    config_hash,
    empty_seed_state,
    state_hash,
    with_entry_hits,
)
from .stats import compute_grounding_stats, hash_payload


@dataclass(frozen=True)
class OriginalityInput:
    cycle_id: str
    cycle_index: int
    candidates: tuple[Rule | Mapping[str, Any], ...]
    anti_pattern_state: AntiPatternListState = field(default_factory=empty_seed_state)
    config: OriginalityConfig = field(default_factory=OriginalityConfig)

    def __post_init__(self) -> None:
        if not isinstance(self.cycle_id, str) or not self.cycle_id:
            raise ValueError("cycle_id must be a non-empty string")
        if not isinstance(self.cycle_index, int) or self.cycle_index < 0:
            raise ValueError("cycle_index must be a non-negative int")
        loaded: list[Rule] = []
        for item in self.candidates:
            loaded.append(item if isinstance(item, Rule) else load_rule(item))
        object.__setattr__(self, "candidates", tuple(loaded))

    def as_dict(self) -> dict[str, Any]:
        return {
            "cycle_id": self.cycle_id,
            "cycle_index": self.cycle_index,
            "candidates": [rule.to_dict() for rule in self.candidates],
            "anti_pattern_state": self.anti_pattern_state.as_dict(),
            "config": self.config.as_dict(),
        }


@dataclass(frozen=True)
class OriginalityDecision:
    rule_id: str
    result: str
    matched_anti_pattern: str | None
    anti_pattern_list_version: str
    state_hash: str
    config_hash: str
    grounding_hash: str
    stats_hash: str
    trace_hash: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "result": self.result,
            "matched_anti_pattern": self.matched_anti_pattern,
            "anti_pattern_list_version": self.anti_pattern_list_version,
            "state_hash": self.state_hash,
            "config_hash": self.config_hash,
            "grounding_hash": self.grounding_hash,
            "stats_hash": self.stats_hash,
            "trace_hash": self.trace_hash,
        }


@dataclass(frozen=True)
class OriginalityOutput:
    accepted_rules: tuple[Rule, ...]
    decisions: tuple[OriginalityDecision, ...]
    anti_pattern_state: AntiPatternListState

    def as_dict(self) -> dict[str, Any]:
        return {
            "accepted_rules": [rule.to_dict() for rule in self.accepted_rules],
            "decisions": [decision.as_dict() for decision in self.decisions],
            "anti_pattern_state": self.anti_pattern_state.as_dict(),
        }


class OriginalityStage(Stage):
    name = "originality_filter"
    version = "1"
    audit_stage = "Propose"
    audit_category = "Originality-filter"
    cost_ceiling = CostCeiling(compute_usd=0.5, llm_usd=0.0, data_reads=2048)
    InputType = OriginalityInput
    OutputType = OriginalityOutput

    def __init__(
        self,
        *,
        registry: Any,
        artifacts,
        audit,
        access=None,
        writer=None,
    ) -> None:
        super().__init__(artifacts=artifacts, audit=audit, access=access, writer=writer)
        self._registry = registry

    def fingerprint(self, inputs: Any) -> tuple[str, str]:
        if not isinstance(inputs, OriginalityInput):
            return super().fingerprint(inputs)
        inputs_hash = hash_payload(inputs.as_dict())
        fp = hashlib.sha256(
            canonicalize(
                {
                    "name": self.name,
                    "version": self.version,
                    "inputs_hash": inputs_hash,
                }
            )
        ).hexdigest()
        return inputs_hash, fp

    def compute(self, inputs: OriginalityInput, ctx: StageContext) -> OriginalityOutput:
        if ctx.access is None:
            raise RuntimeError("OriginalityStage requires an AccessLayer")

        state_before = state_hash(inputs.anti_pattern_state)
        cfg_hash = config_hash(inputs.config)
        entries = active_entries(inputs.anti_pattern_state)
        accepted: list[Rule] = []
        decisions: list[OriginalityDecision] = []
        hit_ids: list[str] = []

        for rule in inputs.candidates:
            ctx.charge_compute(0.000001)
            stats = compute_grounding_stats(rule, ctx.access, self._registry)
            matched: str | None = None
            trace_items: list[dict[str, Any]] = []
            for entry in entries:
                ctx.charge_compute(0.000001)
                did_match, trace = evaluate_matcher(entry.matcher, stats)
                trace_items.append(
                    {
                        "entry_id": entry.entry_id,
                        "result": did_match,
                        "trace_hash": trace.trace_hash,
                    }
                )
                if did_match:
                    matched = entry.entry_id
                    hit_ids.append(entry.entry_id)
                    break

            trace_hash = hash_payload({"items": trace_items})
            if matched is None:
                accepted.append(rule)
                outcome = "pass"
            else:
                outcome = "reject"
            decisions.append(
                OriginalityDecision(
                    rule_id=rule.rule_id,
                    result=outcome,
                    matched_anti_pattern=matched,
                    anti_pattern_list_version=inputs.anti_pattern_state.version,
                    state_hash=state_before,
                    config_hash=cfg_hash,
                    grounding_hash=stats.grounding_hash,
                    stats_hash=stats.stats_hash,
                    trace_hash=trace_hash,
                )
            )

        state_after = with_entry_hits(
            inputs.anti_pattern_state,
            tuple(sorted(set(hit_ids))),
            inputs.cycle_index,
        )
        return OriginalityOutput(
            accepted_rules=tuple(accepted),
            decisions=tuple(decisions),
            anti_pattern_state=state_after,
        )

    def invariant(self, inputs: OriginalityInput, outputs: OriginalityOutput) -> None:
        if len(outputs.decisions) != len(inputs.candidates):
            raise InvariantViolation("one decision is required per candidate")
        input_ids = [rule.rule_id for rule in inputs.candidates]
        decision_ids = [decision.rule_id for decision in outputs.decisions]
        if decision_ids != input_ids:
            raise InvariantViolation("decision order must match candidate order")
        pass_ids = [decision.rule_id for decision in outputs.decisions if decision.result == "pass"]
        accepted_ids = [rule.rule_id for rule in outputs.accepted_rules]
        if accepted_ids != pass_ids:
            raise InvariantViolation("accepted rules must be the passed candidates")
        for decision in outputs.decisions:
            if decision.result not in {"pass", "reject"}:
                raise InvariantViolation("decision result must be pass or reject")
            if decision.result == "reject" and decision.matched_anti_pattern is None:
                raise InvariantViolation("reject decision must include matched_anti_pattern")
            if decision.result == "pass" and decision.matched_anti_pattern is not None:
                raise InvariantViolation("pass decision must not include matched_anti_pattern")
        input_entry_ids = {entry.entry_id for entry in inputs.anti_pattern_state.entries}
        output_entry_ids = {entry.entry_id for entry in outputs.anti_pattern_state.entries}
        if not output_entry_ids.issubset(input_entry_ids):
            raise InvariantViolation("stage must not add entries")

    def audit_extra_payload(
        self,
        inputs: OriginalityInput,
        outputs: OriginalityOutput,
        ctx: StageContext,
        *,
        inputs_hash: str,
        output_hash: str,
    ) -> dict[str, Any]:
        return {
            "cycle_id": inputs.cycle_id,
            "anti_pattern_list_version": inputs.anti_pattern_state.version,
            "state_hash_before": state_hash(inputs.anti_pattern_state),
            "state_hash_after": state_hash(outputs.anti_pattern_state),
            "config_hash": config_hash(inputs.config),
            "decisions": [decision.as_dict() for decision in outputs.decisions],
            "accepted_rule_ids": [rule.rule_id for rule in outputs.accepted_rules],
            "rejected_rule_ids": [
                decision.rule_id for decision in outputs.decisions if decision.result == "reject"
            ],
        }

    def _serialize_output(self, outputs: OriginalityOutput) -> bytes:
        return canonicalize(outputs.as_dict())

    def _deserialize_output(self, data: bytes) -> OriginalityOutput:
        raw = json.loads(data.decode("utf-8"))
        return OriginalityOutput(
            accepted_rules=tuple(load_rule(item) for item in raw["accepted_rules"]),
            decisions=tuple(
                OriginalityDecision(
                    rule_id=str(item["rule_id"]),
                    result=str(item["result"]),
                    matched_anti_pattern=item["matched_anti_pattern"],
                    anti_pattern_list_version=str(item["anti_pattern_list_version"]),
                    state_hash=str(item["state_hash"]),
                    config_hash=str(item["config_hash"]),
                    grounding_hash=str(item["grounding_hash"]),
                    stats_hash=str(item["stats_hash"]),
                    trace_hash=str(item["trace_hash"]),
                )
                for item in raw["decisions"]
            ),
            anti_pattern_state=AntiPatternListState.from_dict(raw["anti_pattern_state"]),
        )
