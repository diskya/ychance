from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from audit import canonicalize


class PartitionConfigError(ValueError):
    """Raised when partition derivation configuration is missing or invalid."""


ALLOWED_SUMMARY_STATISTICS = frozenset({"mean", "std", "min", "max", "last", "delta"})


@dataclass(frozen=True)
class PartitionConfig:
    config_version: str
    partition_count: int
    summary_window_bars: int
    summary_statistics: tuple[str, ...]
    fingerprint_quantiles: tuple[float, ...]
    max_iterations: int
    convergence_tolerance: float
    standardize_epsilon: float

    def __post_init__(self) -> None:
        if not isinstance(self.config_version, str) or not self.config_version:
            raise PartitionConfigError("config_version must be a non-empty string")
        _positive_int(self.partition_count, "partition_count")
        _positive_int(self.summary_window_bars, "summary_window_bars")
        _positive_int(self.max_iterations, "max_iterations")
        _non_negative(self.convergence_tolerance, "convergence_tolerance")
        if (
            not isinstance(self.standardize_epsilon, (int, float))
            or float(self.standardize_epsilon) <= 0
        ):
            raise PartitionConfigError("standardize_epsilon must be > 0")

        stats = tuple(str(item) for item in self.summary_statistics)
        if not stats:
            raise PartitionConfigError("summary_statistics must not be empty")
        unknown = set(stats) - ALLOWED_SUMMARY_STATISTICS
        if unknown:
            raise PartitionConfigError(
                f"summary_statistics contains unsupported values: {sorted(unknown)}"
            )
        object.__setattr__(self, "summary_statistics", stats)

        quantiles = tuple(float(item) for item in self.fingerprint_quantiles)
        if not quantiles:
            raise PartitionConfigError("fingerprint_quantiles must not be empty")
        if any(item < 0.0 or item > 1.0 for item in quantiles):
            raise PartitionConfigError("fingerprint_quantiles must be in [0, 1]")
        if tuple(sorted(quantiles)) != quantiles:
            raise PartitionConfigError("fingerprint_quantiles must be sorted")
        object.__setattr__(self, "fingerprint_quantiles", quantiles)

    def as_dict(self) -> dict[str, Any]:
        return {
            "config_version": self.config_version,
            "partition_count": self.partition_count,
            "summary_window_bars": self.summary_window_bars,
            "summary_statistics": list(self.summary_statistics),
            "fingerprint_quantiles": list(self.fingerprint_quantiles),
            "max_iterations": self.max_iterations,
            "convergence_tolerance": self.convergence_tolerance,
            "standardize_epsilon": self.standardize_epsilon,
        }


def config_hash(config: PartitionConfig) -> str:
    return hashlib.sha256(canonicalize(config.as_dict())).hexdigest()


def load_partitions_config(config_path: Path | str | None = None) -> PartitionConfig:
    if config_path is None:
        config_path = Path(__file__).resolve().parents[1] / "config" / "partitions.yaml"
    path = Path(config_path)
    if not path.exists():
        raise PartitionConfigError(f"missing partitions config: {path}")

    text = path.read_text()
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, UnicodeDecodeError):
        data = _load_simple_yaml_mapping(text)

    raw = data.get("partitions", data)
    if not isinstance(raw, dict):
        raise PartitionConfigError("partitions config must be a mapping")
    required = set(PartitionConfig.__dataclass_fields__)
    missing = required - set(raw.keys())
    extra = set(raw.keys()) - required
    if missing or extra:
        raise PartitionConfigError(
            f"partitions config keys mismatch; missing={sorted(missing)}, extra={sorted(extra)}"
        )
    return PartitionConfig(
        config_version=str(raw["config_version"]),
        partition_count=int(raw["partition_count"]),
        summary_window_bars=int(raw["summary_window_bars"]),
        summary_statistics=tuple(_as_list(raw["summary_statistics"])),
        fingerprint_quantiles=tuple(float(item) for item in _as_list(raw["fingerprint_quantiles"])),
        max_iterations=int(raw["max_iterations"]),
        convergence_tolerance=float(raw["convergence_tolerance"]),
        standardize_epsilon=float(raw["standardize_epsilon"]),
    )


def _positive_int(raw: int, field: str) -> None:
    if not isinstance(raw, int) or raw <= 0:
        raise PartitionConfigError(f"{field} must be a positive int")


def _non_negative(raw: float, field: str) -> None:
    if not isinstance(raw, (int, float)) or float(raw) < 0:
        raise PartitionConfigError(f"{field} must be a non-negative number")


def _as_list(raw: Any) -> list[Any]:
    if isinstance(raw, list):
        return raw
    if isinstance(raw, tuple):
        return list(raw)
    raise PartitionConfigError("configured sequence values must be lists")


def _load_simple_yaml_mapping(text: str) -> dict[str, Any]:
    root: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-1, root)]
    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        line = raw_line.strip()
        if ":" not in line:
            continue
        key, scalar_text = line.split(":", 1)
        key = key.strip()
        scalar_text = scalar_text.split("#", 1)[0].strip()
        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        if scalar_text == "":
            child: dict[str, Any] = {}
            parent[key] = child
            stack.append((indent, child))
        else:
            parent[key] = _parse_scalar(scalar_text)
    return root


def _parse_scalar(scalar_text: str) -> Any:
    if scalar_text in {"true", "false"}:
        return scalar_text == "true"
    if scalar_text.startswith("[") and scalar_text.endswith("]"):
        inner = scalar_text[1:-1].strip()
        if not inner:
            return []
        return [_parse_scalar(item.strip()) for item in inner.split(",")]
    if (
        (scalar_text.startswith('"') and scalar_text.endswith('"'))
        or (scalar_text.startswith("'") and scalar_text.endswith("'"))
    ):
        return scalar_text[1:-1]
    try:
        return int(scalar_text)
    except ValueError:
        pass
    try:
        return float(scalar_text)
    except ValueError:
        return scalar_text
