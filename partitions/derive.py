from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Sequence

import numpy as np

from .assignment import (
    PARTITION_ARTIFACT_VERSION,
    FingerprintQuantile,
    PartitionAssignment,
    PartitionFingerprint,
    PartitionPoint,
    PartitionWindow,
    assignment_hash,
    bar_times,
    write_partition_assignment,
)
from .config import PartitionConfig, config_hash, load_partitions_config


@dataclass(frozen=True)
class PartitionDerivationResult:
    assignment: PartitionAssignment
    assignment_hash: str


def derive_partition_assignment(
    *,
    registry: Any,
    access: Any,
    artifacts: Any,
    window: PartitionWindow,
    step_seconds: int,
    state_spec_refs: Sequence[str],
    config: PartitionConfig | None = None,
) -> PartitionDerivationResult:
    config = load_partitions_config() if config is None else config
    refs = _validate_state_refs(state_spec_refs)
    start, end = window.as_tuple()
    times = bar_times(start, end, step_seconds)
    if not times:
        raise ValueError("partition derivation window produced no timestamps")

    vectors = _state_vectors(
        registry=registry,
        access=access,
        times=times,
        window_start=start,
        step_seconds=step_seconds,
        state_spec_refs=refs,
        config=config,
    )
    labels = _cluster_deterministically(vectors, config)
    fingerprints = _fingerprints(
        vectors,
        labels,
        quantiles=config.fingerprint_quantiles,
    )
    assignment = PartitionAssignment(
        artifact_version=PARTITION_ARTIFACT_VERSION,
        config_version=config.config_version,
        config_hash=config_hash(config),
        state_spec_refs=refs,
        summary_statistics=config.summary_statistics,
        summary_window_bars=config.summary_window_bars,
        source_window=window,
        step_seconds=step_seconds,
        assignments=tuple(
            PartitionPoint(t=t.isoformat(), partition_id=f"partition_{int(label)}")
            for t, label in zip(times, labels, strict=True)
        ),
        fingerprints=fingerprints,
        fingerprint_quantiles=config.fingerprint_quantiles,
    )
    stored_hash = write_partition_assignment(artifacts, assignment)
    expected_hash = assignment_hash(assignment)
    if stored_hash != expected_hash:
        raise ValueError("partition assignment artifact hash mismatch")
    return PartitionDerivationResult(assignment=assignment, assignment_hash=stored_hash)


def _validate_state_refs(state_spec_refs: Sequence[str]) -> tuple[str, ...]:
    refs = tuple(str(item) for item in state_spec_refs)
    if not refs or any(not item for item in refs):
        raise ValueError("state_spec_refs must contain non-empty strings")
    if len(set(refs)) != len(refs):
        raise ValueError("state_spec_refs must be unique")
    return refs


def _state_vectors(
    *,
    registry: Any,
    access: Any,
    times: tuple[datetime, ...],
    window_start: datetime,
    step_seconds: int,
    state_spec_refs: tuple[str, ...],
    config: PartitionConfig,
) -> np.ndarray:
    rows: list[list[float]] = []
    step = timedelta(seconds=step_seconds)
    for t in times:
        t0 = max(window_start, t - (config.summary_window_bars - 1) * step)
        row: list[float] = []
        for spec_ref in state_spec_refs:
            values = _series_values(registry, spec_ref, t0, t, access, step_seconds)
            row.extend(_summaries(values, config.summary_statistics))
        rows.append(row)
    matrix = np.asarray(rows, dtype=float)
    if matrix.ndim != 2 or matrix.shape[0] == 0 or matrix.shape[1] == 0:
        raise ValueError("state summary matrix must be two-dimensional and non-empty")
    if not np.isfinite(matrix).all():
        raise ValueError("state summary matrix contains non-finite values")
    return matrix


def _series_values(
    registry: Any,
    spec_ref: str,
    t0: datetime,
    t1: datetime,
    access: Any,
    step_seconds: int,
) -> np.ndarray:
    series = getattr(registry, "series", None)
    if callable(series):
        raw = series(spec_ref, t0, t1, access)
        values = np.asarray(raw, dtype=float).reshape(-1)
    else:
        values = np.asarray(
            [_value_at(registry, spec_ref, t, access) for t in bar_times(t0, t1, step_seconds)],
            dtype=float,
        ).reshape(-1)
    if values.size == 0:
        raise ValueError("registered state series returned no values")
    if not np.isfinite(values).all():
        raise ValueError("registered state series contains non-finite values")
    return values


def _value_at(registry: Any, spec_ref: str, t: datetime, access: Any) -> float:
    for method_name in ("resolve", "evaluate", "at"):
        method = getattr(registry, method_name, None)
        if callable(method):
            return float(method(spec_ref, t, access))
    raise TypeError("registry must expose series(), resolve(), evaluate(), or at()")


