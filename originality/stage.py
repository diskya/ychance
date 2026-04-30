from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Any

from pattern import Pattern, load_pattern
from pipeline import CostCeiling, InvariantViolation, Stage, StageContext

from .fingerprint import PatternFingerprint, build_pattern_fingerprint, digest_jsonable
from .matchers import AntiPatternDecision, AntiPatternList


class OriginalityInputError(ValueError):
    """Raised when the Originality stage cannot load its Pattern input."""


@dataclass(frozen=True)
class OriginalityInput:
    cycle_id: str
    pattern_artifact_hash: str | None = None
    pattern: dict[str, Any] | None = None
    observation_fingerprint_hash: str | None = None


@dataclass(frozen=True)
class OriginalityResult:
    pattern_id: str
    result: str
    matched_anti_pattern: str | None
    anti_pattern_list_version: str
    fingerprint_hash: str
    matcher_id: str | None
    match_hash: str | None


class OriginalityFilter(Stage):
    name = "originality_filter"
    version = "1"
    audit_stage = "Originality"
    cost_ceiling = CostCeiling(compute_usd=1.0, llm_usd=0.0, data_reads=0)
    InputType = OriginalityInput
    OutputType = OriginalityResult

    def __init__(
        self,
        *,
        anti_patterns: AntiPatternList | None = None,
        artifacts,
        audit,
        access=None,
        writer=None,
    ) -> None:
        super().__init__(artifacts=artifacts, audit=audit, access=access, writer=writer)
        self._anti_patterns = anti_patterns or AntiPatternList()

    @property
    def anti_patterns(self) -> AntiPatternList:
        return self._anti_patterns

    def fingerprint(self, inputs: Any) -> tuple[str, str]:
        inputs_hash = digest_jsonable(
            {
                "inputs": _to_jsonable(inputs),
                "anti_pattern_list_version": self._anti_patterns.version,
            }
        )
        fp = digest_jsonable(
            {
                "name": self.name,
                "version": self.version,
                "inputs_hash": inputs_hash,
            }
        )
        return inputs_hash, fp

    def compute(self, inputs: OriginalityInput, ctx: StageContext) -> OriginalityResult:
        del ctx
        pattern = self._load_input_pattern(inputs)
        fingerprint = build_pattern_fingerprint(
            pattern,
            observation_fingerprint_hash=inputs.observation_fingerprint_hash,
        )
        decision = self._anti_patterns.decide(fingerprint)
        return _to_result(fingerprint, decision)

    def invariant(self, inputs: OriginalityInput, outputs: OriginalityResult) -> None:
        pattern = self._load_input_pattern(inputs)
        if outputs.pattern_id != pattern.pattern_id:
            raise InvariantViolation("Originality result pattern_id does not match input")
        if outputs.result not in {"pass", "reject"}:
            raise InvariantViolation("Originality result must be pass or reject")
        if outputs.result == "pass" and outputs.matched_anti_pattern is not None:
            raise InvariantViolation("passed Originality result cannot have a match")
        if outputs.result == "reject" and outputs.matched_anti_pattern is None:
            raise InvariantViolation("rejected Originality result requires a match")
        if outputs.anti_pattern_list_version != self._anti_patterns.version:
            raise InvariantViolation("Originality list version mismatch")
        if len(outputs.fingerprint_hash) != 64:
            raise InvariantViolation("Originality fingerprint_hash must be sha256 hex")

    def audit_extra_payload(
        self,
        inputs: OriginalityInput,
        outputs: OriginalityResult,
        ctx: StageContext,
        *,
        inputs_hash: str,
        output_hash: str,
    ) -> dict[str, Any]:
        del inputs, ctx, inputs_hash, output_hash
        return {
            "kind": "OriginalityRecord",
            "pattern_id": outputs.pattern_id,
            "result": outputs.result,
            "matched_anti_pattern": outputs.matched_anti_pattern,
            "anti_pattern_list_version": outputs.anti_pattern_list_version,
            "fingerprint_hash": outputs.fingerprint_hash,
            "matcher_id": outputs.matcher_id,
            "match_hash": outputs.match_hash,
            "anti_pattern_count": len(self._anti_patterns.entries),
        }

    def _load_input_pattern(self, inputs: OriginalityInput) -> Pattern:
        if inputs.pattern is not None and inputs.pattern_artifact_hash is not None:
            raise OriginalityInputError(
                "provide either pattern or pattern_artifact_hash, not both"
            )
        if inputs.pattern is not None:
            return load_pattern(inputs.pattern)
        if inputs.pattern_artifact_hash is None:
            raise OriginalityInputError("OriginalityInput requires a Pattern")
        return load_pattern(self._artifacts.get(inputs.pattern_artifact_hash))


def _to_result(
    fingerprint: PatternFingerprint,
    decision: AntiPatternDecision,
) -> OriginalityResult:
    return OriginalityResult(
        pattern_id=fingerprint.pattern_id,
        result=decision.result,
        matched_anti_pattern=decision.matched_anti_pattern,
        anti_pattern_list_version=decision.anti_pattern_list_version,
        fingerprint_hash=fingerprint.fingerprint_hash,
        matcher_id=decision.matcher_id,
        match_hash=decision.match_hash,
    )


def _to_jsonable(obj: Any) -> Any:
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {k: _to_jsonable(v) for k, v in dataclasses.asdict(obj).items()}
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(v) for v in obj]
    return obj
