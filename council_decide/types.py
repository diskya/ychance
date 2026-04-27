from __future__ import annotations

import dataclasses
import hashlib
from dataclasses import dataclass
from typing import Any, Mapping

from audit import canonicalize
from council_llm import CouncilVote
from council_llm.types import FINAL_VOTES, text_hash


DECISION_APPROVE = "approve"
DECISION_REJECT = "reject"

DECISION_RULE_ID = "council_decision_rule_v1"
DECISION_RULE_SPEC: dict[str, Any] = {
    "decision_rule_id": DECISION_RULE_ID,
    "version": 1,
    "minimum_independent_approve_groups": 2,
    "reject_blocks": True,
    "independent_group_field": "independent_group_id",
    "collapsed_group_semantics": (
        "members sharing independent_group_id count as one voice; "
        "any reject inside the group makes that voice reject"
    ),
    "approver_representative": "lexicographically first approving member_id per group",
}
DECISION_RULE_HASH = hashlib.sha256(canonicalize(DECISION_RULE_SPEC)).hexdigest()


@dataclass(frozen=True)
class IndependenceClassification:
    classification_id: str
    member_groups: dict[str, str]

    def __post_init__(self) -> None:
        if not isinstance(self.classification_id, str) or not self.classification_id:
            raise ValueError("classification_id must be a non-empty string")
        if not isinstance(self.member_groups, Mapping) or not self.member_groups:
            raise ValueError("member_groups must be a non-empty mapping")
        normalized: dict[str, str] = {}
        for raw_member_id, raw_group_id in self.member_groups.items():
            member_id = str(raw_member_id)
            group_id = str(raw_group_id)
            if not member_id:
                raise ValueError("member_groups keys must be non-empty member ids")
            if not group_id:
                raise ValueError("member_groups values must be non-empty group ids")
            normalized[member_id] = group_id
        object.__setattr__(self, "member_groups", normalized)

    @property
    def classification_hash(self) -> str:
        return content_hash(self.as_dict())

    def as_dict(self) -> dict[str, Any]:
        return {
            "classification_id": self.classification_id,
            "member_groups": dict(sorted(self.member_groups.items())),
        }


@dataclass(frozen=True)
class CouncilMemberVote:
    rule_id: str
    rule_hash: str
    validate_report_hash: str
    member_id: str
    member_version: str
    vote: str
    rationale: str
    citations: tuple[str, ...]
    rationale_hash: str
    vote_record_hash: str | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "rule_id",
            "rule_hash",
            "validate_report_hash",
            "member_id",
            "member_version",
            "vote",
            "rationale_hash",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"{field_name} must be a non-empty string")
        if self.vote not in FINAL_VOTES:
            raise ValueError("vote must be approve or reject")
        if not isinstance(self.rationale, str):
            raise TypeError("rationale must be a string")
        if len(self.rule_hash) != 64 or len(self.validate_report_hash) != 64:
            raise ValueError("rule_hash and validate_report_hash must be 64-char hashes")
        if self.vote_record_hash is not None and (
            not isinstance(self.vote_record_hash, str) or len(self.vote_record_hash) != 64
        ):
            raise ValueError("vote_record_hash must be a 64-character string or None")
        object.__setattr__(self, "citations", tuple(str(item) for item in self.citations))
        expected = text_hash(self.rationale)
        if self.rationale_hash != expected:
            raise ValueError("rationale_hash does not match rationale")

    def summary(self, independent_group_id: str) -> dict[str, Any]:
        payload = {
            "member_id": self.member_id,
            "member_version": self.member_version,
            "independent_group_id": independent_group_id,
            "vote": self.vote,
            "rationale_hash": self.rationale_hash,
            "citations": list(self.citations),
        }
        if self.vote_record_hash is not None:
            payload["vote_record_hash"] = self.vote_record_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "rule_hash": self.rule_hash,
            "validate_report_hash": self.validate_report_hash,
            "member_id": self.member_id,
            "member_version": self.member_version,
            "vote": self.vote,
            "rationale": self.rationale,
            "citations": list(self.citations),
            "rationale_hash": self.rationale_hash,
            "vote_record_hash": self.vote_record_hash,
        }


@dataclass(frozen=True)
class BlockingRationale:
    independent_group_id: str
    member_id: str
    member_version: str
    rationale: str
    rationale_hash: str
    citations: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "independent_group_id": self.independent_group_id,
            "member_id": self.member_id,
            "member_version": self.member_version,
            "rationale": self.rationale,
            "rationale_hash": self.rationale_hash,
            "citations": list(self.citations),
        }


@dataclass(frozen=True)
class IndependentGroupDecision:
    independent_group_id: str
    member_ids: tuple[str, ...]
    vote: str
    approve_member_ids: tuple[str, ...]
    reject_member_ids: tuple[str, ...]
    voice_count: int = 1

    def as_dict(self) -> dict[str, Any]:
        return {
            "independent_group_id": self.independent_group_id,
            "member_ids": list(self.member_ids),
            "vote": self.vote,
            "approve_member_ids": list(self.approve_member_ids),
            "reject_member_ids": list(self.reject_member_ids),
            "voice_count": self.voice_count,
        }


