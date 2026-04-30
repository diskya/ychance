from __future__ import annotations

import ast
from pathlib import Path


ORIGINALITY_ROOT = Path(__file__).resolve().parents[2] / "originality"


def _module_paths() -> list[Path]:
    return sorted(ORIGINALITY_ROOT.glob("*.py"))


def test_originality_has_no_direct_rawstore_imports() -> None:
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


def test_originality_does_not_import_llm_clients() -> None:
    forbidden = {"openai", "anthropic"}
    for path in _module_paths():
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[0] not in forbidden
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                assert module.split(".")[0] not in forbidden
