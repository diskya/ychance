"""Prompt templates for draft and adjudicate passes.

Prompts are designed to avoid named-method vocabulary and focus on
primitive rule components: predicates, actions, exits, groundings.
"""

from __future__ import annotations

from typing import Any


def make_draft_prompt(
    slice_description: str,
    available_specs: list[str],
    anti_patterns: list[dict[str, Any]] | None = None,
    live_rule_groundings: list[dict[str, Any]] | None = None,
) -> str:
    """Create a prompt for the draft pass.

    Args:
        slice_description: human-readable summary of data slice
        available_specs: list of spec_id strings the model can reference
        anti_patterns: optional list of behaviors to avoid
        live_rule_groundings: optional list of existing rule groundings

    Returns:
        A prompt string suitable for qwen-plus.
    """
    anti_pattern_text = ""
    if anti_patterns:
        anti_pattern_text = "## Behaviors to avoid\n"
        for i, ap in enumerate(anti_patterns, 1):
            anti_pattern_text += f"{i}. {ap.get('description', 'Unknown')}\n"

    grounding_text = ""
    if live_rule_groundings:
        grounding_text = "## Existing rule groundings (for originality context)\n"
        for i, g in enumerate(live_rule_groundings, 1):
            grounding_text += f"{i}. {g.get('spec_ref', 'N/A')}: {g.get('assertion', {}).get('kind', 'N/A')}\n"

    available_specs_str = ", ".join(available_specs[:10]) if available_specs else "none"
    if len(available_specs) > 10:
        available_specs_str += ", ..."

    prompt = f"""You are a quantitative rule generator. Your task is to propose executable trading rules based on data.

## Data Slice
{slice_description}

## Available Features (spec_ids)
{available_specs_str}

## Rule Structure
Each rule must be a valid JSON object with:
- context: a DAG of predicates (comparisons, arithmetic, boolean operations)
- exit: a DAG of exit conditions
- action: {{side: "long"/"short"/"cash", size_multiplier: 0-10}}
- horizon_bars: number of bars (1-1000)
- cadence: {{kind: "fixed_step", step_seconds: 60-86400}}
- grounding: spec_ref, assertion (kind in {{in_range, quantile_ge, sign}}), window
- price_spec_ref: a 64-character spec_id string

## Primitive Operations
For predicates and exit conditions, use only:
- Comparisons: lt, le, gt, ge, eq, ne
- Boolean: and, or, not
- Arithmetic: add, sub, mul, div
- Literals: literal{{num: number}}
- Spec access: spec_ref{{id: "64-char-spec-id"}}

Do NOT use: named methods, feature categories, technical names, or prior vocabulary.

{anti_pattern_text}

{grounding_text}

## Your Task
Generate 2-3 candidate rules that:
1. Are syntactically valid JSON
2. Use the available spec_ids appropriately
3. Avoid the behaviors above
4. Have a computable grounding (the assertion can be checked against data)
5. Are simple enough to execute quickly

Return a JSON array of candidate objects. Each candidate is a complete rule object ready for parsing.

[START RESPONSE]"""
    return prompt


def make_adjudicate_prompt(
    candidates_json: str,
    candidate_count: int,
    performance_hint: str | None = None,
) -> str:
    """Create a prompt for the adjudicate pass.

    Args:
        candidates_json: JSON string of draft candidates
        candidate_count: number of candidates being reviewed
        performance_hint: optional note about expected execution fitness

    Returns:
        A prompt string suitable for qwen-plus.
    """
    performance_text = ""
    if performance_hint:
        performance_text = f"\n## Performance Context\n{performance_hint}\n"

    prompt = f"""You are reviewing trading rule candidates for executability and coherence.

## Candidates (from draft pass)
{candidates_json}

{performance_text}

## Review Criteria
For each candidate, assess:
1. Does the context DAG use valid operations and spec_refs?
2. Does the exit DAG use valid operations?
3. Is the grounding window reasonable (1+ days, <365 days)?
4. Is the action side valid and size_multiplier finite and non-negative?
5. Is the horizon_bars positive and reasonable (<10000)?

## Output Format
Return a JSON object:
{{
  "candidates_reviewed": {candidate_count},
  "decisions": [
    {{
      "index": 0,
      "assessment": "brief explanation",
      "keep": true/false,
      "confidence": 0.0-1.0
    }},
    ...
  ]
}}

Do NOT modify the candidates. Only score them as-is.

[START RESPONSE]"""
    return prompt
