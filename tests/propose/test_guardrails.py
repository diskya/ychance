"""Tests for §0 and architecture guardrails."""

import re
from pathlib import Path

import pytest


def test_propose_no_blocklisted_tokens():
    """Test that propose/ contains no blocklisted finance vocabulary.

    This checks the prompts and all helper modules for inherited finance terms.
    """
    from tests.rule.test_op_names_primitive import BLOCKLIST

    propose_root = Path(__file__).resolve().parents[2] / "propose"
    token_re = re.compile(r"\b(" + "|".join(sorted(BLOCKLIST)) + r")\b", re.IGNORECASE)

    for path in sorted(propose_root.glob("*.py")):
        text = path.read_text()
        match = token_re.search(text)
        assert match is None, f"{path.name} contains blocklisted token {match.group(0)!r}"


def test_propose_no_direct_rawstore_import():
    """Test that propose/ does not directly import rawstore."""
    propose_root = Path(__file__).resolve().parents[2] / "propose"

    for path in sorted(propose_root.glob("*.py")):
        text = path.read_text()
        # Check for direct imports like "from rawstore" or "import rawstore"
        assert "from rawstore" not in text, f"{path.name} imports rawstore directly"
        assert "import rawstore" not in text, f"{path.name} imports rawstore directly"
