from __future__ import annotations

import ast
import sys
from pathlib import Path


REPRESENT_ROOT = Path(__file__).resolve().parents[2] / "represent"
TEST_ROOT = Path(__file__).resolve().parents[1]


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


def test_represent_import_exposes_qwen_client_without_openai_import() -> None:
    sys.modules.pop("openai", None)
    import represent

    assert hasattr(represent, "QwenOpenAICompatibleClient")
    assert "openai" not in sys.modules


def test_tests_do_not_instantiate_qwen_client() -> None:
    for path in sorted(TEST_ROOT.rglob("test_*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Name):
                assert func.id != "QwenOpenAICompatibleClient"
            if isinstance(func, ast.Attribute):
                assert func.attr != "QwenOpenAICompatibleClient"
