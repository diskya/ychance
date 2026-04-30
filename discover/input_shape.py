from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal


ShapeName = Literal["tool_request", "red_team_request", "flagged"]


@dataclass(frozen=True)
class ShapeClassification:
    input_text: str
    shape_classification: ShapeName
    normalized_directive: str | None
    rejection_reason: str | None


_SPACE_RE = re.compile(r"\s+")
_CONTENT_PATTERNS = (
    re.compile(r"\bwhat\s+about\b", re.IGNORECASE),
    re.compile(r"\bhave\s+you\s+checked\b", re.IGNORECASE),
    re.compile(r"\blook\s+at\b", re.IGNORECASE),
    re.compile(r"\bfocus\s+on\b", re.IGNORECASE),
)
_CONTENT_TERMS = frozenset(
    {
        "momentum",
        "reversion",
        "earnings",
        "revenue",
        "profit",
        "volatility",
        "sentiment",
        "macro",
        "inflation",
        "rates",
        "yield",
        "sector",
        "industry",
        "size",
        "value",
        "growth",
        "quality",
        "liquidity",
        "news",
        "filing",
    }
)
_TOOL_WORDS = frozenset(
    {
        "compute",
        "run",
        "inspect",
        "show",
        "distribution",
        "window",
        "different",
        "same",
        "stratified",
        "partition",
        "that",
        "this",
        "again",
        "sample",
    }
)
_RED_TEAM_WORDS = frozenset(
    {
        "falsify",
        "falsification",
        "simplest",
        "non-pattern",
        "explanation",
        "shuffled",
        "shuffle",
        "control",
        "reproduce",
        "replicate",
        "fail",
        "failure",
        "alternative",
    }
)


def classify_operator_input(text: str) -> ShapeClassification:
    """Classify operator text and return only a non-content directive if accepted."""

    if not isinstance(text, str):
        raise TypeError("operator input must be a string")
    normalized_text = _SPACE_RE.sub(" ", text.strip())
    if not normalized_text:
        return ShapeClassification(
            input_text=text,
            shape_classification="flagged",
            normalized_directive=None,
            rejection_reason="empty input",
        )

    lowered = normalized_text.lower()
    if any(pattern.search(normalized_text) for pattern in _CONTENT_PATTERNS):
        return _flagged(text, "content-shaped targeting phrase")
    if _contains_content_term(lowered):
        return _flagged(text, "content-shaped term")

    tokens = set(re.findall(r"[a-z]+(?:-[a-z]+)?", lowered))
    if tokens & _RED_TEAM_WORDS:
        return ShapeClassification(
            input_text=text,
            shape_classification="red_team_request",
            normalized_directive="red_team_request: stress-test the current claim without new content",
            rejection_reason=None,
        )
    if tokens & _TOOL_WORDS:
        return ShapeClassification(
            input_text=text,
            shape_classification="tool_request",
            normalized_directive="tool_request: adjust tool use on existing outputs without new content",
            rejection_reason=None,
        )
    return _flagged(text, "unrecognized input shape")


def _contains_content_term(lowered: str) -> bool:
    tokens = set(re.findall(r"[a-z]+", lowered))
    if tokens & _CONTENT_TERMS:
        return True
    return "mean reversion" in lowered


def _flagged(text: str, reason: str) -> ShapeClassification:
    return ShapeClassification(
        input_text=text,
        shape_classification="flagged",
        normalized_directive=None,
        rejection_reason=reason,
    )
