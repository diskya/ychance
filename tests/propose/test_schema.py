"""Tests for candidate schema validation."""

import pytest

from propose import CandidateValidationError, validate_candidate_shape


def test_validate_candidate_shape_requires_mapping():
    with pytest.raises(CandidateValidationError):
        validate_candidate_shape([])

    with pytest.raises(CandidateValidationError):
        validate_candidate_shape("not a dict")


def test_validate_candidate_shape_requires_all_keys():
    partial = {
        "context": {},
        "action": {},
    }
    with pytest.raises(CandidateValidationError):
        validate_candidate_shape(partial)


def test_validate_candidate_shape_accepts_valid():
    valid = {
        "context": {"nodes": [], "output": "x0"},
        "exit": {"nodes": [], "output": "x1"},
        "action": {"side": "long", "size_multiplier": 1.0},
        "action_schema_version": 1,
        "horizon_bars": 10,
        "cadence": {"kind": "fixed_step", "step_seconds": 60},
        "grounding": {"spec_ref": "a" * 64, "assertion": {"kind": "sign", "expected_sign": 1}, "window": {"t0": "2024-01-01T00:00:00+00:00", "t1": "2024-01-02T00:00:00+00:00"}},
        "price_spec_ref": "b" * 64,
    }
    # Should not raise
    validate_candidate_shape(valid)


def test_validate_candidate_shape_requires_correct_types():
    invalid_context = {
        "context": "not a dict",
        "exit": {"nodes": [], "output": "x1"},
        "action": {"side": "long", "size_multiplier": 1.0},
        "action_schema_version": 1,
        "horizon_bars": 10,
        "cadence": {"kind": "fixed_step", "step_seconds": 60},
        "grounding": {"spec_ref": "a" * 64, "assertion": {"kind": "sign", "expected_sign": 1}, "window": {}},
        "price_spec_ref": "b" * 64,
    }
    with pytest.raises(CandidateValidationError):
        validate_candidate_shape(invalid_context)


def test_validate_candidate_shape_requires_valid_horizon():
    invalid_horizon = {
        "context": {"nodes": [], "output": "x0"},
        "exit": {"nodes": [], "output": "x1"},
        "action": {"side": "long", "size_multiplier": 1.0},
        "action_schema_version": 1,
        "horizon_bars": 0,
        "cadence": {"kind": "fixed_step", "step_seconds": 60},
        "grounding": {"spec_ref": "a" * 64, "assertion": {"kind": "sign", "expected_sign": 1}, "window": {}},
        "price_spec_ref": "b" * 64,
    }
    with pytest.raises(CandidateValidationError):
        validate_candidate_shape(invalid_horizon)


def test_validate_candidate_shape_requires_64char_spec_ref():
    invalid_spec = {
        "context": {"nodes": [], "output": "x0"},
        "exit": {"nodes": [], "output": "x1"},
        "action": {"side": "long", "size_multiplier": 1.0},
        "action_schema_version": 1,
        "horizon_bars": 10,
        "cadence": {"kind": "fixed_step", "step_seconds": 60},
        "grounding": {"spec_ref": "a" * 64, "assertion": {"kind": "sign", "expected_sign": 1}, "window": {}},
        "price_spec_ref": "b" * 63,
    }
    with pytest.raises(CandidateValidationError):
        validate_candidate_shape(invalid_spec)
