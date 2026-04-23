from __future__ import annotations

from rule import finalize_rule, load_rule

from .fixtures.helpers import (
    AUX_SPEC,
    base_grounding,
    binary,
    context_price_gt,
    context_price_le,
    literal,
    rule_body,
    spec_ref,
)


def _deep_context() -> dict:
    return {
        "nodes": [
            spec_ref(node_id="price"),
            spec_ref(AUX_SPEC, "aux"),
            literal(100, "one"),
            literal(5, "two"),
            binary("sum", "add", "price", "two"),
            binary("gt", "gt", "sum", "one"),
            binary("aux_ok", "le", "aux", "two"),
            {"id": "both", "op": "and", "args": {}, "inputs": ["gt", "aux_ok"]},
        ],
        "output": "both",
    }


def test_load_rule_round_trips_finalized_bodies() -> None:
    bodies = [
        rule_body(side="long", grounding=base_grounding("in_range")),
        rule_body(side="short", context=context_price_le(), grounding=base_grounding("quantile_ge")),
        rule_body(side="cash", context=_deep_context(), grounding=base_grounding("sign")),
        rule_body(
            context={
                "nodes": [
                    spec_ref(node_id="price"),
                    literal(100, "threshold"),
                    binary("above", "gt", "price", "threshold"),
                    {"id": "invert", "op": "not", "args": {}, "inputs": ["above"]},
                ],
                "output": "invert",
            },
            side="long",
            grounding=base_grounding("in_range"),
        ),
        rule_body(
            context=context_price_gt(101),
            exit={
                "nodes": [
                    {"id": "held", "op": "time_since_entry", "args": {}, "inputs": []},
                    literal(2, "two"),
                    binary("done", "ge", "held", "two"),
                ],
                "output": "done",
            },
            side="short",
            grounding=base_grounding("sign"),
        ),
    ]

    for body in bodies:
        finalized = finalize_rule(body)
        assert load_rule(finalized.to_dict()).rule_id == finalized.rule_id
