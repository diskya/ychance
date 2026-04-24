"""Scoring logic for draft and adjudicate passes.

Draft score: heuristic evaluation based on LLM confidence and grounding testability.
Adjudicate score: refined evaluation after deeper inspection.
"""

from __future__ import annotations

from typing import Any, Mapping


def score_draft_candidate(candidate: Mapping[str, Any]) -> float:
    """Score a candidate from the draft pass.

    Returns a float in [0, 1]. Higher is more promising.

    Draft scoring is heuristic and fast: checks basic structure,
    grounding window size, and action simplicity.
    """
    try:
        # Penalize missing or malformed grounding
        grounding = candidate.get("grounding", {})
        if not isinstance(grounding, Mapping) or not grounding.get("window"):
            return 0.1

        # Reasonable window size (not too short, not too long)
        window = grounding.get("window", {})
        if isinstance(window, Mapping):
            try:
                from datetime import datetime
                t0_str = window.get("t0")
                t1_str = window.get("t1")
                if isinstance(t0_str, str) and isinstance(t1_str, str):
                    t0 = datetime.fromisoformat(t0_str)
                    t1 = datetime.fromisoformat(t1_str)
                    window_days = (t1 - t0).days
                    if window_days < 1 or window_days > 365:
                        return 0.2
            except (ValueError, AttributeError):
                return 0.2

        # Action should be reasonable
        action = candidate.get("action", {})
        if isinstance(action, Mapping):
            side = action.get("side")
            multiplier = action.get("size_multiplier", 0)
            if side not in {"long", "short", "cash"}:
                return 0.1
            if not isinstance(multiplier, (int, float)) or multiplier < 0 or multiplier > 10:
                return 0.2

        # Grounding should have a reasonable assertion
        assertion = grounding.get("assertion", {})
        if isinstance(assertion, Mapping):
            kind = assertion.get("kind")
            if kind not in {"in_range", "quantile_ge", "sign"}:
                return 0.1

        # If we got here, structure looks reasonable
        return 0.6
    except Exception:
        return 0.1


def score_adjudicate_candidate(
    candidate: Mapping[str, Any],
    execution_succeeded: bool,
    grounding_evaluated: bool,
) -> float:
    """Score a candidate from the adjudicate pass.

    Returns a float in [0, 1]. Higher is more promising.

    Adjudicate scoring reflects whether the candidate passed key checks:
    - Execution without raising
    - Grounding can be evaluated
    """
    base_score = score_draft_candidate(candidate)

    if not execution_succeeded:
        return base_score * 0.3

    if not grounding_evaluated:
        return base_score * 0.5

    # Candidate passed both execution and grounding checks
    return min(0.95, base_score * 1.2)
