from __future__ import annotations

import dataclasses
import re
from pathlib import Path

from rule import Rule
from rule.exit_ops import DEFAULT_EXIT_OPS
from rule.predicate_ops import DEFAULT_PREDICATE_OPS


RULE_ROOT = Path(__file__).resolve().parents[2] / "rule"
NAME_RE = re.compile(r"^[a-z_][a-z0-9_]*$")
PREDICATE_ALLOWLIST = {
    "spec_ref",
    "literal",
    "and",
    "or",
    "not",
    "lt",
    "le",
    "gt",
    "ge",
    "eq",
    "ne",
    "add",
    "sub",
    "mul",
    "div",
}
EXIT_ALLOWLIST = PREDICATE_ALLOWLIST | {
    "time_since_entry",
    "realized_pnl",
    "context_still_holds",
}
BLOCKLIST = {
    "momentum",
    "reversion",
    "value",
    "quality",
    "carry",
    "trend",
    "breakout",
    "pair",
    "arbitrage",
    "alpha",
    "beta",
    "premium",
    "anomaly",
    "signal",
    "factor",
    "strategy",
    "edge",
    "pattern",
    "regime",
    "ticker",
    "sector",
    "macro",
    "earnings",
}


def test_op_names_are_primitives_only() -> None:
    for name in DEFAULT_PREDICATE_OPS:
        assert NAME_RE.match(name)
        assert name in PREDICATE_ALLOWLIST
    for name in DEFAULT_EXIT_OPS:
        assert NAME_RE.match(name)
        assert name in EXIT_ALLOWLIST


def test_rule_source_contains_no_blocklisted_tokens() -> None:
    token_re = re.compile(r"\b(" + "|".join(sorted(BLOCKLIST)) + r")\b", re.IGNORECASE)
    for path in sorted(RULE_ROOT.glob("*.py")):
        text = path.read_text()
        match = token_re.search(text)
        assert match is None, f"{path} contains blocklisted token {match.group(0)!r}"


def test_rule_has_no_free_text_field() -> None:
    forbidden = {"description", "rationale", "why", "notes", "comment", "label", "name"}
    assert forbidden.isdisjoint({field.name for field in dataclasses.fields(Rule)})
