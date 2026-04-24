from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from audit import canonicalize


PARTITION_ARTIFACT_VERSION = "1"
_PARTITION_ID_RE = re.compile(r"^partition_(0|[1-9][0-9]*)$")


@dataclass(frozen=True)
class PartitionWindow:
    t0: str
    t1: str

    def __post_init__(self) -> None:
        start = _parse_time(self.t0, "t0")
        end = _parse_time(self.t1, "t1")
        if end < start:
            raise ValueError("partition window t1 must be >= t0")
        object.__setattr__(self, "t0", start.isoformat())
        object.__setattr__(self, "t1", end.isoformat())

    def as_tuple(self) -> tuple[datetime, datetime]:
        return _parse_time(self.t0, "t0"), _parse_time(self.t1, "t1")

    def as_dict(self) -> dict[str, str]:
        return {"t0": self.t0, "t1": self.t1}


@dataclass(frozen=True)
class PartitionPoint:
    t: str
    partition_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "t", _parse_time(self.t, "t").isoformat())
        _validate_partition_id(self.partition_id)

    def as_dict(self) -> dict[str, str]:
        return {"t": self.t, "partition_id": self.partition_id}


@dataclass(frozen=True)
class FingerprintQuantile:
    q: float
    values: tuple[float, ...]

    def __post_init__(self) -> None:
        q = float(self.q)
        if q < 0.0 or q > 1.0:
            raise ValueError("fingerprint quantile q must be in [0, 1]")
        object.__setattr__(self, "q", q)
        object.__setattr__(
            self,
            "values",
            tuple(_finite_float(item, "quantile entry") for item in self.values),
        )

    def as_dict(self) -> dict[str, Any]:
        return {"q": self.q, "values": list(self.values)}


@dataclass(frozen=True)
class PartitionFingerprint:
    partition_id: str
    count: int
    weight: float
    centroid: tuple[float, ...]
    mean: tuple[float, ...]
    std: tuple[float, ...]
    min: tuple[float, ...]
    max: tuple[float, ...]
    quantiles: tuple[FingerprintQuantile, ...]

    def __post_init__(self) -> None:
        _validate_partition_id(self.partition_id)
        if not isinstance(self.count, int) or self.count <= 0:
            raise ValueError("partition fingerprint count must be a positive int")
        weight = _finite_float(self.weight, "partition fingerprint weight")
        if weight <= 0.0 or weight > 1.0:
            raise ValueError("partition fingerprint weight must be in (0, 1]")
        object.__setattr__(self, "weight", weight)
        vectors = {
            "centroid": self.centroid,
            "mean": self.mean,
            "std": self.std,
            "min": self.min,
            "max": self.max,
        }
        lengths = {len(values) for values in vectors.values()}
        if len(lengths) != 1 or not next(iter(lengths), 0):
            raise ValueError("partition fingerprint vectors must share a non-zero length")
        for field, values in vectors.items():
            object.__setattr__(
                self,
                field,
                tuple(_finite_float(item, f"partition fingerprint {field}") for item in values),
            )
        q_values = tuple(
            item if isinstance(item, FingerprintQuantile) else FingerprintQuantile(**item)
            for item in self.quantiles
        )
        for item in q_values:
            if len(item.values) != len(self.centroid):
                raise ValueError("partition fingerprint quantile length mismatch")
        object.__setattr__(self, "quantiles", q_values)

    def as_dict(self) -> dict[str, Any]:
        return {
            "partition_id": self.partition_id,
            "count": self.count,
            "weight": self.weight,
            "centroid": list(self.centroid),
            "mean": list(self.mean),
            "std": list(self.std),
            "min": list(self.min),
            "max": list(self.max),
            "quantiles": [item.as_dict() for item in self.quantiles],
        }


