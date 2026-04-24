from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from audit import canonicalize


class ScreenConfigError(ValueError):
    """Raised when Screen configuration is missing or invalid."""


@dataclass(frozen=True)
class ScreenConfig:
    config_version: str
    max_candidate_compute_usd: float
    compute_cost_per_bar_usd: float
    compute_cost_per_trade_usd: float
    data_read_cost_usd: float
    min_trades: int
    min_signal_to_noise: float
    noise_floor: float
    max_turnover_per_bar: float
    round_trip_cost_bps: float
    max_cost_to_gross_return: float

    def __post_init__(self) -> None:
        if not isinstance(self.config_version, str) or not self.config_version:
            raise ScreenConfigError("config_version must be a non-empty string")
        _non_negative(self.max_candidate_compute_usd, "max_candidate_compute_usd")
        _non_negative(self.compute_cost_per_bar_usd, "compute_cost_per_bar_usd")
        _non_negative(self.compute_cost_per_trade_usd, "compute_cost_per_trade_usd")
        _non_negative(self.data_read_cost_usd, "data_read_cost_usd")
        if not isinstance(self.min_trades, int) or self.min_trades < 0:
            raise ScreenConfigError("min_trades must be a non-negative int")
        _non_negative(self.noise_floor, "noise_floor")
        _non_negative(self.max_turnover_per_bar, "max_turnover_per_bar")
        _non_negative(self.round_trip_cost_bps, "round_trip_cost_bps")
        _non_negative(self.max_cost_to_gross_return, "max_cost_to_gross_return")

    def as_dict(self) -> dict[str, Any]:
        return {
            "config_version": self.config_version,
            "max_candidate_compute_usd": self.max_candidate_compute_usd,
            "compute_cost_per_bar_usd": self.compute_cost_per_bar_usd,
            "compute_cost_per_trade_usd": self.compute_cost_per_trade_usd,
            "data_read_cost_usd": self.data_read_cost_usd,
            "min_trades": self.min_trades,
            "min_signal_to_noise": self.min_signal_to_noise,
            "noise_floor": self.noise_floor,
            "max_turnover_per_bar": self.max_turnover_per_bar,
            "round_trip_cost_bps": self.round_trip_cost_bps,
            "max_cost_to_gross_return": self.max_cost_to_gross_return,
        }


def config_hash(config: ScreenConfig) -> str:
    import hashlib

    return hashlib.sha256(canonicalize(config.as_dict())).hexdigest()


def load_screen_config(config_path: Path | str | None = None) -> ScreenConfig:
    if config_path is None:
        config_path = Path(__file__).resolve().parents[1] / "config" / "screen.yaml"
    path = Path(config_path)
    if not path.exists():
        raise ScreenConfigError(f"missing Screen config: {path}")

    text = path.read_text()
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, UnicodeDecodeError):
        data = _load_simple_yaml_mapping(text)

    raw = data.get("screen", data)
    if not isinstance(raw, dict):
        raise ScreenConfigError("screen config must be a mapping")
    required = set(ScreenConfig.__dataclass_fields__)
    missing = required - set(raw.keys())
    extra = set(raw.keys()) - required
    if missing or extra:
        raise ScreenConfigError(
            f"screen config keys mismatch; missing={sorted(missing)}, extra={sorted(extra)}"
        )
    return ScreenConfig(
        config_version=str(raw["config_version"]),
        max_candidate_compute_usd=float(raw["max_candidate_compute_usd"]),
        compute_cost_per_bar_usd=float(raw["compute_cost_per_bar_usd"]),
        compute_cost_per_trade_usd=float(raw["compute_cost_per_trade_usd"]),
        data_read_cost_usd=float(raw["data_read_cost_usd"]),
        min_trades=int(raw["min_trades"]),
        min_signal_to_noise=float(raw["min_signal_to_noise"]),
        noise_floor=float(raw["noise_floor"]),
        max_turnover_per_bar=float(raw["max_turnover_per_bar"]),
        round_trip_cost_bps=float(raw["round_trip_cost_bps"]),
        max_cost_to_gross_return=float(raw["max_cost_to_gross_return"]),
    )


def _non_negative(value: float, field: str) -> None:
    if not isinstance(value, (int, float)) or float(value) < 0:
        raise ScreenConfigError(f"{field} must be a non-negative number")


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
