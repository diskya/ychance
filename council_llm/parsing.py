from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from audit import canonicalize

from .types import APPROVE, NEED_FULL_REVIEW, REJECT, SCREENING_VOTES


class CouncilParseError(ValueError):
    pass


@dataclass(frozen=True)
class ParsedFullVote:
    vote: str
    rationale: str
    citations: tuple[str, ...]


def parse_screening_vote(text: str) -> str:
    payload = _json_object(text)
    if isinstance(payload, dict):
        raw = payload.get("screening_vote", payload.get("vote"))
        if isinstance(raw, str):
            return _normalize_vote(raw, allow_need_full_review=True)
    return _single_vote_from_text(text, allow_need_full_review=True)


def parse_full_vote(text: str) -> ParsedFullVote:
    payload = _json_object(text)
    if not isinstance(payload, dict):
        vote = _single_vote_from_text(text, allow_need_full_review=False)
        return ParsedFullVote(vote=vote, rationale="", citations=())

    raw_vote = payload.get("vote")
    if not isinstance(raw_vote, str):
        raise CouncilParseError("full review response is missing vote")
    vote = _normalize_vote(raw_vote, allow_need_full_review=False)
    rationale = payload.get("rationale", "")
    if rationale is None:
        rationale = ""
    if not isinstance(rationale, str):
        rationale = str(rationale)
    raw_citations = payload.get("citations", payload.get("key_evidence_citations", []))
    return ParsedFullVote(
        vote=vote,
        rationale=rationale,
        citations=_coerce_citations(raw_citations),
    )


def _json_object(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
    return None


def _normalize_vote(raw: str, *, allow_need_full_review: bool) -> str:
    normalized = re.sub(r"[\s_-]+", " ", raw.strip().lower())
    allowed = set(SCREENING_VOTES if allow_need_full_review else {APPROVE, REJECT})
    if normalized in allowed:
        return normalized
    raise CouncilParseError(f"invalid vote {raw!r}")


def _single_vote_from_text(text: str, *, allow_need_full_review: bool) -> str:
    normalized = re.sub(r"[\s_-]+", " ", text.strip().lower())
    candidates = [APPROVE, REJECT]
    if allow_need_full_review:
        candidates.append(NEED_FULL_REVIEW)
    matches = [vote for vote in candidates if re.search(rf"\b{re.escape(vote)}\b", normalized)]
    if len(matches) == 1:
        return matches[0]
    raise CouncilParseError("response must contain exactly one valid vote")


def _coerce_citations(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if not isinstance(value, list):
        raise CouncilParseError("citations must be a list or string")
    citations: list[str] = []
    for item in value:
        if isinstance(item, str):
            citations.append(item)
        else:
            citations.append(canonicalize(item).decode("utf-8"))
    return tuple(citations)
