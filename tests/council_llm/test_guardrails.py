from __future__ import annotations

import ast
from pathlib import Path

from council_llm import build_screening_prompt
from rule import finalize_rule
from tests.council_llm.test_stage import _report
from tests.rule.fixtures.helpers import rule_body


COUNCIL_ROOT = Path(__file__).resolve().parents[2] / "council_llm"


def test_council_llm_has_no_direct_rawstore_imports() -> None:
    for path in sorted(COUNCIL_ROOT.glob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name != "rawstore"
                    assert not alias.name.startswith("rawstore.")
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                assert module != "rawstore"
                assert not module.startswith("rawstore.")


def test_council_llm_does_not_import_propose() -> None:
    for path in sorted(COUNCIL_ROOT.glob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name != "propose"
                    assert not alias.name.startswith("propose.")
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                assert module != "propose"
                assert not module.startswith("propose.")


def test_prompt_builder_does_not_expose_propose_rationale_values() -> None:
    rule = finalize_rule(rule_body())
    raw_slice = {
        "rows": [{"value": 1.0}],
        "free_text_rationale": "NEVER_SEND_THIS_ARGUMENT",
        "proposing_model": "NEVER_SEND_THIS_MODEL",
    }
    prompt = build_screening_prompt(
        rule=rule,
        validate_report=_report(rule),
        raw_slice=raw_slice,
    )

    assert "NEVER_SEND_THIS_ARGUMENT" not in prompt
    assert "NEVER_SEND_THIS_MODEL" not in prompt
