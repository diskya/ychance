from __future__ import annotations

import json
from pathlib import Path

import pytest

from audit import AuditLog
from council_llm import (
    CouncilInput,
    CouncilMember,
    CouncilParseError,
    CouncilVoterStage,
    build_full_prompt,
    build_screening_prompt,
    cache_key_hash,
    parse_full_vote,
    parse_screening_vote,
    validation_report_hash,
)
from pipeline import ArtifactStore
from represent.llm_client import LLMResponse
from rule import finalize_rule
from tests.rule.fixtures.helpers import context_price_le, exit_after, rule_body, tick
from validate import (
    ChallengerReport,
    PartitionResult,
    RobustnessItem,
    RobustnessProfile,
    UtilityDistribution,
    ValidateFold,
    ValidateWindow,
    ValidationReport,
)


class RecordingLLMClient:
    def __init__(self, responses: list[LLMResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[dict] = []

    def complete(self, *, model: str, prompt: str, params: dict) -> LLMResponse:
        self.calls.append({"model": model, "prompt": prompt, "params": dict(params)})
        if not self.responses:
            raise AssertionError("unexpected LLM call")
        return self.responses.pop(0)


@pytest.fixture
def audit(tmp_path: Path) -> AuditLog:
    return AuditLog(tmp_path / "audit")


@pytest.fixture
def artifacts(tmp_path: Path):
    store = ArtifactStore(tmp_path / "artifacts")
    try:
        yield store
    finally:
        store.close()


def _records(log: AuditLog) -> list[dict]:
    records: list[dict] = []
    for path in sorted(log._root.glob("*.jsonl")):
        for line in path.read_text().splitlines():
            if line:
                records.append(json.loads(line))
    return records


def _response(text: str, *, input_tokens: int = 10, output_tokens: int = 3) -> LLMResponse:
    return LLMResponse(
        text=text,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        raw_json={"text": text},
    )


def _member(member_id: str = "member-a", version: str = "family-a-v1") -> CouncilMember:
    return CouncilMember(
        member_id=member_id,
        member_version=version,
        vendor_family=f"{member_id}-family",
        model=f"{member_id}-model",
        input_cost_per_1k_usd=0.2,
        output_cost_per_1k_usd=0.4,
    )


def _rule():
    return finalize_rule(
        rule_body(
            context=context_price_le(99),
            exit=exit_after(1),
            horizon_bars=4,
        )
    )


def _report(rule) -> ValidationReport:
    train = ValidateWindow(tick(6).isoformat(), tick(12).isoformat())
    gap = ValidateWindow(tick(13).isoformat(), tick(13).isoformat())
    holdout = ValidateWindow(tick(14).isoformat(), tick(20).isoformat())
    return ValidationReport(
        rule_id=rule.rule_id,
        validate_protocol_version="test-validate",
        result="pass",
        validate_window=ValidateWindow(tick(6).isoformat(), tick(20).isoformat()),
        windows_used=(
            ValidateFold(
                fold_id="fold-0",
                train_window=train,
                gap_window=gap,
                holdout_window=holdout,
                inner_windows=(train,),
            ),
        ),
        disjointness_proof={"checked_by": "synthetic"},
        utility_distribution=UtilityDistribution(
            construction="synthetic",
            samples=(0.04, 0.05, 0.06),
        ),
        challenger_reports=(
            ChallengerReport(
                challenger_id="inactive",
                utility_distribution=UtilityDistribution(
                    construction="synthetic",
                    samples=(0.0, 0.01, 0.02),
                ),
                partition_results=(
                    PartitionResult(
                        partition_id="partition_0",
                        dominance_order=1,
                        dominance_grid=({"threshold": 0.0, "candidate": 0.9},),
                        dominates=True,
                    ),
                ),
                dominance_fraction=1.0,
                result="pass",
            ),
        ),
        robustness_profile=RobustnessProfile(
            items=(
                RobustnessItem(
                    perturbation_id="small_shift",
                    utility_distribution=UtilityDistribution(
                        construction="synthetic",
                        samples=(0.03, 0.04),
                    ),
                ),
            )
        ),
        partition_profile={"active_partitions": ["partition_0"]},
        config_hash="c" * 64,
    )


def _stage(
    *,
    artifacts,
    audit,
    client: RecordingLLMClient,
    member: CouncilMember | None = None,
) -> CouncilVoterStage:
    return CouncilVoterStage(
        member=member or _member(),
        llm_client=client,
        artifacts=artifacts,
        audit=audit,
    )


def test_prompt_redacts_propose_rationale_and_model_identity() -> None:
    rule = _rule()
    report = _report(rule).as_dict()
    report["free_text_rationale"] = "SECRET_PROPOSE_ARGUMENT"
    report["model_version"] = "SECRET_PROPOSER_MODEL"
    raw_slice = {
        "rows": [{"x": 1}],
        "candidate_audits": [
            {
                "free_text_rationale": "SECRET_NESTED_ARGUMENT",
                "model_id": "SECRET_NESTED_MODEL",
            }
        ],
        "llm_calls": [{"model_version": "SECRET_LLM_CALL_MODEL"}],
    }

    screening = build_screening_prompt(
        rule=rule,
        validate_report=report,
        raw_slice=raw_slice,
    )
    full = build_full_prompt(rule=rule, validate_report=report, raw_slice=raw_slice)

    for prompt in (screening, full):
        assert "SECRET_PROPOSE_ARGUMENT" not in prompt
        assert "SECRET_PROPOSER_MODEL" not in prompt
        assert "SECRET_NESTED_ARGUMENT" not in prompt
        assert "SECRET_NESTED_MODEL" not in prompt
        assert "SECRET_LLM_CALL_MODEL" not in prompt
        assert rule.rule_id in prompt


def test_vote_parsing_accepts_json_and_rejects_ambiguous_text() -> None:
    assert parse_screening_vote('{"screening_vote":"need_full_review"}') == "need full review"
    assert parse_screening_vote("APPROVE") == "approve"

    parsed = parse_full_vote(
        '{"vote":"reject","rationale":"missing evidence","citations":["utility_distribution"]}'
    )
    assert parsed.vote == "reject"
    assert parsed.rationale == "missing evidence"
    assert parsed.citations == ("utility_distribution",)

    with pytest.raises(CouncilParseError):
        parse_screening_vote("approve then reject")


def test_screening_vote_does_not_trigger_full_review(artifacts, audit) -> None:
    rule = _rule()
    report = _report(rule)
    client = RecordingLLMClient([_response('{"screening_vote":"approve"}')])
    result = _stage(artifacts=artifacts, audit=audit, client=client).run(
        CouncilInput(
            cycle_id="cycle-1",
            rule=rule,
            validate_report=report,
            raw_slice={"rows": [{"t": tick(14).isoformat(), "value": 1.0}]},
        )
    )

    assert result.outputs.vote == "approve"
    assert result.outputs.rationale == ""
    assert result.outputs.citations == ()
    assert result.outputs.query_mode == "screening_only"
    assert result.outputs.prompt_hashes["full"] is None
    assert len(client.calls) == 1


def test_need_full_review_triggers_full_rationale_generation(artifacts, audit) -> None:
    rule = _rule()
    report = _report(rule)
    client = RecordingLLMClient(
        [
            _response('{"screening_vote":"need full review"}'),
            _response(
                '{"vote":"reject","rationale":"robustness is insufficient",'
                '"citations":["robustness_profile.items[0]"]}',
                output_tokens=9,
            ),
        ]
    )
    result = _stage(artifacts=artifacts, audit=audit, client=client).run(
        CouncilInput(
            cycle_id="cycle-1",
            rule=rule,
            validate_report=report,
            raw_slice={"rows": [{"t": tick(15).isoformat(), "value": 2.0}]},
        )
    )

    assert result.outputs.vote == "reject"
    assert result.outputs.rationale == "robustness is insufficient"
    assert result.outputs.citations == ("robustness_profile.items[0]",)
    assert result.outputs.query_mode == "full_review"
    assert len(client.calls) == 2


def test_cache_key_uses_rule_report_and_member_version_only(artifacts, audit) -> None:
    rule = _rule()
    report = _report(rule)
    member = _member(version="stable-member-version")
    client = RecordingLLMClient([_response('{"screening_vote":"approve"}')])
    stage = _stage(artifacts=artifacts, audit=audit, client=client, member=member)

    first = CouncilInput(
        cycle_id="cycle-1",
        rule=rule,
        validate_report=report,
        raw_slice={"rows": [{"value": 1}]},
    )
    second = CouncilInput(
        cycle_id="cycle-1",
        rule=rule,
        validate_report=report,
        raw_slice={"rows": [{"value": 999}]},
    )

    assert stage.fingerprint(first) == stage.fingerprint(second)
    assert stage.fingerprint(first)[0] == cache_key_hash(
        rule_hash=rule.rule_id,
        validate_report_hash=validation_report_hash(report),
        member_version=member.member_version,
    )

    miss = stage.run(first)
    hit = stage.run(first)

    assert miss.cache_hit is False
    assert hit.cache_hit is True
    assert miss.output_hash == hit.output_hash
    assert len(client.calls) == 1

    council_records = [record for record in _records(audit) if record["category"] == "Council"]
    assert [record["cache_status"] for record in council_records] == ["miss", "hit"]
    assert council_records[1]["llm_cost"] == 0.0


def test_audit_payload_shape_for_full_vote(artifacts, audit) -> None:
    rule = _rule()
    report = _report(rule)
    client = RecordingLLMClient(
        [
            _response('{"screening_vote":"need full review"}'),
            _response(
                '{"vote":"approve","rationale":"distribution clears the gate",'
                '"citations":["utility_distribution.samples","challenger_reports[0]"]}',
                input_tokens=12,
                output_tokens=11,
            ),
        ]
    )
    result = _stage(artifacts=artifacts, audit=audit, client=client).run(
        CouncilInput(
            cycle_id="cycle-1",
            rule=rule,
            validate_report=report,
            raw_slice={"rows": [{"t": tick(16).isoformat(), "value": 3.0}]},
        )
    )

    records = [record for record in _records(audit) if record["category"] == "Council"]
    assert len(records) == 1
    record = records[0]
    assert record["stage"] == "Council"
    assert record["rule_id"] == rule.rule_id
    assert record["member_id"] == "member-a"
    assert record["member_version"] == "family-a-v1"
    assert record["cache_status"] == "miss"
    assert record["vote"] == "approve"
    assert record["rationale_hash"] == result.outputs.rationale_hash
    assert record["citations"] == [
        "utility_distribution.samples",
        "challenger_reports[0]",
    ]
    assert set(record["prompt_hashes"]) == {"screening", "full"}
    assert set(record["response_hashes"]) == {"screening", "full"}
    assert [trace["phase"] for trace in record["llm_traces"]] == ["screening", "full"]
    assert record["cost_usage"]["llm_usd"] == record["llm_cost"]
    assert record["llm_cost"] > 0.0


def test_integration_with_synthetic_validation_report(artifacts, audit) -> None:
    rule = _rule()
    report = _report(rule)
    client = RecordingLLMClient(
        [
            _response('{"screening_vote":"need full review"}'),
            _response(
                json.dumps(
                    {
                        "vote": "approve",
                        "rationale": "validated distribution dominates the challenger",
                        "citations": [
                            "validate_report.utility_distribution.samples",
                            "validate_report.challenger_reports[0].result",
                        ],
                    }
                )
            ),
        ]
    )

    vote = _stage(artifacts=artifacts, audit=audit, client=client).run(
        CouncilInput(
            cycle_id="cycle-integration",
            rule=rule,
            validate_report=report,
            raw_slice={"window": [tick(14).isoformat(), tick(20).isoformat()]},
        )
    ).outputs

    assert vote.as_tuple() == (
        "approve",
        "validated distribution dominates the challenger",
        (
            "validate_report.utility_distribution.samples",
            "validate_report.challenger_reports[0].result",
        ),
    )
    assert vote.validate_report_hash == validation_report_hash(report)
