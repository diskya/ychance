from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from access import AccessLayer, WindowReservationBook
from audit import AuditLog
from partitions import (
    PartitionConfig,
    PartitionConfigError,
    PartitionPoint,
    PartitionWindow,
    assignment_hash,
    derive_partition_assignment,
    load_partition_assignment,
    load_partitions_config,
)
from pipeline import ArtifactStore
from rawstore import RawStore


SPEC_5 = "5" * 64
SPEC_6 = "6" * 64
BASE_TIME = datetime(2024, 1, 1, tzinfo=timezone.utc)


def tick(offset: int) -> datetime:
    return BASE_TIME + timedelta(minutes=offset)


class SeriesRegistry:
    def __init__(self, series_by_ref: dict[str, list[float]]) -> None:
        self._series_by_ref = {ref: tuple(values) for ref, values in series_by_ref.items()}

    def resolve(self, spec_ref: str, t: datetime, access: AccessLayer) -> float:
        del access
        index = int((t.astimezone(timezone.utc) - BASE_TIME).total_seconds() // 60)
        return float(self._series_by_ref[spec_ref][index])


@pytest.fixture
def audit(tmp_path: Path) -> AuditLog:
    return AuditLog(tmp_path / "audit")


@pytest.fixture
def rawstore(tmp_path: Path):
    store = RawStore(tmp_path / "rawstore")
    try:
        yield store
    finally:
        store.close()


@pytest.fixture
def reservations(tmp_path: Path):
    book = WindowReservationBook(tmp_path / "reservations")
    try:
        yield book
    finally:
        book.close()


@pytest.fixture
def access(
    rawstore: RawStore,
    audit: AuditLog,
    reservations: WindowReservationBook,
) -> AccessLayer:
    return AccessLayer(
        rawstore,
        audit,
        cycle_id="partition-cycle",
        max_reads_per_cycle=1000,
        reservation_book=reservations,
    )


@pytest.fixture
def artifacts(tmp_path: Path):
    store = ArtifactStore(tmp_path / "artifacts")
    try:
        yield store
    finally:
        store.close()


def _config(**overrides) -> PartitionConfig:
    values = {
        "config_version": "test-partitions",
        "partition_count": 2,
        "summary_window_bars": 1,
        "summary_statistics": ("last",),
        "fingerprint_quantiles": (0.0, 0.5, 1.0),
        "max_iterations": 25,
        "convergence_tolerance": 0.0,
        "standardize_epsilon": 0.000000000001,
    }
    values.update(overrides)
    return PartitionConfig(**values)


def test_derivation_is_deterministic_and_hash_stable(
    artifacts: ArtifactStore,
    access: AccessLayer,
) -> None:
    registry = SeriesRegistry(
        {
            SPEC_5: [0, 0, 0, 0, 10, 10, 10, 10],
            SPEC_6: [1, 1, 1, 1, 11, 11, 11, 11],
        }
    )
    window = PartitionWindow(tick(0).isoformat(), tick(7).isoformat())
    config = _config(summary_statistics=("mean", "last"))

    first = derive_partition_assignment(
        registry=registry,
        access=access,
        artifacts=artifacts,
        window=window,
        step_seconds=60,
        state_spec_refs=(SPEC_5, SPEC_6),
        config=config,
    )
    second = derive_partition_assignment(
        registry=registry,
        access=access,
        artifacts=artifacts,
        window=window,
        step_seconds=60,
        state_spec_refs=(SPEC_5, SPEC_6),
        config=config,
    )

    assert first.assignment_hash == second.assignment_hash
    assert artifacts.has(first.assignment_hash)
    assert assignment_hash(first.assignment) == first.assignment_hash
    loaded = load_partition_assignment(artifacts.get(first.assignment_hash))
    assert loaded.as_dict() == first.assignment.as_dict()


def test_tags_are_canonical_and_fingerprints_are_statistical(
    artifacts: ArtifactStore,
    access: AccessLayer,
) -> None:
    registry = SeriesRegistry({SPEC_5: [0, 0, 0, 10, 10, 10]})

    result = derive_partition_assignment(
        registry=registry,
        access=access,
        artifacts=artifacts,
        window=PartitionWindow(tick(0).isoformat(), tick(5).isoformat()),
        step_seconds=60,
        state_spec_refs=(SPEC_5,),
        config=_config(),
    )

    assignment_ids = {item.partition_id for item in result.assignment.assignments}
    assert assignment_ids == {"partition_0", "partition_1"}
    assert [item.partition_id for item in result.assignment.fingerprints] == [
        "partition_0",
        "partition_1",
    ]
    assert sum(item.count for item in result.assignment.fingerprints) == 6
    for fingerprint in result.assignment.fingerprints:
        assert fingerprint.weight > 0
        assert len(fingerprint.centroid) == 1
        assert len(fingerprint.std) == 1
        assert [item.q for item in fingerprint.quantiles] == [0.0, 0.5, 1.0]
        assert all(len(item.values) == 1 for item in fingerprint.quantiles)


def test_config_validation_and_loading(tmp_path: Path) -> None:
    with pytest.raises(PartitionConfigError, match="partition_count"):
        _config(partition_count=0)
    with pytest.raises(PartitionConfigError, match="unsupported"):
        _config(summary_statistics=("unsupported_stat",))
    with pytest.raises(PartitionConfigError, match="sorted"):
        _config(fingerprint_quantiles=(0.5, 0.1))
    with pytest.raises(ValueError, match="partition ids"):
        PartitionPoint(t=tick(0).isoformat(), partition_id="bad_id")

    path = tmp_path / "partitions.yaml"
    path.write_text(
        "\n".join(
            [
                "partitions:",
                "  config_version: loaded-partitions",
                "  partition_count: 2",
                "  summary_window_bars: 3",
                "  summary_statistics: [mean, std, last]",
                "  fingerprint_quantiles: [0.1, 0.5, 0.9]",
                "  max_iterations: 50",
                "  convergence_tolerance: 0.000001",
                "  standardize_epsilon: 0.000001",
            ]
        )
    )

    loaded = load_partitions_config(path)

    assert loaded.config_version == "loaded-partitions"
    assert loaded.summary_statistics == ("mean", "std", "last")
    assert loaded.fingerprint_quantiles == (0.1, 0.5, 0.9)
