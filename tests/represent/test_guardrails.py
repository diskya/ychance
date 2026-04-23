from __future__ import annotations

import ast
from pathlib import Path


REPRESENT_ROOT = Path(__file__).resolve().parents[2] / "represent"


def _module_paths() -> list[Path]:
    return sorted(REPRESENT_ROOT.glob("*.py"))


def test_represent_has_no_direct_rawstore_imports() -> None:
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


def test_represent_has_no_wall_clock_reads() -> None:
    for path in _module_paths():
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr in {"now", "utcnow", "time"}:
                if isinstance(func.value, ast.Name) and func.value.id in {"datetime", "time"}:
                    raise AssertionError(f"wall-clock read found in {path}")
                if isinstance(func.value, ast.Attribute) and func.value.attr in {"datetime", "time"}:
                    raise AssertionError(f"wall-clock read found in {path}")
