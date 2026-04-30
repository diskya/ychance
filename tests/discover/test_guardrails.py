from __future__ import annotations

import ast
from pathlib import Path


DISCOVER_ROOT = Path(__file__).resolve().parents[2] / "discover"
PROMPT_FORBIDDEN_VOCABULARY = {
    "momentum",
    "reversion",
    "earnings",
    "revenue",
    "profit",
    "volatility",
    "sentiment",
    "macro",
    "inflation",
    "sector",
    "industry",
    "liquidity",
}


def _module_paths() -> list[Path]:
    return sorted(DISCOVER_ROOT.glob("*.py"))


def test_discover_has_no_direct_rawstore_imports() -> None:
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


def test_discover_prompt_templates_do_not_name_target_vocabulary() -> None:
    prompts_path = DISCOVER_ROOT / "prompts.py"
    tree = ast.parse(prompts_path.read_text(), filename=str(prompts_path))
    strings = [
        node.value.lower()
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]
    for text in strings:
        for term in PROMPT_FORBIDDEN_VOCABULARY:
            assert term not in text
