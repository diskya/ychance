from __future__ import annotations

import json
from pathlib import Path

import pytest

from audit import AuditLog
from council_decide import (
    DECISION_RULE_HASH,
    DECISION_RULE_ID,
    CouncilDecisionInput,
    CouncilDecisionStage,
    IndependenceClassification,
)
from council_llm import CouncilVote
from council_llm.types import text_hash
from pipeline import ArtifactStore


RULE_ID = "rule-under-council"
RULE_HASH = "a" * 64
VALIDATE_REPORT_HASH = "b" * 64


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


def _vote(
    member_id: str,
    vote: str,
    rationale: str = "",
    *,
    member_version: str | None = None,
    citations: tuple[str, ...] = (),
) -> CouncilVote:
    return CouncilVote(
        rule_id=RULE_ID,
        member_id=member_id,
        member_version=member_version or f"{member_id}-v1",
        vendor_family=f"{member_id}-family",
        vote=vote,
        rationale=rationale,
        citations=citations,
        rationale_hash=text_hash(rationale),
        screening_decision=vote,
        query_mode="screening_only",
        rule_hash=RULE_HASH,
        validate_report_hash=VALIDATE_REPORT_HASH,
        raw_slice_hash="c" * 64,
        cache_key_hash="d" * 64,
        prompt_hashes={"screening": "e" * 64, "full": None},
        response_hashes={"screening": "f" * 64, "full": None},
        llm_traces=(),
    )


def _classification(**groups: str) -> IndependenceClassification:
    return IndependenceClassification(
        classification_id="indep-test-v1",
        member_groups=groups,
    )


def _stage(artifacts, audit) -> CouncilDecisionStage:
    return CouncilDecisionStage(artifacts=artifacts, audit=audit)


def test_two_independent_approvals_approve(artifacts, audit) -> None:
    result = _stage(artifacts, audit).run(
        CouncilDecisionInput(
            cycle_id="cycle-1",
            votes=(
                _vote("member-a", "approve"),
                _vote("member-b", "approve"),
            ),
            independence=_classification(**{"member-a": "group-a", "member-b": "group-b"}),
        )
    )

    decision = result.outputs
    assert decision.decision == "approve"
    assert decision.route == "Graduate"
    assert decision.approval_voice_count == 2
    assert decision.independent_approver_group_ids == ("group-a", "group-b")
    assert decision.independent_approver_member_ids == ("member-a", "member-b")
    assert decision.blocking_rationales == ()
    assert decision.rejection_reasons == ()


def test_independent_reject_blocks_approval(artifacts, audit) -> None:
    result = _stage(artifacts, audit).run(
        CouncilDecisionInput(
            cycle_id="cycle-1",
            votes=(
                _vote("member-a", "approve"),
                _vote("member-b", "approve"),
                _vote(
                    "member-c",
                    "reject",
                    "validate distribution does not support graduation",
                    citations=("utility_distribution.samples",),
                ),
            ),
            independence=_classification(
                **{
                    "member-a": "group-a",
                    "member-b": "group-b",
                    "member-c": "group-c",
                }
            ),
        )
    )

    decision = result.outputs
    assert decision.decision == "reject"
    assert decision.route == "Propose"
    assert decision.approval_voice_count == 2
    assert decision.rejection_reasons == ("independent_reject",)
    assert len(decision.blocking_rationales) == 1
    blocker = decision.blocking_rationales[0]
    assert blocker.independent_group_id == "group-c"
    assert blocker.member_id == "member-c"
    assert blocker.rationale == "validate distribution does not support graduation"


def test_collapsed_pair_counts_as_one_voice(artifacts, audit) -> None:
    result = _stage(artifacts, audit).run(
        CouncilDecisionInput(
            cycle_id="cycle-1",
            votes=(
                _vote("member-a", "approve"),
                _vote("member-b", "approve"),
            ),
            independence=_classification(**{"member-a": "group-collapsed", "member-b": "group-collapsed"}),
        )
    )

    decision = result.outputs
    assert decision.decision == "reject"
    assert decision.approval_voice_count == 1
    assert decision.independent_approver_group_ids == ("group-collapsed",)
    assert decision.independent_approver_member_ids == ("member-a",)
    assert decision.rejection_reasons == ("insufficient_independent_approvals",)
    assert decision.independent_groups[0].member_ids == ("member-a", "member-b")
    assert decision.independent_groups[0].voice_count == 1


