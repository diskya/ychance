from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from access import AccessLayer, WindowReservationBook
from audit import AuditLog
from empirical_test import EmpiricalTest, EmpiricalTestInput
from partitions import (
    FingerprintQuantile,
    PartitionAssignment,
    PartitionFingerprint,
    PartitionPoint,
    PartitionWindow,
    write_partition_assignment,
)
from pattern import finalize_pattern
from pipeline import ArtifactStore
from rawstore import RawStore


SPEC_REF = "f" * 64
BASE_TIME = datetime(2026, 4, 1, 12, 0, 0, tzinfo=timezone.utc)


def tick(days: int) -> datetime:
    return BASE_TIME + timedelta(days=days)


def h(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _window(days: int) -> dict[str, str]:
    return {
        "t0": tick(days).isoformat(),
        "t1": (tick(days) + timedelta(hours=1)).isoformat(),
    }


def _key(window: dict[str, str], control: str | None = None) -> tuple[str, str, str | None]:
    return window["t0"], window["t1"], control


def _pattern_body(
    *,
    assertion: dict[str, Any] | None = None,
    heldouts: list[dict[str, str]] | None = None,
    threshold_band: float = 0.05,
) -> dict[str, Any]:
    return finalize_pattern(
        {
            "spec_ref": SPEC_REF,
            "assertion": assertion
            or {"kind": "quantile_ge", "args": {"p": 0.5, "threshold": 1.0}},
            "scope": {"kind": "all", "args": {}},
            "observation_window": _window(0),
            "replication_protocol": {
                "kind": "fixed_windows",
                "args": {
                    "pass_threshold": 1.0,
                    "partition_pass_threshold": 1.0,
                    "threshold_band": threshold_band,
                    "windows": heldouts or [_window(2), _window(3)],
                },
            },
        }
    )


class SyntheticRegistry:
    def __init__(
        self,
        *,
        values: dict[tuple[str, str, str | None], list[float]],
        lineages: dict[tuple[str, str, str | None], tuple[str, ...]],
    ) -> None:
        self.values = values
        self.lineages = lineages

    def empirical_value(
        self,
        *,
        spec_ref: str,
        t0: datetime,
        t1: datetime,
        access: AccessLayer,
        scope: dict[str, Any],
        control: str | None,
        seed: int | None,
    ) -> dict[str, Any] | None:
        del access, scope, seed
        assert spec_ref == SPEC_REF
        key = (t0.isoformat(), t1.isoformat(), control)
        if key not in self.values:
            if control is not None:
                return None
            raise KeyError(key)
        return {
            "value": np.asarray(self.values[key], dtype=float),
            "lineage_hashes": self.lineages.get(key, (h(f"lineage:{key}"),)),
        }


@pytest.fixture
def stack(tmp_path: Path):
    rawstore = RawStore(tmp_path / "rawstore")
    audit = AuditLog(tmp_path / "audit")
    artifacts = ArtifactStore(tmp_path / "artifacts")
    reservations = WindowReservationBook(tmp_path / "reservations")
    access = AccessLayer(
        rawstore,
        audit,
        cycle_id="bootstrap",
        max_reads_per_cycle=1000,
        reservation_book=reservations,
    )
    try:
        yield {
            "rawstore": rawstore,
            "audit": audit,
            "artifacts": artifacts,
            "reservations": reservations,
            "access": access,
        }
    finally:
        artifacts.close()
        reservations.close()
        rawstore.close()


def _audit_records(log: AuditLog) -> list[dict]:
    records: list[dict] = []
    for path in sorted(log._root.glob("*.jsonl")):
        for line in path.read_text().splitlines():
            if line:
                records.append(json.loads(line))
    return records


def _passing_registry(pattern: dict[str, Any]) -> SyntheticRegistry:
    obs = pattern["observation_window"]
    heldouts = pattern["replication_protocol"]["args"]["windows"]
    values: dict[tuple[str, str, str | None], list[float]] = {
        _key(obs): [1.5, 2.0],
    }
    lineages: dict[tuple[str, str, str | None], tuple[str, ...]] = {
        _key(obs): (h("obs"),),
    }
    for index, window in enumerate(heldouts):
        values[_key(window)] = [2.0, 3.0, 4.0]
        values[_key(window, "time_shuffled")] = [0.0, 0.0, 0.0]
        values[_key(window, "scope_randomized")] = [0.0, 0.0, 0.0]
        lineages[_key(window)] = (h(f"heldout:{index}"),)
    return SyntheticRegistry(values=values, lineages=lineages)


def _stage(stack: dict[str, Any], registry: SyntheticRegistry) -> EmpiricalTest:
    return EmpiricalTest(
        registry=registry,
        artifacts=stack["artifacts"],
        audit=stack["audit"],
        access=stack["access"],
    )


def test_deterministic_verdict_for_same_state_and_pattern_id(stack: dict[str, Any]) -> None:
    pattern = _pattern_body()
    registry = _passing_registry(pattern)
    stage = _stage(stack, registry)
    inputs = EmpiricalTestInput(
        cycle_id="cycle-1",
        query_time=tick(4).isoformat(),
        pattern=pattern,
    )

    first = stage.run(inputs, envelope={"cycle_id": "cycle-1", "pattern_id": pattern["pattern_id"]})
    second = stage.run(inputs, envelope={"cycle_id": "cycle-1", "pattern_id": pattern["pattern_id"]})

    assert first.outputs.verdict is True
    assert second.cache_hit is True
    assert second.outputs == first.outputs
    assert first.outputs.pattern_id == pattern["pattern_id"]
    records = [r for r in _audit_records(stack["audit"]) if r["category"] == "EmpiricalTest"]
    assert len(records) == 1
    assert records[0]["kind"] == "EmpiricalTestReport"
    assert records[0]["verdict"] is True


def test_disjointness_failure_is_caught(stack: dict[str, Any]) -> None:
    pattern = _pattern_body(heldouts=[_window(2)])
    registry = _passing_registry(pattern)
    shared = h("shared-lineage")
    obs = pattern["observation_window"]
    heldout = pattern["replication_protocol"]["args"]["windows"][0]
    registry.lineages[_key(obs)] = (shared,)
    registry.lineages[_key(heldout)] = (shared,)

    result = _stage(stack, registry).run(
        EmpiricalTestInput(
            cycle_id="cycle-2",
            query_time=tick(4).isoformat(),
            pattern=pattern,
        ),
        envelope={"cycle_id": "cycle-2", "pattern_id": pattern["pattern_id"]},
    )

    assert result.outputs.verdict is False
    assert result.outputs.disjointness_verdict is False
    assert result.outputs.disjointness_audit.overlap_hashes == (shared,)


@pytest.mark.parametrize(
    ("failing_control", "window_values"),
    [
        ("time_shuffled", [2.0, 3.0, 4.0]),
        ("scope_randomized", [2.0, 3.0, 4.0]),
        ("threshold_perturbed", [1.0, 1.0, 1.0]),
    ],
)
def test_each_perturbation_control_rejects_failing_synthetic_pattern(
    stack: dict[str, Any],
    failing_control: str,
    window_values: list[float],
) -> None:
    pattern = _pattern_body(heldouts=[_window(2)])
    registry = _passing_registry(pattern)
    heldout = pattern["replication_protocol"]["args"]["windows"][0]
    registry.values[_key(heldout)] = window_values
    if failing_control == "time_shuffled":
        registry.values[_key(heldout, "time_shuffled")] = window_values
    if failing_control == "scope_randomized":
        registry.values[_key(heldout, "scope_randomized")] = window_values

    report = _stage(stack, registry).run(
        EmpiricalTestInput(
            cycle_id=f"cycle-{failing_control}",
            query_time=tick(4).isoformat(),
            pattern=pattern,
        ),
        envelope={"cycle_id": f"cycle-{failing_control}", "pattern_id": pattern["pattern_id"]},
    ).outputs

    by_control = {item.control: item for item in report.perturbation_results}
    assert report.verdict is False
    assert by_control[failing_control].passed is False
    assert report.perturbation_verdict is False


def _partition_assignment(artifacts: ArtifactStore) -> str:
    assignment = PartitionAssignment(
        artifact_version="1",
        config_version="test-partitions",
        config_hash=h("partition-config"),
        state_spec_refs=(SPEC_REF,),
        summary_statistics=("last",),
        summary_window_bars=1,
        source_window=PartitionWindow(tick(1).isoformat(), tick(4).isoformat()),
        step_seconds=3600,
        assignments=(
            PartitionPoint(t=tick(2).isoformat(), partition_id="partition_0"),
            PartitionPoint(t=tick(3).isoformat(), partition_id="partition_1"),
        ),
        fingerprints=(
            PartitionFingerprint(
                partition_id="partition_0",
                count=1,
                weight=0.5,
                centroid=(0.0,),
                mean=(0.0,),
                std=(0.0,),
                min=(0.0,),
                max=(0.0,),
                quantiles=(FingerprintQuantile(q=0.5, values=(0.0,)),),
            ),
            PartitionFingerprint(
                partition_id="partition_1",
                count=1,
                weight=0.5,
                centroid=(1.0,),
                mean=(1.0,),
                std=(0.0,),
                min=(1.0,),
                max=(1.0,),
                quantiles=(FingerprintQuantile(q=0.5, values=(1.0,)),),
            ),
        ),
        fingerprint_quantiles=(0.5,),
    )
    return write_partition_assignment(artifacts, assignment)


def test_partition_results_are_included(stack: dict[str, Any]) -> None:
    pattern = _pattern_body()
    registry = _passing_registry(pattern)
    assignment_hash = _partition_assignment(stack["artifacts"])

    report = _stage(stack, registry).run(
        EmpiricalTestInput(
            cycle_id="cycle-partitions",
            query_time=tick(4).isoformat(),
            pattern=pattern,
            partition_assignment_hash=assignment_hash,
        ),
        envelope={"cycle_id": "cycle-partitions", "pattern_id": pattern["pattern_id"]},
    ).outputs

    assert report.verdict is True
    assert [item.partition_id for item in report.partition_results] == [
        "partition_0",
        "partition_1",
    ]
    assert all(item.verdict for item in report.partition_results)
    assert report.partition_profile["partition_source"] == "assignment_artifact"
