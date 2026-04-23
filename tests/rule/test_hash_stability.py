from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

from rule import finalize_rule
from rule import action as action_module
from rule.predicate_ops import DEFAULT_PREDICATE_OPS

from .fixtures.helpers import base_grounding, context_price_gt, context_price_le, rule_body, tick


def test_predicate_op_version_bump_only_changes_rules_using_that_op() -> None:
    gt_body = rule_body(context=context_price_gt())
    le_body = rule_body(context=context_price_le())
    base_gt = finalize_rule(gt_body).rule_id
    base_le = finalize_rule(le_body).rule_id

    shifted = dict(DEFAULT_PREDICATE_OPS)
    shifted["gt"] = replace(shifted["gt"], op_version="2")

    assert finalize_rule(gt_body, predicate_registry=shifted).rule_id != base_gt
    assert finalize_rule(le_body, predicate_registry=shifted).rule_id == base_le


def test_action_schema_version_bump_changes_rule_id(monkeypatch) -> None:
    base = finalize_rule(rule_body()).rule_id
    monkeypatch.setattr(action_module, "action_schema_version", 2)
    shifted = rule_body()

    assert finalize_rule(shifted).rule_id != base


def test_grounding_window_changes_rule_id() -> None:
    body = rule_body()
    shifted = deepcopy(body)
    shifted["grounding"] = base_grounding("in_range")
    shifted["grounding"]["window"]["t1"] = tick(5).isoformat()

    assert finalize_rule(shifted).rule_id != finalize_rule(body).rule_id


def test_cadence_step_changes_rule_id() -> None:
    body = rule_body()
    shifted = deepcopy(body)
    shifted["cadence"]["step_seconds"] = 120

    assert finalize_rule(shifted).rule_id != finalize_rule(body).rule_id


def test_canonical_json_is_stable_across_dict_insertion_order() -> None:
    body = rule_body()
    reordered = {
        "price_spec_ref": body["price_spec_ref"],
        "grounding": {
            "window": {
                "t1": body["grounding"]["window"]["t1"],
                "t0": body["grounding"]["window"]["t0"],
            },
            "assertion": {
                "hi": body["grounding"]["assertion"]["hi"],
                "kind": body["grounding"]["assertion"]["kind"],
                "lo": body["grounding"]["assertion"]["lo"],
            },
            "spec_ref": body["grounding"]["spec_ref"],
        },
        "cadence": {"step_seconds": body["cadence"]["step_seconds"], "kind": "fixed_step"},
        "horizon_bars": body["horizon_bars"],
        "action_schema_version": body["action_schema_version"],
        "action": {
            "size_multiplier": body["action"]["size_multiplier"],
            "side": body["action"]["side"],
        },
        "exit": {
            "output": body["exit"]["output"],
            "nodes": [dict(reversed(list(node.items()))) for node in reversed(body["exit"]["nodes"])],
        },
        "context": {
            "output": body["context"]["output"],
            "nodes": [dict(reversed(list(node.items()))) for node in reversed(body["context"]["nodes"])],
        },
    }

    assert finalize_rule(reordered).rule_id == finalize_rule(body).rule_id
