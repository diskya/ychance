from __future__ import annotations

from typing import Any, Mapping

from audit import canonicalize
from rule import Rule
from validate import ValidationReport

from .types import (
    NEED_FULL_REVIEW,
    rule_payload,
    to_jsonable,
    validation_report_payload,
)


_REDACT_KEYS = frozenset(
    {
        "adjudicate_model_id",
        "candidate_audits",
        "draft_model_id",
        "free_text_rationale",
        "llm_calls",
        "model",
        "model_id",
        "model_version",
        "proposal_rationale",
        "propose_model",
        "propose_rationale",
        "proposer",
        "proposer_model",
        "proposing_model",
        "rationale",
    }
)


def sanitized_vote_payload(
    *,
    rule: Rule | Mapping[str, Any],
    validate_report: ValidationReport | Mapping[str, Any],
    raw_slice: Any,
) -> dict[str, Any]:
    return {
        "rule": _redact(rule_payload(rule)),
        "validate_report": _redact(validation_report_payload(validate_report)),
        "raw_slice": _redact(to_jsonable(raw_slice)),
    }


def build_screening_prompt(
    *,
    rule: Rule | Mapping[str, Any],
    validate_report: ValidationReport | Mapping[str, Any],
    raw_slice: Any,
) -> str:
    payload = _canonical_json(
        sanitized_vote_payload(
            rule=rule,
            validate_report=validate_report,
            raw_slice=raw_slice,
        )
    )
    return (
        "Council screening query.\n"
        "Use only the sanitized rule, validation report, and raw slice below. "
        "The proposal argument and proposer identity are deliberately withheld.\n"
        "Return only JSON with this shape: "
        '{"screening_vote":"approve|reject|need full review"}.\n'
        f"Use \"{NEED_FULL_REVIEW}\" when a short check is not enough.\n"
        "SANITIZED_INPUT_JSON:\n"
        f"{payload}\n"
    )


def build_full_prompt(
    *,
    rule: Rule | Mapping[str, Any],
    validate_report: ValidationReport | Mapping[str, Any],
    raw_slice: Any,
) -> str:
    payload = _canonical_json(
        sanitized_vote_payload(
            rule=rule,
            validate_report=validate_report,
            raw_slice=raw_slice,
        )
    )
    return (
        "Council full review query.\n"
        "Use only the sanitized rule, validation report, and raw slice below. "
        "The proposal argument and proposer identity are deliberately withheld.\n"
        "Return only JSON with this shape: "
        '{"vote":"approve|reject","rationale":"text","citations":["path or slice reference"]}.\n'
        "Citations must refer to fields in the validation report or raw slice.\n"
        "SANITIZED_INPUT_JSON:\n"
        f"{payload}\n"
    )


def _redact(value: Any) -> Any:
    if isinstance(value, Mapping):
        clean: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if _redact_key(key_text):
                continue
            clean[key_text] = _redact(item)
        return clean
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, tuple):
        return [_redact(item) for item in value]
    return value


def _redact_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_").replace(" ", "_")
    return normalized in _REDACT_KEYS


def _canonical_json(payload: Any) -> str:
    return canonicalize(payload).decode("utf-8")
