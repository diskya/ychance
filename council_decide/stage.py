from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from typing import Any

from audit import canonicalize
from council_llm.types import APPROVE, REJECT
from pipeline import CostCeiling, InvariantViolation, Stage, StageContext, StageResult

from .types import (
    DECISION_APPROVE,
    DECISION_REJECT,
    DECISION_RULE_HASH,
    DECISION_RULE_ID,
    DECISION_RULE_SPEC,
    BlockingRationale,
    CouncilDecision,
    CouncilDecisionInput,
    CouncilMemberVote,
    IndependenceClassification,
    IndependentGroupDecision,
    content_hash,
)


class CouncilDecisionStage(Stage):
    name = "council_decision_stage"
    version = "1"
    audit_stage = "Council"
    cost_ceiling = CostCeiling(compute_usd=0.1, llm_usd=0.0, data_reads=0)
    InputType = CouncilDecisionInput
    OutputType = CouncilDecision

    def run(self, inputs: Any, *, envelope: dict | None = None) -> StageResult:
        if isinstance(inputs, CouncilDecisionInput):
            env = {"cycle_id": inputs.cycle_id, "rule_id": inputs.rule_id}
            env.update(
                {
                    key: value
                    for key, value in (envelope or {}).items()
                    if key in {"cycle_id", "rule_id", "m2a_id"}
                }
            )
        else:
            env = dict(envelope or {})
        return super().run(inputs, envelope=env)

    def fingerprint(self, inputs: Any) -> tuple[str, str]:
        if not isinstance(inputs, CouncilDecisionInput):
            return super().fingerprint(inputs)
        inputs_hash = content_hash(inputs.as_dict())
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

    def compute(self, inputs: CouncilDecisionInput, ctx: StageContext) -> CouncilDecision:
        ctx.charge_compute(0.000001 * len(inputs.votes))
        classification = inputs.independence
        assert isinstance(classification, IndependenceClassification)

        grouped_votes: dict[str, list[CouncilMemberVote]] = defaultdict(list)
        for vote in inputs.votes:
            grouped_votes[classification.member_groups[vote.member_id]].append(vote)

        group_decisions: list[IndependentGroupDecision] = []
        blocking_rationales: list[BlockingRationale] = []
        approver_group_ids: list[str] = []
        approver_member_ids: list[str] = []
        member_summaries: list[dict[str, Any]] = []

        for group_id in sorted(grouped_votes):
            votes = sorted(grouped_votes[group_id], key=lambda item: item.member_id)
            approve_ids = tuple(vote.member_id for vote in votes if vote.vote == APPROVE)
            reject_votes = tuple(vote for vote in votes if vote.vote == REJECT)
            reject_ids = tuple(vote.member_id for vote in reject_votes)
            group_vote = REJECT if reject_votes else APPROVE

            group_decisions.append(
                IndependentGroupDecision(
                    independent_group_id=group_id,
                    member_ids=tuple(vote.member_id for vote in votes),
                    vote=group_vote,
                    approve_member_ids=approve_ids,
                    reject_member_ids=reject_ids,
                )
            )
            if group_vote == APPROVE:
                approver_group_ids.append(group_id)
                approver_member_ids.append(approve_ids[0])
            else:
                for vote in reject_votes:
                    blocking_rationales.append(
                        BlockingRationale(
                            independent_group_id=group_id,
                            member_id=vote.member_id,
                            member_version=vote.member_version,
                            rationale=vote.rationale,
                            rationale_hash=vote.rationale_hash,
                            citations=vote.citations,
                        )
                    )

            for vote in votes:
                member_summaries.append(vote.summary(group_id))

        rejection_reasons: list[str] = []
        if blocking_rationales:
            rejection_reasons.append("independent_reject")
        if len(approver_group_ids) < DECISION_RULE_SPEC["minimum_independent_approve_groups"]:
            rejection_reasons.append("insufficient_independent_approvals")

        decision = DECISION_REJECT if rejection_reasons else DECISION_APPROVE
        return CouncilDecision(
            rule_id=inputs.rule_id,
            rule_hash=inputs.rule_hash,
            validate_report_hash=inputs.validate_report_hash,
            decision=decision,
            route="Graduate" if decision == DECISION_APPROVE else "Propose",
            decision_rule_id=DECISION_RULE_ID,
            decision_rule_hash=DECISION_RULE_HASH,
            independence_classification_id=classification.classification_id,
            independence_classification_hash=classification.classification_hash,
            member_votes=tuple(sorted(member_summaries, key=lambda item: item["member_id"])),
            independent_groups=tuple(group_decisions),
            independent_approver_group_ids=tuple(approver_group_ids),
            independent_approver_member_ids=tuple(approver_member_ids),
            approval_voice_count=len(approver_group_ids),
            blocking_rationales=tuple(
                sorted(
                    blocking_rationales,
                    key=lambda item: (item.independent_group_id, item.member_id),
                )
            ),
            rejection_reasons=tuple(rejection_reasons),
        )

    def invariant(self, inputs: CouncilDecisionInput, outputs: CouncilDecision) -> None:
        if outputs.rule_id != inputs.rule_id:
            raise InvariantViolation("decision rule_id does not match input votes")
        if outputs.rule_hash != inputs.rule_hash:
            raise InvariantViolation("decision rule_hash does not match input votes")
        if outputs.validate_report_hash != inputs.validate_report_hash:
            raise InvariantViolation("decision validate_report_hash does not match input votes")
        if outputs.decision not in {DECISION_APPROVE, DECISION_REJECT}:
            raise InvariantViolation("decision must be approve or reject")
        if outputs.decision_rule_id != DECISION_RULE_ID:
            raise InvariantViolation("decision rule id mismatch")
        if outputs.decision_rule_hash != DECISION_RULE_HASH:
            raise InvariantViolation("decision rule hash mismatch")

        classification = inputs.independence
        assert isinstance(classification, IndependenceClassification)
        if outputs.independence_classification_hash != classification.classification_hash:
            raise InvariantViolation("independence classification hash mismatch")

        vote_member_ids = sorted(vote.member_id for vote in inputs.votes)
        output_member_ids = sorted(item["member_id"] for item in outputs.member_votes)
        if output_member_ids != vote_member_ids:
            raise InvariantViolation("member vote summaries must cover input votes")
        if len(outputs.independent_approver_group_ids) != outputs.approval_voice_count:
            raise InvariantViolation("approval voice count must match approver groups")
        if len(set(outputs.independent_approver_group_ids)) != len(
            outputs.independent_approver_group_ids
        ):
            raise InvariantViolation("approver groups must be unique")

        group_votes = {group.independent_group_id: group.vote for group in outputs.independent_groups}
        reject_group_ids = {
            group.independent_group_id
            for group in outputs.independent_groups
            if group.vote == REJECT
        }
        if reject_group_ids and "independent_reject" not in outputs.rejection_reasons:
            raise InvariantViolation("rejecting independent groups must block")
        if len(outputs.independent_approver_group_ids) < 2 and (
            "insufficient_independent_approvals" not in outputs.rejection_reasons
        ):
            raise InvariantViolation("fewer than two approval voices must reject")
        if outputs.decision == DECISION_APPROVE:
            if outputs.rejection_reasons:
                raise InvariantViolation("approved decision cannot have rejection reasons")
            if any(group_votes[group_id] != APPROVE for group_id in outputs.independent_approver_group_ids):
                raise InvariantViolation("approver group ids must name approve groups")
        else:
            if not outputs.rejection_reasons:
                raise InvariantViolation("rejected decision must include rejection reasons")

    def audit_extra_payload(
        self,
        inputs: CouncilDecisionInput,
        outputs: CouncilDecision,
        ctx: StageContext,
        *,
        inputs_hash: str,
        output_hash: str,
    ) -> dict[str, Any]:
        return outputs.as_dict()

    def _serialize_output(self, outputs: CouncilDecision) -> bytes:
        return canonicalize(outputs.as_dict())

    def _deserialize_output(self, data: bytes) -> CouncilDecision:
        raw = json.loads(data.decode("utf-8"))
        return CouncilDecision(
            rule_id=str(raw["rule_id"]),
            rule_hash=str(raw["rule_hash"]),
            validate_report_hash=str(raw["validate_report_hash"]),
            decision=str(raw["decision"]),
            route=str(raw["route"]),
            decision_rule_id=str(raw["decision_rule_id"]),
            decision_rule_hash=str(raw["decision_rule_hash"]),
            independence_classification_id=str(raw["independence_classification_id"]),
            independence_classification_hash=str(raw["independence_classification_hash"]),
            member_votes=tuple(dict(item) for item in raw["member_votes"]),
            independent_groups=tuple(
                IndependentGroupDecision(
                    independent_group_id=str(item["independent_group_id"]),
                    member_ids=tuple(str(member_id) for member_id in item["member_ids"]),
                    vote=str(item["vote"]),
                    approve_member_ids=tuple(
                        str(member_id) for member_id in item["approve_member_ids"]
                    ),
                    reject_member_ids=tuple(
                        str(member_id) for member_id in item["reject_member_ids"]
                    ),
                    voice_count=int(item["voice_count"]),
                )
                for item in raw["independent_groups"]
            ),
            independent_approver_group_ids=tuple(
                str(item) for item in raw["independent_approver_group_ids"]
            ),
            independent_approver_member_ids=tuple(
                str(item) for item in raw["independent_approver_member_ids"]
            ),
            approval_voice_count=int(raw["approval_voice_count"]),
            blocking_rationales=tuple(
                BlockingRationale(
                    independent_group_id=str(item["independent_group_id"]),
                    member_id=str(item["member_id"]),
                    member_version=str(item["member_version"]),
                    rationale=str(item["rationale"]),
                    rationale_hash=str(item["rationale_hash"]),
                    citations=tuple(str(citation) for citation in item["citations"]),
                )
                for item in raw["blocking_rationales"]
            ),
            rejection_reasons=tuple(str(item) for item in raw["rejection_reasons"]),
        )
