from __future__ import annotations

import ast
from pathlib import Path


RULE_ROOT = Path(__file__).resolve().parents[2] / "rule"


def test_rule_has_no_wall_clock_reads() -> None:
    for path in sorted(RULE_ROOT.glob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Attribute):
                if isinstance(func.value, ast.Name) and func.value.id == "time" and func.attr == "time":
                    raise AssertionError(f"time.time read found in {path}")
                if isinstance(func.value, ast.Name) and func.value.id == "datetime":
                    assert func.attr not in {"now", "today", "utcnow"}
                if isinstance(func.value, ast.Attribute) and func.value.attr == "datetime":
                    assert func.attr not in {"now", "today", "utcnow"}
