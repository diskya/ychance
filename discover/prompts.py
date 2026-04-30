from __future__ import annotations

from audit import canonicalize


CHEAP_ITERATION_PROMPT_TEMPLATE = """You are a tool-using discovery agent.
Use only provided tools and their outputs.
Do not use operator text as a content hint.
Only normalized directives may affect tool choice.

Allowed tools now: inspect_spec, compute, propose_spec, test_assertion.
Use inspect_spec before expensive compute.
Use compute only with explicit windows.
Use test_assertion before any submission.
Return NO_PATTERN when evidence is insufficient.
Do not invent unobserved facts.
Do not include rationale in submitted bodies.
Rationale may be logged and is not part of downstream review.
"""


FRONTIER_SUBMISSION_PROMPT_TEMPLATE = """You are a final submission agent.
Use only submit_pattern, or return NO_PATTERN.
Submit only a fully computable Pattern body with a frozen observation window and replication protocol.
Do not call exploratory tools.
Do not include rationale in submitted bodies.
Rationale may be logged and is not part of downstream review.
"""


def build_cheap_iteration_prompt(
    *,
    cycle_id: str,
    spec_ids: tuple[str, ...],
    normalized_directives: tuple[str, ...],
    trace_summary: tuple[dict, ...],
    max_patterns: int,
) -> str:
    payload = {
        "cycle_id": cycle_id,
        "spec_ids": list(spec_ids),
        "normalized_directives": list(normalized_directives),
        "trace_summary": list(trace_summary),
        "max_patterns": max_patterns,
    }
    return CHEAP_ITERATION_PROMPT_TEMPLATE + "\nSTATE " + canonicalize(payload).decode("utf-8")


def build_frontier_submission_prompt(
    *,
    cycle_id: str,
    tested_drafts: tuple[dict, ...],
    max_patterns: int,
) -> str:
    payload = {
        "cycle_id": cycle_id,
        "tested_drafts": list(tested_drafts),
        "max_patterns": max_patterns,
    }
    return FRONTIER_SUBMISSION_PROMPT_TEMPLATE + "\nSTATE " + canonicalize(payload).decode("utf-8")