def test_collapsed_group_reject_blocks_group_voice(artifacts, audit) -> None:
    result = _stage(artifacts, audit).run(
        CouncilDecisionInput(
            cycle_id="cycle-1",
            votes=(
                _vote("member-a", "approve"),
                _vote("member-b", "reject", "same-group disagreement blocks"),
                _vote("member-c", "approve"),
            ),
            independence=_classification(
                **{
                    "member-a": "group-collapsed",
                    "member-b": "group-collapsed",
                    "member-c": "group-c",
                }
            ),
        )
    )

    decision = result.outputs
    assert decision.decision == "reject"
    assert decision.approval_voice_count == 1
    collapsed = {
        group.independent_group_id: group for group in decision.independent_groups
    }["group-collapsed"]
    assert collapsed.vote == "reject"
    assert collapsed.reject_member_ids == ("member-b",)
    assert decision.rejection_reasons == (
        "independent_reject",
        "insufficient_independent_approvals",
    )


def test_insufficient_independent_approvals_rejects(artifacts, audit) -> None:
    result = _stage(artifacts, audit).run(
        CouncilDecisionInput(
            cycle_id="cycle-1",
            votes=(
                _vote("member-a", "approve"),
                _vote("member-b", "reject", "not enough support"),
            ),
            independence=_classification(**{"member-a": "group-a", "member-b": "group-b"}),
        )
    )

    decision = result.outputs
    assert decision.decision == "reject"
    assert decision.approval_voice_count == 1
    assert decision.rejection_reasons == (
        "independent_reject",
        "insufficient_independent_approvals",
    )


def test_audit_payload_shape_and_redaction(artifacts, audit) -> None:
    vote_mapping = {
        "rule_id": RULE_ID,
        "rule_hash": RULE_HASH,
        "validate_report_hash": VALIDATE_REPORT_HASH,
        "member_id": "member-a",
        "member_version": "member-a-v1",
        "vote": "reject",
        "rationale": "missing disjoint evidence",
        "rationale_hash": text_hash("missing disjoint evidence"),
        "citations": ["disjointness_proof"],
        "free_text_rationale": "SECRET_PROPOSE_ARGUMENT",
        "model_version": "SECRET_PROPOSER_MODEL",
        "record_hash": "1" * 64,
    }
    result = _stage(artifacts, audit).run(
        CouncilDecisionInput(
            cycle_id="cycle-audit",
            votes=(vote_mapping, _vote("member-b", "approve")),
            independence={
                "classification_id": "indep-test-v1",
                "member_groups": {"member-a": "group-a", "member-b": "group-b"},
            },
        )
    )

    records = [record for record in _records(audit) if record["category"] == "Council"]
    assert len(records) == 1
    record = records[0]
    assert record["stage"] == "Council"
    assert record["stage_name"] == "council_decision_stage"
    assert record["rule_id"] == RULE_ID
    assert record["rule_hash"] == RULE_HASH
    assert record["validate_report_hash"] == VALIDATE_REPORT_HASH
    assert record["decision"] == "reject"
    assert record["decision_rule_id"] == DECISION_RULE_ID
    assert record["decision_rule_hash"] == DECISION_RULE_HASH
    assert record["independence_classification_id"] == "indep-test-v1"
    assert record["independence_classification_hash"] == result.outputs.independence_classification_hash
    assert [item["member_id"] for item in record["member_votes"]] == ["member-a", "member-b"]
    assert record["member_votes"][0]["vote_record_hash"] == "1" * 64
    assert record["independent_groups"][0]["independent_group_id"] == "group-a"
    assert record["blocking_rationales"] == [
        {
            "independent_group_id": "group-a",
            "member_id": "member-a",
            "member_version": "member-a-v1",
            "rationale": "missing disjoint evidence",
            "rationale_hash": text_hash("missing disjoint evidence"),
            "citations": ["disjointness_proof"],
        }
    ]
    serialized = json.dumps(record)
    assert "SECRET_PROPOSE_ARGUMENT" not in serialized
    assert "SECRET_PROPOSER_MODEL" not in serialized


def test_cache_hit_has_no_second_audit_record(artifacts, audit) -> None:
    stage = _stage(artifacts, audit)
    inputs = CouncilDecisionInput(
        cycle_id="cycle-cache",
        votes=(_vote("member-a", "approve"), _vote("member-b", "approve")),
        independence=_classification(**{"member-a": "group-a", "member-b": "group-b"}),
    )

    miss = stage.run(inputs)
    hit = stage.run(inputs)

    assert miss.cache_hit is False
    assert hit.cache_hit is True
    assert miss.output_hash == hit.output_hash
    assert len([record for record in _records(audit) if record["category"] == "Council"]) == 1
