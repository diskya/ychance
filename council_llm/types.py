from __future__ import annotations

import dataclasses
import hashlib
from dataclasses import dataclass, field
from typing import Any, Mapping

from audit import canonicalize
from rule import Rule, load_rule
from validate import ValidationReport


APPROVE = "approve"
REJECT = "reject"
NEED_FULL_REVIEW = "need full review"
FINAL_VOTES = frozenset({APPROVE, REJECT})
SCREENING_VOTES = frozenset({APPROVE, REJECT, NEED_FULL_REVIEW})


@dataclass(frozen=True)
class CouncilMember:
    member_id: str
    member_version: str
    vendor_family: str
    model: str
    screening_params: dict[str, Any] = field(
        default_factory=lambda: {"temperature": 0, "max_tokens": 32}
    )
    full_params: dict[str, Any] = field(
        default_factory=lambda: {"temperature": 0, "max_tokens": 512}
    )
    input_cost_per_1k_usd: float = 0.0
    output_cost_per_1k_usd: float = 0.0

    def __post_init__(self) -> None:
        for field_name in ("member_id", "member_version", "vendor_family", "model"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"{field_name} must be a non-empty string")
        _assert_json_mapping("screening_params", self.screening_params)
        _assert_json_mapping("full_params", self.full_params)
        if self.input_cost_per_1k_usd < 0 or self.output_cost_per_1k_usd < 0:
            raise ValueError("token costs must be non-negative")


@dataclass(frozen=True)
class CouncilInput:
    cycle_id: str
    rule: Rule | Mapping[str, Any]
    validate_report: ValidationReport | Mapping[str, Any]
    raw_slice: Any

    def __post_init__(self) -> None:
        if not isinstance(self.cycle_id, str) or not self.cycle_id:
            raise ValueError("cycle_id must be a non-empty string")
        object.__setattr__(
            self,
            "rule",
            self.rule if isinstance(self.rule, Rule) else load_rule(self.rule),
        )
        if not isinstance(self.validate_report, (ValidationReport, Mapping)):
            raise TypeError("validate_report must be a ValidationReport or mapping")


@dataclass(frozen=True)
class CouncilLLMTrace:
    phase: str
    model: str
    prompt_hash: str
    params_hash: str
    response_hash: str
    input_tokens: int
    output_tokens: int
    llm_cost: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "model": self.model,
            "prompt_hash": self.prompt_hash,
            "params_hash": self.params_hash,
            "response_hash": self.response_hash,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "llm_cost": self.llm_cost,
        }


@dataclass(frozen=True)
class CouncilVote:
    rule_id: str
    member_id: str
    member_version: str
    vendor_family: str
    vote: str
    rationale: str
    citations: tuple[str, ...]
    rationale_hash: str
    screening_decision: str
    query_mode: str
    rule_hash: str
    validate_report_hash: str
    raw_slice_hash: str
    cache_key_hash: str
    prompt_hashes: dict[str, str | None]
    response_hashes: dict[str, str | None]
    llm_traces: tuple[CouncilLLMTrace, ...]

    def as_tuple(self) -> tuple[str, str, tuple[str, ...]]:
        return self.vote, self.rationale, self.citations


def content_hash(payload: Any) -> str:
    return hashlib.sha256(canonicalize(to_jsonable(payload))).hexdigest()


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def rule_content_hash(rule: Rule | Mapping[str, Any]) -> str:
    normalized = rule if isinstance(rule, Rule) else load_rule(rule)
    return normalized.rule_id


def validation_report_hash(report: ValidationReport | Mapping[str, Any]) -> str:
    return content_hash(validation_report_payload(report))


def raw_slice_hash(raw_slice: Any) -> str:
    return content_hash(raw_slice)


def cache_key_hash(
    *,
    rule_hash: str,
    validate_report_hash: str,
    member_version: str,
) -> str:
    return content_hash(
        {
            "rule_hash": rule_hash,
            "validate_report_hash": validate_report_hash,
            "member_version": member_version,
        }
    )


def validation_report_payload(report: ValidationReport | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(report, ValidationReport):
        return report.as_dict()
    return dict(report)


def rule_payload(rule: Rule | Mapping[str, Any]) -> dict[str, Any]:
    normalized = rule if isinstance(rule, Rule) else load_rule(rule)
    return normalized.to_dict()


def to_jsonable(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        if hasattr(value, "as_dict"):
            return to_jsonable(value.as_dict())
        return to_jsonable(dataclasses.asdict(value))
    if isinstance(value, Mapping):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(item) for item in value]
    if isinstance(value, (bytes, bytearray, memoryview)):
        data = bytes(value)
        return {
            "bytes_sha256": hashlib.sha256(data).hexdigest(),
            "bytes_size": len(data),
        }
    return value


def _assert_json_mapping(name: str, value: Mapping[str, Any]) -> None:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be a mapping")
    canonicalize(to_jsonable(dict(value)))