@dataclass(frozen=True)
class CouncilDecisionInput:
    cycle_id: str
    votes: tuple[CouncilMemberVote | CouncilVote | Mapping[str, Any], ...]
    independence: IndependenceClassification | Mapping[str, Any]

    def __post_init__(self) -> None:
        if not isinstance(self.cycle_id, str) or not self.cycle_id:
            raise ValueError("cycle_id must be a non-empty string")
        votes = tuple(load_member_vote(item) for item in self.votes)
        if not votes:
            raise ValueError("at least one vote is required")
        seen_members: set[str] = set()
        for vote in votes:
            if vote.member_id in seen_members:
                raise ValueError(f"duplicate vote for member {vote.member_id}")
            seen_members.add(vote.member_id)
        rule_ids = {vote.rule_id for vote in votes}
        rule_hashes = {vote.rule_hash for vote in votes}
        report_hashes = {vote.validate_report_hash for vote in votes}
        if len(rule_ids) != 1 or len(rule_hashes) != 1 or len(report_hashes) != 1:
            raise ValueError("all votes must refer to the same rule and validate report")

        classification = load_independence_classification(self.independence)
        missing = sorted(member_id for member_id in seen_members if member_id not in classification.member_groups)
        if missing:
            raise ValueError(f"missing independence groups for members: {missing}")

        object.__setattr__(self, "votes", votes)
        object.__setattr__(self, "independence", classification)

    @property
    def rule_id(self) -> str:
        return self.votes[0].rule_id

    @property
    def rule_hash(self) -> str:
        return self.votes[0].rule_hash

    @property
    def validate_report_hash(self) -> str:
        return self.votes[0].validate_report_hash

    def as_dict(self) -> dict[str, Any]:
        classification = self.independence
        assert isinstance(classification, IndependenceClassification)
        return {
            "cycle_id": self.cycle_id,
            "votes": [vote.as_dict() for vote in self.votes],
            "independence": classification.as_dict(),
        }


@dataclass(frozen=True)
class CouncilDecision:
    rule_id: str
    rule_hash: str
    validate_report_hash: str
    decision: str
    route: str
    decision_rule_id: str
    decision_rule_hash: str
    independence_classification_id: str
    independence_classification_hash: str
    member_votes: tuple[dict[str, Any], ...]
    independent_groups: tuple[IndependentGroupDecision, ...]
    independent_approver_group_ids: tuple[str, ...]
    independent_approver_member_ids: tuple[str, ...]
    approval_voice_count: int
    blocking_rationales: tuple[BlockingRationale, ...]
    rejection_reasons: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "rule_hash": self.rule_hash,
            "validate_report_hash": self.validate_report_hash,
            "decision": self.decision,
            "route": self.route,
            "decision_rule_id": self.decision_rule_id,
            "decision_rule_hash": self.decision_rule_hash,
            "independence_classification_id": self.independence_classification_id,
            "independence_classification_hash": self.independence_classification_hash,
            "member_votes": [dict(item) for item in self.member_votes],
            "independent_groups": [group.as_dict() for group in self.independent_groups],
            "independent_approver_group_ids": list(self.independent_approver_group_ids),
            "independent_approver_member_ids": list(self.independent_approver_member_ids),
            "approval_voice_count": self.approval_voice_count,
            "blocking_rationales": [item.as_dict() for item in self.blocking_rationales],
            "rejection_reasons": list(self.rejection_reasons),
            "approve_threshold": DECISION_RULE_SPEC["minimum_independent_approve_groups"],
            "reject_blocks": DECISION_RULE_SPEC["reject_blocks"],
        }


def load_independence_classification(
    value: IndependenceClassification | Mapping[str, Any],
) -> IndependenceClassification:
    if isinstance(value, IndependenceClassification):
        return value
    if not isinstance(value, Mapping):
        raise TypeError("independence must be an IndependenceClassification or mapping")
    if "member_groups" in value:
        return IndependenceClassification(
            classification_id=str(value.get("classification_id", "inline")),
            member_groups=dict(value["member_groups"]),
        )
    return IndependenceClassification(
        classification_id="inline",
        member_groups={str(key): str(item) for key, item in value.items()},
    )


def load_member_vote(value: CouncilMemberVote | CouncilVote | Mapping[str, Any]) -> CouncilMemberVote:
    if isinstance(value, CouncilMemberVote):
        return value
    if isinstance(value, CouncilVote):
        return CouncilMemberVote(
            rule_id=value.rule_id,
            rule_hash=value.rule_hash,
            validate_report_hash=value.validate_report_hash,
            member_id=value.member_id,
            member_version=value.member_version,
            vote=value.vote,
            rationale=value.rationale,
            citations=value.citations,
            rationale_hash=value.rationale_hash,
        )
    if not isinstance(value, Mapping):
        raise TypeError("vote must be a CouncilMemberVote, CouncilVote, or mapping")
    citations = value.get("citations", value.get("key_evidence_citations", ()))
    if isinstance(citations, str):
        citations = (citations,)
    rationale = str(value.get("rationale", ""))
    rationale_hash = str(value.get("rationale_hash", text_hash(rationale)))
    vote_record_hash = value.get("record_hash", value.get("vote_record_hash"))
    return CouncilMemberVote(
        rule_id=str(value["rule_id"]),
        rule_hash=str(value["rule_hash"]),
        validate_report_hash=str(value["validate_report_hash"]),
        member_id=str(value["member_id"]),
        member_version=str(value["member_version"]),
        vote=str(value["vote"]),
        rationale=rationale,
        citations=tuple(str(item) for item in citations),
        rationale_hash=rationale_hash,
        vote_record_hash=None if vote_record_hash is None else str(vote_record_hash),
    )


def content_hash(payload: Any) -> str:
    return hashlib.sha256(canonicalize(to_jsonable(payload))).hexdigest()


def to_jsonable(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        if hasattr(value, "as_dict"):
            return to_jsonable(value.as_dict())
        return to_jsonable(dataclasses.asdict(value))
    if isinstance(value, Mapping):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(item) for item in value]
    return value
