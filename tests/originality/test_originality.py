from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from audit import AuditLog, canonicalize
from originality import (
    AntiPatternEntry,
    AntiPatternList,
    AntiPatternListError,
    FingerprintReductionMatcher,
    OriginalityFilter,
    OriginalityInput,
    build_pattern_fingerprint,
)
from pattern import finalize_pattern, load_pattern, serialize_pattern
from pipeline import ArtifactStore


SPEC_REF = "a" * 64
BASE_TIME = datetime(2026, 4, 23, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def stack(tmp_path: Path) -> dict[str, Any]:
    return {
        "artifacts": ArtifactStore(tmp_path / "artifacts"),
        "audit": AuditLog(tmp_path / "audit"),
    }


def _body(**overrides: Any) -> dict[str, Any]:
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


def _pattern(**overrides: Any) -> dict[str, Any]:
    return finalize_pattern(_body(**overrides))


def _fingerprint(pattern: dict[str, Any]):
    return build_pattern_fingerprint(load_pattern(pattern))


def _entry(
    anti_pattern_id: str,
    pattern: dict[str, Any],
    *,
    paths: tuple[str, ...] = ("assertion", "scope"),
) -> AntiPatternEntry:
    return AntiPatternEntry(
        anti_pattern_id=anti_pattern_id,
        matcher=FingerprintReductionMatcher.from_fingerprint(
            matcher_id=f"matcher-{anti_pattern_id}",
            fingerprint=_fingerprint(pattern),
            paths=paths,
        ),
    )


def _audit_records(log: AuditLog) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(log._root.glob("*.jsonl")):
        for line in path.read_text().splitlines():
            records.append(json.loads(line))
    return records


def test_reduction_matcher_is_stable_over_path_order_and_canonical_input() -> None:
    pattern = _pattern(assertion={"kind": "in_range", "args": {"hi": 3, "lo": 1}})
    fingerprint = _fingerprint(pattern)

    first = FingerprintReductionMatcher.from_fingerprint(
        matcher_id="m1",
        fingerprint=fingerprint,
        paths=("scope", "assertion"),
    )
    second = FingerprintReductionMatcher.from_fingerprint(
        matcher_id="m1",
        fingerprint=fingerprint,
        paths=("assertion", "scope"),
    )

    assert first.config() == second.config()
    assert first.match(fingerprint).matched is True
    assert first.match(fingerprint).match_hash == second.match(fingerprint).match_hash
    assert AntiPatternList((AntiPatternEntry("ap1", first),), max_size=4).version == (
        AntiPatternList((AntiPatternEntry("ap1", second),), max_size=4).version
    )


def test_stage_passes_then_rejects_after_list_mutation_without_stale_cache(
    stack: dict[str, Any],
) -> None:
    pattern = _pattern()
    anti_patterns = AntiPatternList(max_size=4)
    stage = OriginalityFilter(
        anti_patterns=anti_patterns,
        artifacts=stack["artifacts"],
        audit=stack["audit"],
    )
    inputs = OriginalityInput(cycle_id="cycle-1", pattern=pattern)

    first = stage.run(
        inputs,
        envelope={"cycle_id": "cycle-1", "pattern_id": pattern["pattern_id"]},
    )
    anti_patterns.append(_entry("ap1", pattern))
    second = stage.run(
        inputs,
        envelope={"cycle_id": "cycle-1", "pattern_id": pattern["pattern_id"]},
    )

    assert first.outputs.result == "pass"
    assert first.outputs.matched_anti_pattern is None
    assert second.cache_hit is False
    assert second.outputs.result == "reject"
    assert second.outputs.matched_anti_pattern == "ap1"


def test_bounded_list_can_be_emptied_as_a_unit() -> None:
    pattern = _pattern()
    entry = _entry("ap1", pattern)
    anti_patterns = AntiPatternList(max_size=1)
    anti_patterns.append(entry)
    full_version = anti_patterns.version

    with pytest.raises(AntiPatternListError, match="full"):
        anti_patterns.append(_entry("ap2", pattern))

    assert anti_patterns.decide(_fingerprint(pattern)).result == "reject"
    anti_patterns.clear()

    assert anti_patterns.entries == ()
    assert anti_patterns.version != full_version
    assert anti_patterns.decide(_fingerprint(pattern)).result == "pass"


def test_originality_audit_emits_required_fields(stack: dict[str, Any]) -> None:
    pattern = _pattern()
    pattern_artifact_hash = stack["artifacts"].put(serialize_pattern(load_pattern(pattern)))
    anti_patterns = AntiPatternList((_entry("ap1", pattern),), max_size=4)
    stage = OriginalityFilter(
        anti_patterns=anti_patterns,
        artifacts=stack["artifacts"],
        audit=stack["audit"],
    )

    result = stage.run(
        OriginalityInput(
            cycle_id="cycle-audit",
            pattern_artifact_hash=pattern_artifact_hash,
            observation_fingerprint_hash="b" * 64,
        ),
        envelope={"cycle_id": "cycle-audit", "pattern_id": pattern["pattern_id"]},
    )

    records = [r for r in _audit_records(stack["audit"]) if r["category"] == "Originality"]
    assert result.outputs.result == "reject"
    assert len(records) == 1
    assert records[0]["kind"] == "OriginalityRecord"
    assert records[0]["pattern_id"] == pattern["pattern_id"]
    assert records[0]["result"] == "reject"
    assert records[0]["matched_anti_pattern"] == "ap1"
    assert records[0]["anti_pattern_list_version"] == anti_patterns.version
    assert records[0]["stage"] == "Originality"
    assert records[0]["llm_cost"] == 0.0


def test_pattern_fingerprint_is_canonical_for_equivalent_pattern_body() -> None:
    first = _pattern(assertion={"kind": "in_range", "args": {"lo": 1.0, "hi": 3.0}})
    second = dict(json.loads(canonicalize(first).decode("utf-8")))

    assert _fingerprint(first) == _fingerprint(second)
