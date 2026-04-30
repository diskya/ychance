from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import numpy as np
import pytest

from audit import canonicalize
from pattern import (
    DEFAULT_ASSERTION_OPS,
    DEFAULT_SCOPE_OPS,
    PatternValidationError,
    finalize_pattern,
    load_pattern,
    serialize_pattern,
)


SPEC_REF = "a" * 64
BASE_TIME = datetime(2026, 4, 23, 12, 0, 0, tzinfo=timezone.utc)


def _body(**overrides) -> dict:
    body = {
        "spec_ref": SPEC_REF,
        "assertion": {"kind": "in_range", "args": {"lo": 1.0, "hi": 3.0}},
        "scope": {"kind": "all", "args": {}},
        "observation_window": {
            "t0": BASE_TIME.isoformat(),
            "t1": datetime(2026, 4, 23, 13, 0, 0, tzinfo=timezone.utc).isoformat(),
        },
        "replication_protocol": {
            "kind": "fixed_windows",
            "args": {
                "pass_threshold": 1.0,
                "windows": [
                    {
                        "t0": datetime(2026, 4, 24, 12, 0, 0, tzinfo=timezone.utc).isoformat(),
                        "t1": datetime(2026, 4, 24, 13, 0, 0, tzinfo=timezone.utc).isoformat(),
                    }
                ],
            },
        },
    }
    body.update(overrides)
    return body


def test_pattern_id_is_stable_and_folds_op_versions() -> None:
    first = finalize_pattern(_body())
    second = finalize_pattern(_body())

    assert first["pattern_id"] == second["pattern_id"]

    shifted_assertions = dict(DEFAULT_ASSERTION_OPS)
    shifted_assertions["in_range"] = replace(
        shifted_assertions["in_range"],
        op_version="2",
    )
    shifted_scopes = dict(DEFAULT_SCOPE_OPS)
    shifted_scopes["all"] = replace(shifted_scopes["all"], op_version="2")

    assert finalize_pattern(_body(), assertion_registry=shifted_assertions)[
        "pattern_id"
    ] != first["pattern_id"]
    assert finalize_pattern(_body(), scope_registry=shifted_scopes)[
        "pattern_id"
    ] != first["pattern_id"]


def test_round_trip_serialization_is_byte_identical() -> None:
    finalized = finalize_pattern(_body())
    pattern = load_pattern(finalized)

    raw = serialize_pattern(pattern)
    loaded_again = load_pattern(raw)

    assert raw == canonicalize(finalized)
    assert serialize_pattern(loaded_again) == raw
    assert loaded_again.as_dict() == finalized


def test_load_rejects_wrong_pattern_id() -> None:
    finalized = finalize_pattern(_body())
    finalized["pattern_id"] = "0" * 64

    with pytest.raises(PatternValidationError, match="pattern_id"):
        load_pattern(finalized)


class RecordingRegistry:
    def __init__(self, value) -> None:
        self.value = value
        self.calls: list[tuple[str, datetime, object]] = []

    def resolve(self, spec_ref: str, t: datetime, access: object):
        self.calls.append((spec_ref, t, access))
        return self.value


def test_evaluate_uses_registry_and_access_path() -> None:
    marker_access = object()
    registry = RecordingRegistry(np.array([1.25, 2.5]))
    pattern = load_pattern(finalize_pattern(_body()))

    assert pattern.evaluate(BASE_TIME, marker_access, registry) is True
    assert registry.calls == [(SPEC_REF, BASE_TIME, marker_access)]


def test_evaluate_returns_false_when_assertion_fails() -> None:
    marker_access = object()
    registry = RecordingRegistry(np.array([1.25, 4.0]))
    pattern = load_pattern(finalize_pattern(_body()))

    assert pattern.evaluate(BASE_TIME, marker_access, registry) is False


def test_time_range_scope_blocks_resolution_outside_scope() -> None:
    marker_access = object()
    registry = RecordingRegistry(2.0)
    scoped = _body(
        scope={
            "kind": "time_range",
            "args": {
                "t0": BASE_TIME.isoformat(),
                "t1": datetime(2026, 4, 23, 12, 30, tzinfo=timezone.utc).isoformat(),
            },
        }
    )
    pattern = load_pattern(finalize_pattern(scoped))

    assert pattern.evaluate(
        datetime(2026, 4, 23, 12, 45, tzinfo=timezone.utc),
        marker_access,
        registry,
    ) is False
    assert registry.calls == []


class ScopedRegistry(RecordingRegistry):
    def __init__(self, value, scope_result: bool) -> None:
        super().__init__(value)
        self.scope_result = scope_result
        self.scope_calls: list[tuple[str, datetime, object, dict]] = []

    def scope_contains(self, spec_ref: str, t: datetime, access: object, scope: dict):
        self.scope_calls.append((spec_ref, t, access, scope))
        return self.scope_result


def test_structured_scope_can_delegate_to_registry() -> None:
    marker_access = object()
    registry = ScopedRegistry(2.0, True)
    scoped = _body(scope={"kind": "partition", "args": {"partition_id": "partition_0"}})
    pattern = load_pattern(finalize_pattern(scoped))

    assert pattern.evaluate(BASE_TIME, marker_access, registry) is True
    assert registry.scope_calls == [
        (
            SPEC_REF,
            BASE_TIME,
            marker_access,
            {"kind": "partition", "args": {"partition_id": "partition_0"}},
        )
    ]
    assert registry.calls == [(SPEC_REF, BASE_TIME, marker_access)]
