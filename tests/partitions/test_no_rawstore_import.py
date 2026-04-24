from __future__ import annotations

import ast
from pathlib import Path


PARTITIONS_ROOT = Path(__file__).resolve().parents[2] / "partitions"


def test_partitions_has_no_direct_rawstore_imports() -> None:
    for path in sorted(PARTITIONS_ROOT.glob("*.py")):
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