def _summaries(values: np.ndarray, summary_statistics: tuple[str, ...]) -> list[float]:
    out: list[float] = []
    for stat in summary_statistics:
        if stat == "mean":
            out.append(float(np.mean(values)))
        elif stat == "std":
            out.append(float(np.std(values)))
        elif stat == "min":
            out.append(float(np.min(values)))
        elif stat == "max":
            out.append(float(np.max(values)))
        elif stat == "last":
            out.append(float(values[-1]))
        elif stat == "delta":
            out.append(float(values[-1] - values[0]))
        else:
            raise ValueError(f"unsupported summary statistic {stat}")
    return out


def _cluster_deterministically(matrix: np.ndarray, config: PartitionConfig) -> np.ndarray:
    unique_count = np.unique(matrix, axis=0).shape[0]
    k = min(config.partition_count, matrix.shape[0], unique_count)
    if k <= 1:
        return np.zeros(matrix.shape[0], dtype=int)
    standardized = _standardize(matrix, config.standardize_epsilon)
    centers = _initial_centers(standardized, k)
    labels = np.zeros(standardized.shape[0], dtype=int)
    for _ in range(config.max_iterations):
        distances = ((standardized[:, None, :] - centers[None, :, :]) ** 2).sum(axis=2)
        next_labels = np.argmin(distances, axis=1)
        next_labels = _repair_empty_labels(standardized, centers, next_labels, k)
        next_centers = np.vstack(
            [standardized[next_labels == label].mean(axis=0) for label in range(k)]
        )
        shift = float(np.max(np.abs(next_centers - centers)))
        labels = next_labels
        centers = next_centers
        if shift <= config.convergence_tolerance:
            break
    return _canonicalize_labels(centers, labels)


def _standardize(matrix: np.ndarray, epsilon: float) -> np.ndarray:
    center = matrix.mean(axis=0)
    scale = matrix.std(axis=0)
    scale = np.where(scale < epsilon, 1.0, scale)
    return (matrix - center) / scale


def _initial_centers(matrix: np.ndarray, k: int) -> np.ndarray:
    order = _lexsort_rows(matrix)
    if k == 1:
        return matrix[[order[0]]]
    center_offsets = np.linspace(0, len(order) - 1, num=k)
    indices = [order[int(round(offset))] for offset in center_offsets]
    return matrix[indices].copy()


def _repair_empty_labels(
    matrix: np.ndarray,
    centers: np.ndarray,
    labels: np.ndarray,
    k: int,
) -> np.ndarray:
    labels = labels.copy()
    for empty in [label for label in range(k) if not np.any(labels == label)]:
        counts = np.bincount(labels, minlength=k)
        donors = [label for label in range(k) if counts[label] > 1]
        if not donors:
            continue
        donor = max(donors, key=lambda label: (counts[label], -label))
        donor_indices = np.flatnonzero(labels == donor)
        distances = ((matrix[donor_indices] - centers[donor]) ** 2).sum(axis=1)
        chosen = int(donor_indices[int(np.argmax(distances))])
        labels[chosen] = empty
    return labels


def _canonicalize_labels(centers: np.ndarray, labels: np.ndarray) -> np.ndarray:
    active = sorted(set(int(item) for item in labels), key=lambda label: tuple(centers[label]))
    mapping = {old: new for new, old in enumerate(active)}
    return np.asarray([mapping[int(item)] for item in labels], dtype=int)


def _lexsort_rows(matrix: np.ndarray) -> np.ndarray:
    keys = [matrix[:, col] for col in reversed(range(matrix.shape[1]))]
    return np.lexsort(keys)


def _fingerprints(
    matrix: np.ndarray,
    labels: np.ndarray,
    *,
    quantiles: tuple[float, ...],
) -> tuple[PartitionFingerprint, ...]:
    fingerprints: list[PartitionFingerprint] = []
    total = int(matrix.shape[0])
    for label in sorted(set(int(item) for item in labels)):
        subset = matrix[labels == label]
        fingerprints.append(
            PartitionFingerprint(
                partition_id=f"partition_{label}",
                count=int(subset.shape[0]),
                weight=_round_float(subset.shape[0] / total),
                centroid=_round_vector(subset.mean(axis=0)),
                mean=_round_vector(subset.mean(axis=0)),
                std=_round_vector(subset.std(axis=0)),
                min=_round_vector(subset.min(axis=0)),
                max=_round_vector(subset.max(axis=0)),
                quantiles=tuple(
                    FingerprintQuantile(
                        q=_round_float(q),
                        values=_round_vector(np.quantile(subset, q, axis=0)),
                    )
                    for q in quantiles
                ),
            )
        )
    return tuple(fingerprints)


def _round_vector(values: np.ndarray) -> tuple[float, ...]:
    return tuple(_round_float(float(item)) for item in np.asarray(values, dtype=float).reshape(-1))


def _round_float(raw_float: float) -> float:
    rounded = round(float(raw_float), 12)
    if rounded == -0.0:
        return 0.0
    return rounded
