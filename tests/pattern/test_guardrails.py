from __future__ import annotations

import ast
from pathlib import Path


PATTERN_ROOT = Path(__file__).resolve().parents[2] / "pattern"
FORBIDDEN_VOCABULARY = {"position", "trade", "pnl", "entry", "exit", "horizon"}


def _module_paths() -> list[Path]:
    return sorted(PATTERN_ROOT.glob("*.py"))


def test_pattern_has_no_direct_rawstore_imports() -> None:
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


def test_pattern_has_no_trading_shaped_imports_or_definitions() -> None:
    for path in _module_paths():
        assert _is_allowed(path.stem), path
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert _is_allowed(alias.name), (path, alias.name)
                    if alias.asname is not None:
                        assert _is_allowed(alias.asname), (path, alias.asname)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                assert _is_allowed(module), (path, module)
                for alias in node.names:
                    assert _is_allowed(alias.name), (path, alias.name)
                    if alias.asname is not None:
                        assert _is_allowed(alias.asname), (path, alias.asname)
            elif isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                assert _is_allowed(node.name), (path, node.name)
            elif isinstance(node, ast.arg):
                assert _is_allowed(node.arg), (path, node.arg)
            elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                assert _is_allowed(node.id), (path, node.id)


def _is_allowed(name: str) -> bool:
    folded = name.lower()
    parts = folded.replace("-", "_").replace(".", "_").split("_")
    return all(term not in parts and term not in folded for term in FORBIDDEN_VOCABULARY)
