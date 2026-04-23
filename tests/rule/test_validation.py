from __future__ import annotations

from copy import deepcopy

import pytest

from rule import RuleValidationError, finalize_rule

from .fixtures.helpers import binary, literal, rule_body


def test_finalize_rejects_predicate_root_not_bool_typed() -> None:
    body = rule_body()
    body["context"] = {"nodes": [literal(1, "one")], "output": "one"}

    with pytest.raises(RuleValidationError, match="context root"):
        finalize_rule(body)


def test_finalize_rejects_exit_root_not_bool_typed() -> None:
    body = rule_body()
    body["exit"] = {
        "nodes": [{"id": "held", "op": "time_since_entry", "args": {}, "inputs": []}],
        "output": "held",
    }

    with pytest.raises(RuleValidationError, match="exit root"):
        finalize_rule(body)


def test_finalize_rejects_unknown_assertion_kind() -> None:
    body = rule_body()
    body["grounding"]["assertion"] = {"kind": "unknown"}

    with pytest.raises(RuleValidationError, match="assertion kind"):
        finalize_rule(body)


def test_finalize_rejects_unknown_predicate_op() -> None:
    body = rule_body()
    body["context"]["nodes"][0]["op"] = "unknown"

    with pytest.raises(RuleValidationError, match="unknown op"):
        finalize_rule(body)


def test_finalize_rejects_unknown_exit_op() -> None:
    body = rule_body()
    body["exit"] = {
        "nodes": [
            {"id": "a", "op": "time_since_entry", "args": {}, "inputs": []},
            literal(1, "one"),
            binary("done", "unknown", "a", "one"),
        ],
        "output": "done",
    }

    with pytest.raises(RuleValidationError, match="unknown op"):
        finalize_rule(body)


def test_finalize_rejects_missing_required_field() -> None:
    body = rule_body()
    del body["cadence"]

    with pytest.raises(RuleValidationError, match="missing"):
        finalize_rule(body)


def test_finalize_rejects_non_tz_aware_grounding_window() -> None:
    body = rule_body()
    body["grounding"]["window"]["t0"] = "2026-01-01T00:00:00"

    with pytest.raises(RuleValidationError, match="timezone-aware"):
        finalize_rule(body)


def test_finalize_rejects_unknown_action_side() -> None:
    body = rule_body()
    body["action"]["side"] = "other"

    with pytest.raises(RuleValidationError, match="action.side"):
        finalize_rule(body)


def test_load_rejects_changed_document_hash() -> None:
    rule = finalize_rule(rule_body())
    doc = deepcopy(rule.to_dict())
    doc["horizon_bars"] = doc["horizon_bars"] + 1

    from rule import load_rule

    with pytest.raises(RuleValidationError, match="rule_id"):
        load_rule(doc)