@dataclass(frozen=True)
class PartitionAssignment:
    artifact_version: str
    config_version: str
    config_hash: str
    state_spec_refs: tuple[str, ...]
    summary_statistics: tuple[str, ...]
    summary_window_bars: int
    source_window: PartitionWindow
    step_seconds: int
    assignments: tuple[PartitionPoint, ...]
    fingerprints: tuple[PartitionFingerprint, ...]
    fingerprint_quantiles: tuple[float, ...]

    def __post_init__(self) -> None:
        if self.artifact_version != PARTITION_ARTIFACT_VERSION:
            raise ValueError("unsupported partition artifact version")
        if not isinstance(self.config_version, str) or not self.config_version:
            raise ValueError("partition config_version must be a non-empty string")
        if not isinstance(self.config_hash, str) or len(self.config_hash) != 64:
            raise ValueError("partition config_hash must be a 64-character string")
        refs = tuple(str(item) for item in self.state_spec_refs)
        if not refs or any(not item for item in refs):
            raise ValueError("state_spec_refs must contain non-empty strings")
        if len(set(refs)) != len(refs):
            raise ValueError("state_spec_refs must be unique")
        object.__setattr__(self, "state_spec_refs", refs)
        stats = tuple(str(item) for item in self.summary_statistics)
        if not stats or any(not item for item in stats):
            raise ValueError("summary_statistics must contain non-empty strings")
        object.__setattr__(self, "summary_statistics", stats)
        if not isinstance(self.summary_window_bars, int) or self.summary_window_bars <= 0:
            raise ValueError("summary_window_bars must be a positive int")
        window = (
            self.source_window
            if isinstance(self.source_window, PartitionWindow)
            else PartitionWindow(**self.source_window)
        )
        object.__setattr__(self, "source_window", window)
        if not isinstance(self.step_seconds, int) or self.step_seconds <= 0:
            raise ValueError("step_seconds must be a positive int")
        points = tuple(
            item if isinstance(item, PartitionPoint) else PartitionPoint(**item)
            for item in self.assignments
        )
        if not points:
            raise ValueError("partition assignments must not be empty")
        points = tuple(sorted(points, key=lambda item: _parse_time(item.t, "t")))
        times = [item.t for item in points]
        if len(set(times)) != len(times):
            raise ValueError("partition assignments must not duplicate timestamps")
        object.__setattr__(self, "assignments", points)
        fingerprints = tuple(
            item if isinstance(item, PartitionFingerprint) else _fingerprint_from_dict(item)
            for item in self.fingerprints
        )
        if not fingerprints:
            raise ValueError("partition fingerprints must not be empty")
        expected_ids = tuple(f"partition_{i}" for i in range(len(fingerprints)))
        actual_ids = tuple(item.partition_id for item in fingerprints)
        if actual_ids != expected_ids:
            raise ValueError("partition fingerprints must use consecutive canonical ids")
        assigned_ids = {item.partition_id for item in points}
        if assigned_ids != set(expected_ids):
            raise ValueError("partition assignments must cover every fingerprint id")
        object.__setattr__(self, "fingerprints", fingerprints)
        quantiles = tuple(float(item) for item in self.fingerprint_quantiles)
        if tuple(sorted(quantiles)) != quantiles:
            raise ValueError("fingerprint_quantiles must be sorted")
        object.__setattr__(self, "fingerprint_quantiles", quantiles)

    def as_dict(self) -> dict[str, Any]:
        return {
            "artifact_version": self.artifact_version,
            "config_version": self.config_version,
            "config_hash": self.config_hash,
            "state_spec_refs": list(self.state_spec_refs),
            "summary_statistics": list(self.summary_statistics),
            "summary_window_bars": self.summary_window_bars,
            "source_window": self.source_window.as_dict(),
            "step_seconds": self.step_seconds,
            "assignments": [item.as_dict() for item in self.assignments],
            "fingerprints": [item.as_dict() for item in self.fingerprints],
            "fingerprint_quantiles": list(self.fingerprint_quantiles),
        }

    def fingerprints_by_id(self) -> dict[str, PartitionFingerprint]:
        return {item.partition_id: item for item in self.fingerprints}


def assignment_hash(assignment: PartitionAssignment) -> str:
    return hashlib.sha256(serialize_assignment(assignment)).hexdigest()


def serialize_assignment(assignment: PartitionAssignment) -> bytes:
    return canonicalize(assignment.as_dict())


def write_partition_assignment(artifacts: Any, assignment: PartitionAssignment) -> str:
    stored_hash = artifacts.put(serialize_assignment(assignment))
    expected_hash = assignment_hash(assignment)
    if stored_hash != expected_hash:
        raise ValueError("partition assignment artifact hash mismatch")
    return stored_hash


def load_partition_assignment(raw: bytes | Mapping[str, Any]) -> PartitionAssignment:
    if isinstance(raw, (bytes, bytearray, memoryview)):
        data = json.loads(bytes(raw).decode("utf-8"))
    elif isinstance(raw, Mapping):
        data = dict(raw)
    else:
        raise TypeError("partition assignment must be bytes or a mapping")
    return PartitionAssignment(
        artifact_version=str(data["artifact_version"]),
        config_version=str(data["config_version"]),
        config_hash=str(data["config_hash"]),
        state_spec_refs=tuple(data["state_spec_refs"]),
        summary_statistics=tuple(data["summary_statistics"]),
        summary_window_bars=int(data["summary_window_bars"]),
        source_window=PartitionWindow(**data["source_window"]),
        step_seconds=int(data["step_seconds"]),
        assignments=tuple(PartitionPoint(**item) for item in data["assignments"]),
        fingerprints=tuple(_fingerprint_from_dict(item) for item in data["fingerprints"]),
        fingerprint_quantiles=tuple(float(item) for item in data["fingerprint_quantiles"]),
    )


