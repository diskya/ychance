from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from audit import canonicalize


class ValidateConfigError(ValueError):
    """Raised when Validate configuration is missing or invalid."""


@dataclass(frozen=True)
class ValidateConfig:
    config_version: str
    max_rule_compute_usd: float
    compute_cost_per_bar_usd: float
    compute_cost_per_trade_usd: float
    data_read_cost_usd: float
    outer_folds: int
    holdout_bars: int
    min_train_bars: int
    inner_folds: int
    min_gap_bars: int
    max_dependency_gap_bars: int
    round_trip_cost_bps: float
    tax_rate: float
    drawdown_penalty: float
    min_return_floor: float
    dominance_order: int
    dominance_epsilon: float
    min_challenger_pass_fraction: float
    require_strict_dominance: bool
    context_random_seed: int
    context_shift_fraction: float

    def __post_init__(self) -> None:
        if not isinstance(self.config_version, str) or not self.config_version:
            raise ValidateConfigError("config_version must be a non-empty string")
        _non_negative(self.max_rule_compute_usd, "max_rule_compute_usd")
        _non_negative(self.compute_cost_per_bar_usd, "compute_cost_per_bar_usd")
        _non_negative(self.compute_cost_per_trade_usd, "compute_cost_per_trade_usd")
        _non_negative(self.data_read_cost_usd, "data_read_cost_usd")
        _positive_int(self.outer_folds, "outer_folds")
        _positive_int(self.holdout_bars, "holdout_bars")
        _positive_int(self.min_train_bars, "min_train_bars")
        _non_negative_int(self.inner_folds, "inner_folds")
        _non_negative_int(self.min_gap_bars, "min_gap_bars")
        _non_negative_int(self.max_dependency_gap_bars, "max_dependency_gap_bars")
        _non_negative(self.round_trip_cost_bps, "round_trip_cost_bps")
        if not isinstance(self.tax_rate, (int, float)) or not 0 <= float(self.tax_rate) <= 1:
            raise ValidateConfigError("tax_rate must be in [0, 1]")
        _non_negative(self.drawdown_penalty, "drawdown_penalty")
        if not isinstance(self.min_return_floor, (int, float)) or float(self.min_return_floor) <= 0:
            raise ValidateConfigError("min_return_floor must be > 0")
        if self.dominance_order != 1:
            raise ValidateConfigError("dominance_order must be 1")
        _non_negative(self.dominance_epsilon, "dominance_epsilon")
        if (
            not isinstance(self.min_challenger_pass_fraction, (int, float))
            or not 0 <= float(self.min_challenger_pass_fraction) <= 1
        ):
            raise ValidateConfigError("min_challenger_pass_fraction must be in [0, 1]")
        if not isinstance(self.require_strict_dominance, bool):
            raise ValidateConfigError("require_strict_dominance must be a bool")
        _non_negative_int(self.context_random_seed, "context_random_seed")
        _non_negative(self.context_shift_fraction, "context_shift_fraction")

    def as_dict(self) -> dict[str, Any]:
        return {
            "config_version": self.config_version,
            "max_rule_compute_usd": self.max_rule_compute_usd,
            "compute_cost_per_bar_usd": self.compute_cost_per_bar_usd,
            "compute_cost_per_trade_usd": self.compute_cost_per_trade_usd,
            "data_read_cost_usd": self.data_read_cost_usd,
            "outer_folds": self.outer_folds,
            "holdout_bars": self.holdout_bars,
            "min_train_bars": self.min_train_bars,
            "inner_folds": self.inner_folds,
            "min_gap_bars": self.min_gap_bars,
            "max_dependency_gap_bars": self.max_dependency_gap_bars,
            "round_trip_cost_bps": self.round_trip_cost_bps,
            "tax_rate": self.tax_rate,
            "drawdown_penalty": self.drawdown_penalty,
            "min_return_floor": self.min_return_floor,
            "dominance_order": self.dominance_order,
            "dominance_epsilon": self.dominance_epsilon,
            "min_challenger_pass_fraction": self.min_challenger_pass_fraction,
            "require_strict_dominance": self.require_strict_dominance,
            "context_random_seed": self.context_random_seed,
            "context_shift_fraction": self.context_shift_fraction,
        }


def config_hash(config: ValidateConfig) -> str:
    import hashlib

    return hashlib.sha256(canonicalize(config.as_dict())).hexdigest()


def load_validate_config(config_path: Path | str | None = None) -> ValidateConfig:
    if config_path is None:
        config_path = Path(__file__).resolve().parents[1] / "config" / "validate.yaml"
    path = Path(config_path)
    if not path.exists():
        raise ValidateConfigError(f"missing Validate config: {path}")

    text = path.read_text()
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, UnicodeDecodeError):
        data = _load_simple_yaml_mapping(text)

    raw = data.get("validate", data)
    if not isinstance(raw, dict):
        raise ValidateConfigError("validate config must be a mapping")
    required = set(ValidateConfig.__dataclass_fields__)
    missing = required - set(raw.keys())
    extra = set(raw.keys()) - required
    if missing or extra:
        raise ValidateConfigError(
            f"validate config keys mismatch; missing={sorted(missing)}, extra={sorted(extra)}"
        )
    return ValidateConfig(
        config_version=str(raw["config_version"]),
        max_rule_compute_usd=float(raw["max_rule_compute_usd"]),
        compute_cost_per_bar_usd=float(raw["compute_cost_per_bar_usd"]),
        compute_cost_per_trade_usd=float(raw["compute_cost_per_trade_usd"]),
        data_read_cost_usd=float(raw["data_read_cost_usd"]),
        outer_folds=int(raw["outer_folds"]),
        holdout_bars=int(raw["holdout_bars"]),
        min_train_bars=int(raw["min_train_bars"]),
        inner_folds=int(raw["inner_folds"]),
        min_gap_bars=int(raw["min_gap_bars"]),
        max_dependency_gap_bars=int(raw["max_dependency_gap_bars"]),
        round_trip_cost_bps=float(raw["round_trip_cost_bps"]),
        tax_rate=float(raw["tax_rate"]),
        drawdown_penalty=float(raw["drawdown_penalty"]),
        min_return_floor=float(raw["min_return_floor"]),
        dominance_order=int(raw["dominance_order"]),
        dominance_epsilon=float(raw["dominance_epsilon"]),
        min_challenger_pass_fraction=float(raw["min_challenger_pass_fraction"]),
        require_strict_dominance=bool(raw["require_strict_dominance"]),
        context_random_seed=int(raw["context_random_seed"]),
        context_shift_fraction=float(raw["context_shift_fraction"]),
    )


def _non_negative(raw: float, field: str) -> None:
    if not isinstance(raw, (int, float)) or float(raw) < 0:
        raise ValidateConfigError(f"{field} must be a non-negative number")


def _positive_int(raw: int, field: str) -> None:
    if not isinstance(raw, int) or raw <= 0:
        raise ValidateConfigError(f"{field} must be a positive int")


def _non_negative_int(raw: int, field: str) -> None:
    if not isinstance(raw, int) or raw < 0:
        raise ValidateConfigError(f"{field} must be a non-negative int")


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
