"""Tests for prompt generation."""

from propose import make_adjudicate_prompt, make_draft_prompt


def test_make_draft_prompt_basic():
    """Test that draft prompt is generated without error."""
    prompt = make_draft_prompt(
        slice_description="recent price data",
        available_specs=["spec_id_1", "spec_id_2"],
    )
    assert isinstance(prompt, str)
    assert "rule" in prompt.lower()
    assert "spec_id_1" in prompt


def test_make_draft_prompt_with_anti_patterns():
    """Test draft prompt with anti-patterns."""
    anti_patterns = [
        {"description": "avoid redundant conditions"},
        {"description": "avoid zero multipliers"},
    ]
    prompt = make_draft_prompt(
        slice_description="test",
        available_specs=[],
        anti_patterns=anti_patterns,
    )
    assert "avoid redundant" in prompt
    assert "avoid zero" in prompt


def test_make_draft_prompt_with_live_groundings():
    """Test draft prompt with live rule groundings."""
    groundings = [
        {"spec_ref": "a" * 64, "assertion": {"kind": "sign"}},
    ]
    prompt = make_draft_prompt(
        slice_description="test",
        available_specs=[],
        live_rule_groundings=groundings,
    )
    assert "originality" in prompt.lower() or "existing" in prompt.lower()


def test_make_adjudicate_prompt_basic():
    """Test that adjudicate prompt is generated without error."""
    import json
    candidates = [{"id": 1}, {"id": 2}]
    prompt = make_adjudicate_prompt(
        candidates_json=json.dumps(candidates),
        candidate_count=2,
    )
    assert isinstance(prompt, str)
    assert "review" in prompt.lower() or "candidates" in prompt.lower()
    assert "2" in prompt


def test_make_adjudicate_prompt_with_performance_hint():
    """Test adjudicate prompt with performance context."""
    import json
    candidates = []
    prompt = make_adjudicate_prompt(
        candidates_json=json.dumps(candidates),
        candidate_count=0,
        performance_hint="Expected execution time <100ms per candidate",
    )
    assert "execution time" in prompt