def partition_id_for_window(
    assignment: PartitionAssignment,
    *,
    t0: datetime,
    t1: datetime,
) -> str:
    start = _parse_time(t0, "t0")
    end = _parse_time(t1, "t1")
    if end < start:
        raise ValueError("partition lookup window t1 must be >= t0")
    counts: dict[str, int] = {}
    for item in assignment.assignments:
        t = _parse_time(item.t, "t")
        if start <= t <= end:
            counts[item.partition_id] = counts.get(item.partition_id, 0) + 1
    if not counts:
        raise ValueError("partition assignment does not cover lookup window")
    return min(counts, key=lambda key: (-counts[key], _partition_sort_key(key)))


def assignment_profile(
    assignment: PartitionAssignment,
    *,
    assignment_hash_value: str,
    fold_partitions: tuple[dict[str, str], ...],
) -> dict[str, Any]:
    active = tuple(sorted({item["partition_id"] for item in fold_partitions}, key=_partition_sort_key))
    fingerprints = assignment.fingerprints_by_id()
    return {
        "active_partitions": list(active),
        "partition_assignment_hash": assignment_hash_value,
        "partition_source": "assignment_artifact",
        "partition_config_version": assignment.config_version,
        "partition_config_hash": assignment.config_hash,
        "partition_artifact_version": assignment.artifact_version,
        "source_window": assignment.source_window.as_dict(),
        "step_seconds": assignment.step_seconds,
        "state_spec_refs": list(assignment.state_spec_refs),
        "summary_statistics": list(assignment.summary_statistics),
        "summary_window_bars": assignment.summary_window_bars,
        "fingerprint_quantiles": list(assignment.fingerprint_quantiles),
        "fold_partitions": [dict(item) for item in fold_partitions],
        "fingerprints": [fingerprints[item].as_dict() for item in active],
    }


def fallback_profile(*, fold_ids: tuple[str, ...]) -> dict[str, Any]:
    return {
        "active_partitions": ["partition_0"],
        "partition_assignment_hash": None,
        "partition_source": "single_validate_partition",
        "partition_config_version": None,
        "partition_config_hash": None,
        "partition_artifact_version": None,
        "fold_partitions": [
            {"fold_id": fold_id, "partition_id": "partition_0"} for fold_id in fold_ids
        ],
        "fingerprints": [
            {
                "partition_id": "partition_0",
                "count": len(fold_ids),
                "weight": 1.0,
                "source": "fallback",
            }
        ],
    }


def _fingerprint_from_dict(item: Mapping[str, Any]) -> PartitionFingerprint:
    return PartitionFingerprint(
        partition_id=str(item["partition_id"]),
        count=int(item["count"]),
        weight=float(item["weight"]),
        centroid=tuple(float(raw) for raw in item["centroid"]),
        mean=tuple(float(raw) for raw in item["mean"]),
        std=tuple(float(raw) for raw in item["std"]),
        min=tuple(float(raw) for raw in item["min"]),
        max=tuple(float(raw) for raw in item["max"]),
        quantiles=tuple(
            FingerprintQuantile(q=float(raw["q"]), values=tuple(float(v) for v in raw["values"]))
            for raw in item["quantiles"]
        ),
    )


def _parse_time(raw: str | datetime, field: str) -> datetime:
    if isinstance(raw, datetime):
        dt = raw
    elif isinstance(raw, str) and raw:
        dt = datetime.fromisoformat(raw)
    else:
        raise TypeError(f"{field} must be datetime or ISO-8601 string")
    if dt.tzinfo is None:
        raise ValueError(f"{field} must be timezone-aware")
    return dt.astimezone(timezone.utc)


def _finite_float(raw: float, field: str) -> float:
    number = float(raw)
    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite")
    return number


def _validate_partition_id(raw: str) -> None:
    if not isinstance(raw, str) or _PARTITION_ID_RE.fullmatch(raw) is None:
        raise ValueError("partition ids must be named partition_0, partition_1, ...")


def _partition_sort_key(partition_id: str) -> int:
    _validate_partition_id(partition_id)
    return int(partition_id.split("_", 1)[1])


def bar_times(start: datetime, end: datetime, step_seconds: int) -> tuple[datetime, ...]:
    start = _parse_time(start, "start")
    end = _parse_time(end, "end")
    if end < start:
        raise ValueError("end must be >= start")
    if not isinstance(step_seconds, int) or step_seconds <= 0:
        raise ValueError("step_seconds must be a positive int")
    times: list[datetime] = []
    step = timedelta(seconds=step_seconds)
    t = start
    while t <= end:
        times.append(t)
        t += step
    return tuple(times)
