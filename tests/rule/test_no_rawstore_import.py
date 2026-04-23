from __future__ import annotations

import ast
from pathlib import Path


RULE_ROOT = Path(__file__).resolve().parents[2] / "rule"


def _module_paths() -> list[Path]:
    return sorted(RULE_ROOT.glob("*.py"))


def test_rule_has_no_direct_rawstore_imports() -> None:
    for path in _module_paths():
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
