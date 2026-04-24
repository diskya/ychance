from __future__ import annotations

import copy
import hashlib
import json
import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping

import numpy as np

from audit import canonicalize
from pipeline import CostCeiling, InvariantViolation, Stage, StageContext, StageResult
from rule import DEFAULT_EXIT_OPS, Rule, Trade, finalize_rule, load_rule
from rule.predicate_ops import EvalContext, coerce_scalar, execute_dag, resolve_spec_output

from .config import ValidateConfig, config_hash, load_validate_config


class ValidateCostExceeded(RuntimeError):
    """Raised before a rule would exceed its Validate cost cap."""


_ZERO_DEPENDENCY_OPS = frozenset(
    {
        "raw_get",
        "literal",
        "decode_json",
        "decode_text",
        "json_get",
        "cast_float64",
        "stack",
        "concatenate",
        "mean",
        "sum",
        "z_score",
        "llm_call",
    }
)


@dataclass(frozen=True)
class ValidateWindow:
    t0: str
    t1: str

    def __post_init__(self) -> None:
        start = _parse_time(self.t0, "t0")
        end = _parse_time(self.t1, "t1")
        if end < start:
            raise ValueError("validate window t1 must be >= t0")
        object.__setattr__(self, "t0", start.isoformat())
        object.__setattr__(self, "t1", end.isoformat())

    def as_tuple(self) -> tuple[datetime, datetime]:
        return _parse_time(self.t0, "t0"), _parse_time(self.t1, "t1")

    def as_dict(self) -> dict[str, str]:
        return {"t0": self.t0, "t1": self.t1}


@dataclass(frozen=True)
class ValidateFold:
    fold_id: str
    train_window: ValidateWindow
    gap_window: ValidateWindow | None
    holdout_window: ValidateWindow
    inner_windows: tuple[ValidateWindow, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "fold_id": self.fold_id,
            "train_window": self.train_window.as_dict(),
            "gap_window": None if self.gap_window is None else self.gap_window.as_dict(),
            "holdout_window": self.holdout_window.as_dict(),
            "inner_windows": [window.as_dict() for window in self.inner_windows],
        }


@dataclass(frozen=True)
class ValidateInput:
    cycle_id: str
    rule: Rule | Mapping[str, Any]
    validate_window: ValidateWindow
    config: ValidateConfig = field(default_factory=load_validate_config)
    screen_output_hash: str | None = None
    partition_assignment_hash: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.cycle_id, str) or not self.cycle_id:
            raise ValueError("cycle_id must be a non-empty string")
        object.__setattr__(
            self,
            "rule",
            self.rule if isinstance(self.rule, Rule) else load_rule(self.rule),
        )
        if self.screen_output_hash is not None and (
            not isinstance(self.screen_output_hash, str) or len(self.screen_output_hash) != 64
        ):
            raise ValueError("screen_output_hash must be a 64-character string or None")
        if self.partition_assignment_hash is not None and (
            not isinstance(self.partition_assignment_hash, str)
            or len(self.partition_assignment_hash) != 64
        ):
            raise ValueError("partition_assignment_hash must be a 64-character string or None")

    def as_dict(self) -> dict[str, Any]:
        assert isinstance(self.rule, Rule)
        return {
            "cycle_id": self.cycle_id,
            "rule": self.rule.to_dict(),
            "validate_window": self.validate_window.as_dict(),
            "config": self.config.as_dict(),
            "screen_output_hash": self.screen_output_hash,
            "partition_assignment_hash": self.partition_assignment_hash,
        }


@dataclass(frozen=True)
class UtilityDistribution:
    construction: str
    samples: tuple[float, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.construction, str) or not self.construction:
            raise ValueError("construction must be a non-empty string")
        normalized: list[float] = []
        for raw in self.samples:
            item = float(raw)
            if not math.isfinite(item):
                raise ValueError("utility distribution samples must be finite")
            normalized.append(item)
        object.__setattr__(self, "samples", tuple(normalized))

    def as_dict(self) -> dict[str, Any]:
        return {
            "construction": self.construction,
            "samples": list(self.samples),
        }


@dataclass(frozen=True)
class PartitionResult:
    partition_id: str
    dominance_order: int
    dominance_grid: tuple[dict[str, float], ...]
    dominates: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "partition_id": self.partition_id,
            "dominance_order": self.dominance_order,
            "dominance_grid": [dict(item) for item in self.dominance_grid],
            "dominates": self.dominates,
        }


@dataclass(frozen=True)
class ChallengerReport:
    challenger_id: str
    utility_distribution: UtilityDistribution
    partition_results: tuple[PartitionResult, ...]
    dominance_fraction: float
    result: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "challenger_id": self.challenger_id,
            "utility_distribution": self.utility_distribution.as_dict(),
            "partition_results": [item.as_dict() for item in self.partition_results],
            "dominance_fraction": self.dominance_fraction,
            "result": self.result,
        }


@dataclass(frozen=True)
class RobustnessItem:
    perturbation_id: str
    utility_distribution: UtilityDistribution

    def as_dict(self) -> dict[str, Any]:
        return {
            "perturbation_id": self.perturbation_id,
            "utility_distribution": self.utility_distribution.as_dict(),
        }


@dataclass(frozen=True)
class RobustnessProfile:
    items: tuple[RobustnessItem, ...]

    def as_dict(self) -> dict[str, Any]:
        return {"items": [item.as_dict() for item in self.items]}


@dataclass(frozen=True)
class ValidationReport:
    rule_id: str
    validate_protocol_version: str
    result: str
    validate_window: ValidateWindow
    windows_used: tuple[ValidateFold, ...]
    disjointness_proof: dict[str, Any]
    utility_distribution: UtilityDistribution
    challenger_reports: tuple[ChallengerReport, ...]
    robustness_profile: RobustnessProfile
    partition_profile: dict[str, Any]
    config_hash: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "validate_protocol_version": self.validate_protocol_version,
            "result": self.result,
            "validate_window": self.validate_window.as_dict(),
            "windows_used": [fold.as_dict() for fold in self.windows_used],
            "disjointness_proof": copy.deepcopy(self.disjointness_proof),
            "utility_distribution": self.utility_distribution.as_dict(),
            "challenger_reports": [report.as_dict() for report in self.challenger_reports],
            "robustness_profile": self.robustness_profile.as_dict(),
            "partition_profile": copy.deepcopy(self.partition_profile),
            "config_hash": self.config_hash,
        }


class ValidateStage(Stage):
    name = "validate_stage"
    version = "1"
    audit_stage = "Validate"
    cost_ceiling = CostCeiling(compute_usd=25.0, llm_usd=0.0, data_reads=250000)
    InputType = ValidateInput
    OutputType = ValidationReport

    def __init__(
        self,
        *,
        registry: Any,
        artifacts,
        audit,
        access=None,
        writer=None,
    ) -> None:
        super().__init__(artifacts=artifacts, audit=audit, access=access, writer=writer)
        self._registry = registry

    def run(self, inputs: Any, *, envelope: dict | None = None) -> StageResult:
        if isinstance(inputs, ValidateInput):
            env = {"cycle_id": inputs.cycle_id, "rule_id": inputs.rule.rule_id}
            env.update(envelope or {})
        else:
            env = dict(envelope or {})
        result = super().run(inputs, envelope=env)
        if result.cache_hit and isinstance(inputs, ValidateInput):
            self._ensure_cached_reservation(result.outputs)
        return result

    def fingerprint(self, inputs: Any) -> tuple[str, str]:
        if not isinstance(inputs, ValidateInput):
            return super().fingerprint(inputs)
        inputs_hash = _hash_payload(inputs.as_dict())
        fp = hashlib.sha256(
            canonicalize(
                {
                    "name": self.name,
                    "version": self.version,
                    "inputs_hash": inputs_hash,
                }
            )
        ).hexdigest()
        return inputs_hash, fp

    def compute(self, inputs: ValidateInput, ctx: StageContext) -> ValidationReport:
        if ctx.access is None:
            raise RuntimeError("ValidateStage requires an AccessLayer")
        rule = inputs.rule
        assert isinstance(rule, Rule)
        start, end = inputs.validate_window.as_tuple()
        dependency_gap_bars = _dependency_gap_bars(rule, self._registry, inputs.config)
        folds = build_validate_folds(
            inputs.validate_window,
            step_seconds=rule.cadence.step_seconds,
            config=inputs.config,
            dependency_gap_bars=dependency_gap_bars,
        )

        ctx.access.assert_window_available(
            rule_id=rule.rule_id,
            stage="Validate",
            t0=start,
            t1=end,
        )
        reservation = ctx.access.reserve_window(
            rule_id=rule.rule_id,
            stage="Validate",
            t0=start,
            t1=end,
        )
        tracker = _RuleCostTracker(rule.rule_id, inputs.config, ctx)
        access = _CostedAccess(ctx.access, tracker)

        rule_samples: list[float] = []
        challenger_samples: dict[str, list[float]] = {
            "inactive": [],
            "context_removed": [],
            "context_randomized": [],
            "input_permuted": [],
        }
        context_spec_ids = _context_spec_refs(rule)

        for fold in folds:
            window = fold.holdout_window.as_tuple()
            rule_trades = _simulate_rule(rule, window, access, self._registry, inputs.config, tracker)
            rule_samples.append(_utility(rule_trades, inputs.config))

            challenger_samples["inactive"].append(_utility([], inputs.config))
            removed_trades = _simulate_with_context_fn(
                rule,
                window,
                access,
                self._registry,
                inputs.config,
                tracker,
                lambda _t, _bar: True,
            )
            challenger_samples["context_removed"].append(_utility(removed_trades, inputs.config))

            randomized_trades = _simulate_with_context_fn(
                rule,
                window,
                access,
                self._registry,
                inputs.config,
                tracker,
                _randomized_context(rule, fold, window, access, self._registry, inputs.config),
            )
            challenger_samples["context_randomized"].append(
                _utility(randomized_trades, inputs.config)
            )

            permuted_registry = _TimePermutedRegistry(
                base=self._registry,
                spec_ids=context_spec_ids,
                times=_bar_times(window[0], window[1], rule.cadence.step_seconds),
                seed=_seed(rule.rule_id, fold.fold_id, inputs.config, "input_permuted"),
            )
            permuted_trades = _simulate_rule(
                rule,
                window,
                access,
                permuted_registry,
                inputs.config,
                tracker,
            )
            challenger_samples["input_permuted"].append(_utility(permuted_trades, inputs.config))

        utility_distribution = UtilityDistribution(
            construction="rule",
            samples=tuple(rule_samples),
        )
        challenger_reports = tuple(
            _challenger_report(
                challenger_id=challenger_id,
                rule_distribution=utility_distribution,
                challenger_samples=tuple(samples),
                config=inputs.config,
            )
            for challenger_id, samples in challenger_samples.items()
        )
        result = "pass" if all(report.result == "pass" for report in challenger_reports) else "fail"
        proof = {
            "checked_by": "AccessLayer.assert_window_available",
            "disjoint_from_stage": "Screen",
            "checked_window": inputs.validate_window.as_dict(),
            "validate_reservation": reservation.as_dict(),
            "dependency_gap_bars": dependency_gap_bars,
        }
        partition_profile = {
            "active_partitions": ["partition_0"],
            "partition_assignment_hash": inputs.partition_assignment_hash,
            "partition_source": "single_validate_partition",
        }
        return ValidationReport(
            rule_id=rule.rule_id,
            validate_protocol_version=inputs.config.config_version,
            result=result,
            validate_window=inputs.validate_window,
            windows_used=folds,
            disjointness_proof=proof,
            utility_distribution=utility_distribution,
            challenger_reports=challenger_reports,
            robustness_profile=_robustness_profile(
                rule=rule,
                folds=folds,
                access=access,
                registry=self._registry,
                config=inputs.config,
                tracker=tracker,
                input_permuted_samples=tuple(challenger_samples["input_permuted"]),
            ),
            partition_profile=partition_profile,
            config_hash=config_hash(inputs.config),
        )

    def invariant(self, inputs: ValidateInput, outputs: ValidationReport) -> None:
        rule = inputs.rule
        assert isinstance(rule, Rule)
        if outputs.rule_id != rule.rule_id:
            raise InvariantViolation("ValidationReport rule_id does not match input rule")
        if outputs.validate_protocol_version != inputs.config.config_version:
            raise InvariantViolation("validate protocol version does not match config")
        if outputs.config_hash != config_hash(inputs.config):
            raise InvariantViolation("config_hash does not match ValidateInput config")
        if outputs.result not in {"pass", "fail"}:
            raise InvariantViolation("Validate result must be pass or fail")
        if not outputs.utility_distribution.samples:
            raise InvariantViolation("Validate utility distribution must not be empty")
        if len(outputs.utility_distribution.samples) != len(outputs.windows_used):
            raise InvariantViolation("one utility sample is required per outer fold")
        if len(outputs.challenger_reports) != 4:
            raise InvariantViolation("four challenger reports are required")
        for report in outputs.challenger_reports:
            if not report.utility_distribution.samples:
                raise InvariantViolation("challenger utility distribution must not be empty")
        if outputs.disjointness_proof.get("checked_by") != "AccessLayer.assert_window_available":
            raise InvariantViolation("disjointness proof must name the access-layer check")

    def audit_extra_payload(
        self,
        inputs: ValidateInput,
        outputs: ValidationReport,
        ctx: StageContext,
        *,
        inputs_hash: str,
        output_hash: str,
    ) -> dict[str, Any]:
        return {
            "rule_id": outputs.rule_id,
            "validate_protocol_version": outputs.validate_protocol_version,
            "windows_used": [fold.as_dict() for fold in outputs.windows_used],
            "disjointness_proof": copy.deepcopy(outputs.disjointness_proof),
            "utility_distribution": outputs.utility_distribution.as_dict(),
            "challenger_reports": [report.as_dict() for report in outputs.challenger_reports],
            "robustness_profile": outputs.robustness_profile.as_dict(),
            "partition_profile": copy.deepcopy(outputs.partition_profile),
            "screen_output_hash": inputs.screen_output_hash,
            "config_hash": outputs.config_hash,
        }

    def _serialize_output(self, outputs: ValidationReport) -> bytes:
        return canonicalize(outputs.as_dict())

    def _deserialize_output(self, data: bytes) -> ValidationReport:
        raw = json.loads(data.decode("utf-8"))
        return _report_from_dict(raw)

    def _ensure_cached_reservation(self, report: ValidationReport) -> None:
        if self._access is None:
            return
        start, end = report.validate_window.as_tuple()
        self._access.assert_window_available(
            rule_id=report.rule_id,
            stage="Validate",
            t0=start,
            t1=end,
        )
        self._access.ensure_window_reserved(
            rule_id=report.rule_id,
            stage="Validate",
            t0=start,
            t1=end,
        )


def build_validate_folds(
    validate_window: ValidateWindow,
    *,
    step_seconds: int,
    config: ValidateConfig,
    dependency_gap_bars: int,
) -> tuple[ValidateFold, ...]:
    start, end = validate_window.as_tuple()
    total_bars = _bar_count(start, end, step_seconds)
    gap_bars = max(config.min_gap_bars, dependency_gap_bars)
    required = config.min_train_bars + gap_bars + config.outer_folds * config.holdout_bars
    if total_bars < required:
        raise ValueError(
            "validate window is too short for configured folds: "
            f"{total_bars} bars available, {required} required"
        )
    folds: list[ValidateFold] = []
    for i in range(config.outer_folds):
        holdout_start = config.min_train_bars + gap_bars + i * config.holdout_bars
        holdout_end = holdout_start + config.holdout_bars - 1
        train_end = holdout_start - gap_bars - 1
        train_window = _window_from_offsets(start, step_seconds, 0, train_end)
        gap_window = (
            None
            if gap_bars == 0
            else _window_from_offsets(start, step_seconds, train_end + 1, holdout_start - 1)
        )
        holdout_window = _window_from_offsets(start, step_seconds, holdout_start, holdout_end)
        folds.append(
            ValidateFold(
                fold_id=f"fold_{i}",
                train_window=train_window,
                gap_window=gap_window,
                holdout_window=holdout_window,
                inner_windows=_inner_windows(
                    start=start,
                    step_seconds=step_seconds,
                    train_end_offset=train_end,
                    config=config,
                ),
            )
        )
    return tuple(folds)


class _RuleCostTracker:
    def __init__(
        self,
        rule_id: str,
        config: ValidateConfig,
        ctx: StageContext,
    ) -> None:
        self.rule_id = rule_id
        self.config = config
        self.ctx = ctx
        self.usd = 0.0
        self.data_reads = 0

    def charge_compute(self, usd: float) -> None:
        self._charge_rule(usd)
        self.ctx.charge_compute(usd)

    def charge_data_read(self) -> None:
        self._charge_rule(self.config.data_read_cost_usd)
        self.ctx.charge_data_read(1)
        self.data_reads += 1

    def _charge_rule(self, usd: float) -> None:
        if self.usd + usd > self.config.max_rule_compute_usd:
            raise ValidateCostExceeded(self.rule_id)
        self.usd += usd


class _CostedAccess:
    def __init__(self, base: Any, tracker: _RuleCostTracker) -> None:
        self._base = base
        self._tracker = tracker

    def get(self, hash: str, query_time: datetime) -> bytes:
        self._tracker.charge_data_read()
        return self._base.get(hash, query_time)

    def provenance(self, hash: str, query_time: datetime):
        self._tracker.charge_data_read()
        return self._base.provenance(hash, query_time)

    def corrections(self, hash: str, query_time: datetime):
        self._tracker.charge_data_read()
        return self._base.corrections(hash, query_time)

    def lookup_llm(
        self,
        model_id: str,
        prompt_hash: str,
        params_hash: str,
        query_time: datetime,
    ) -> str | None:
        self._tracker.charge_data_read()
        return self._base.lookup_llm(model_id, prompt_hash, params_hash, query_time)


class _TimePermutedRegistry:
    def __init__(
        self,
        *,
        base: Any,
        spec_ids: frozenset[str],
        times: tuple[datetime, ...],
        seed: int,
    ) -> None:
        self._base = base
        self._spec_ids = spec_ids
        shuffled = list(times)
        random.Random(seed).shuffle(shuffled)
        self._mapping = dict(zip(times, shuffled, strict=True))

    def at(self, spec_id: str, t: datetime, access: Any) -> Any:
        return self._value(spec_id, self._map_time(spec_id, t), access)

    def resolve(self, spec_id: str, t: datetime, access: Any) -> Any:
        return self._value(spec_id, self._map_time(spec_id, t), access)

    def evaluate(self, spec_id: str, t: datetime, access: Any) -> Any:
        return self._value(spec_id, self._map_time(spec_id, t), access)

    def series(self, spec_id: str, t0: datetime, t1: datetime, access: Any) -> np.ndarray:
        method = getattr(self._base, "series", None)
        if callable(method) and spec_id not in self._spec_ids:
            return np.asarray(method(spec_id, t0, t1, access), dtype=float)
        times = [t for t in self._mapping if t0 <= t <= t1]
        times.sort()
        return np.asarray([self.at(spec_id, t, access) for t in times], dtype=float)

    def get(self, spec_id: str) -> Any:
        return self._base.get(spec_id)

    def list(self) -> list[str]:
        method = getattr(self._base, "list", None)
        if callable(method):
            return method()
        return []

    def _map_time(self, spec_id: str, t: datetime) -> datetime:
        if spec_id not in self._spec_ids:
            return t
        return self._mapping.get(t, t)

    def _value(self, spec_id: str, t: datetime, access: Any) -> Any:
        for method_name in ("resolve", "evaluate", "at"):
            method = getattr(self._base, method_name, None)
            if callable(method):
                return method(spec_id, t, access)
        return resolve_spec_output(spec_id, t, access, self._base)


def _simulate_rule(
    rule: Rule,
    window: tuple[datetime, datetime],
    access: Any,
    registry: Any,
    config: ValidateConfig,
    tracker: _RuleCostTracker,
) -> list[Trade]:
    tracker.charge_compute(_bar_count(window[0], window[1], rule.cadence.step_seconds) * config.compute_cost_per_bar_usd)
    trades = rule.simulate(window, access, registry)
    tracker.charge_compute(len(trades) * config.compute_cost_per_trade_usd)
    return trades


def _simulate_with_context_fn(
    rule: Rule,
    window: tuple[datetime, datetime],
    access: Any,
    registry: Any,
    config: ValidateConfig,
    tracker: _RuleCostTracker,
    context_fn: Callable[[datetime, int], bool],
) -> list[Trade]:
    tracker.charge_compute(_bar_count(window[0], window[1], rule.cadence.step_seconds) * config.compute_cost_per_bar_usd)
    if rule.action.side == "cash":
        return []

    start, end = window
    side_sign = _side_sign(rule.action.side)
    step = timedelta(seconds=rule.cadence.step_seconds)
    trades: list[Trade] = []
    in_position = False
    entry_t: datetime | None = None
    entry_bar: int | None = None
    entry_price: float | None = None

    t = start
    bar_index = 0
    while t <= end:
        if not in_position:
            if context_fn(t, bar_index):
                entry_t = t
                entry_bar = bar_index
                entry_price = _price_at(rule.price_spec_ref, t, access, registry)
                in_position = True
        else:
            assert entry_t is not None
            assert entry_bar is not None
            assert entry_price is not None
            current_price = _price_at(rule.price_spec_ref, t, access, registry)
            ctx = EvalContext(
                t=t,
                access=access,
                spec_registry=registry,
                bar_index=bar_index,
                entry_bar=entry_bar,
                side_sign=side_sign,
                entry_price=entry_price,
                current_price=current_price,
                context_now=lambda t=t, bar_index=bar_index: context_fn(t, bar_index),
            )
            exit_predicate = bool(execute_dag(rule.exit, DEFAULT_EXIT_OPS, ctx))
            if exit_predicate:
                trades.append(
                    _trade(
                        entry_t=entry_t,
                        exit_t=t,
                        side=rule.action.side,
                        side_sign=side_sign,
                        entry_price=entry_price,
                        exit_price=current_price,
                        exit_reason="exit_predicate",
                    )
                )
                in_position = False
                entry_t = None
                entry_bar = None
                entry_price = None
            elif bar_index - entry_bar >= rule.horizon_bars:
                trades.append(
                    _trade(
                        entry_t=entry_t,
                        exit_t=t,
                        side=rule.action.side,
                        side_sign=side_sign,
                        entry_price=entry_price,
                        exit_price=current_price,
                        exit_reason="horizon",
                    )
                )
                in_position = False
                entry_t = None
                entry_bar = None
                entry_price = None
        t += step
        bar_index += 1
    tracker.charge_compute(len(trades) * config.compute_cost_per_trade_usd)
    return trades


def _randomized_context(
    rule: Rule,
    fold: ValidateFold,
    window: tuple[datetime, datetime],
    access: Any,
    registry: Any,
    config: ValidateConfig,
) -> Callable[[datetime, int], bool]:
    times = _bar_times(window[0], window[1], rule.cadence.step_seconds)
    firing_count = 0
    for t in times:
        if rule.evaluate(t, access, registry):
            firing_count += 1
    sample_size = min(firing_count, len(times))
    indices = list(range(len(times)))
    rng = random.Random(_seed(rule.rule_id, fold.fold_id, config, "context_randomized"))
    selected = frozenset(rng.sample(indices, sample_size)) if sample_size else frozenset()
    return lambda _t, bar_index: bar_index in selected


def _utility(trades: list[Trade], config: ValidateConfig) -> float:
    wealth = 1.0
    peak = 1.0
    max_drawdown = 0.0
    cost = config.round_trip_cost_bps / 10000.0
    for trade in trades:
        net_return = float(trade.holding_return) - cost
        if net_return > 0:
            net_return -= net_return * config.tax_rate
        wealth *= max(config.min_return_floor, 1.0 + net_return)
        peak = max(peak, wealth)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - wealth) / peak)
    return float(math.log(max(config.min_return_floor, wealth)) - config.drawdown_penalty * max_drawdown)


def _challenger_report(
    *,
    challenger_id: str,
    rule_distribution: UtilityDistribution,
    challenger_samples: tuple[float, ...],
    config: ValidateConfig,
) -> ChallengerReport:
    challenger_distribution = UtilityDistribution(
        construction=challenger_id,
        samples=challenger_samples,
    )
    dominance_grid, dominates = _dominance_grid(
        rule_distribution.samples,
        challenger_distribution.samples,
        config,
    )
    partition = PartitionResult(
        partition_id="partition_0",
        dominance_order=config.dominance_order,
        dominance_grid=dominance_grid,
        dominates=dominates,
    )
    fraction = 1.0 if dominates else 0.0
    return ChallengerReport(
        challenger_id=challenger_id,
        utility_distribution=challenger_distribution,
        partition_results=(partition,),
        dominance_fraction=fraction,
        result="pass" if fraction >= config.min_challenger_pass_fraction else "fail",
    )


def _dominance_grid(
    rule_samples: tuple[float, ...],
    challenger_samples: tuple[float, ...],
    config: ValidateConfig,
) -> tuple[tuple[dict[str, float], ...], bool]:
    support = sorted(set(rule_samples) | set(challenger_samples))
    grid: list[dict[str, float]] = []
    dominates = True
    strict = False
    for cutoff in support:
        rule_cdf = sum(item <= cutoff for item in rule_samples) / len(rule_samples)
        challenger_cdf = sum(item <= cutoff for item in challenger_samples) / len(challenger_samples)
        if rule_cdf > challenger_cdf + config.dominance_epsilon:
            dominates = False
        if rule_cdf + config.dominance_epsilon < challenger_cdf:
            strict = True
        grid.append(
            {
                "grid_point": float(cutoff),
                "rule_cdf": float(rule_cdf),
                "challenger_cdf": float(challenger_cdf),
            }
        )
    if config.require_strict_dominance and not strict:
        dominates = False
    return tuple(grid), dominates


def _robustness_profile(
    *,
    rule: Rule,
    folds: tuple[ValidateFold, ...],
    access: Any,
    registry: Any,
    config: ValidateConfig,
    tracker: _RuleCostTracker,
    input_permuted_samples: tuple[float, ...],
) -> RobustnessProfile:
    items: list[RobustnessItem] = [
        RobustnessItem(
            perturbation_id="input_permuted",
            utility_distribution=UtilityDistribution(
                construction="input_permuted",
                samples=input_permuted_samples,
            ),
        )
    ]
    shift = config.context_shift_fraction
    if shift > 0:
        for direction, fraction in (("down", -shift), ("up", shift)):
            shifted = _shift_context_literals(rule, fraction)
            if shifted is None:
                continue
            samples: list[float] = []
            for fold in folds:
                trades = _simulate_rule(
                    shifted,
                    fold.holdout_window.as_tuple(),
                    access,
                    registry,
                    config,
                    tracker,
                )
                samples.append(_utility(trades, config))
            items.append(
                RobustnessItem(
                    perturbation_id=f"context_literal_{direction}",
                    utility_distribution=UtilityDistribution(
                        construction=f"context_literal_{direction}",
                        samples=tuple(samples),
                    ),
                )
            )
    return RobustnessProfile(items=tuple(items))


def _shift_context_literals(rule: Rule, fraction: float) -> Rule | None:
    body = rule.public_body()
    changed = False
    literal_arg = "val" + "ue"
    for node in body["context"]["nodes"]:
        if node["op"] != "literal":
            continue
        raw_number = node["args"].get(literal_arg)
        if isinstance(raw_number, bool) or not isinstance(raw_number, (int, float)):
            continue
        node["args"][literal_arg] = float(raw_number) * (1.0 + fraction)
        changed = True
    if not changed:
        return None
    return finalize_rule(body)


def _dependency_gap_bars(rule: Rule, registry: Any, config: ValidateConfig) -> int:
    gap = 0
    for spec_id in _rule_spec_refs(rule):
        spec = _registered_spec(registry, spec_id)
        if spec is None:
            continue
        for node in getattr(spec, "nodes", ()):
            node_gap, declared = _args_gap_bars(getattr(node, "args", {}))
            op_name = str(getattr(node, "op", ""))
            if not declared and op_name not in _ZERO_DEPENDENCY_OPS:
                raise ValueError("feature dependency span is unavailable")
            gap = max(gap, node_gap)
    if gap > config.max_dependency_gap_bars:
        raise ValueError("feature dependency gap exceeds configured maximum")
    return gap


def _args_gap_bars(args: Mapping[str, Any]) -> tuple[int, bool]:
    gap = 0
    declared = False
    for key, raw in args.items():
        if key not in {"lookback_bars", "window_bars", "lag_bars", "dependency_bars"}:
            continue
        declared = True
        if not isinstance(raw, int) or raw < 0:
            raise ValueError(f"{key} must be a non-negative int")
        gap = max(gap, raw)
    return gap, declared


def _registered_spec(registry: Any, spec_id: str) -> Any | None:
    method = getattr(registry, "get", None)
    if not callable(method):
        return None
    try:
        return method(spec_id)
    except KeyError:
        return None


def _rule_spec_refs(rule: Rule) -> frozenset[str]:
    refs = set(_context_spec_refs(rule))
    refs.update(_dag_spec_refs(rule.exit))
    refs.add(rule.price_spec_ref)
    refs.add(rule.grounding.spec_ref)
    return frozenset(refs)


def _context_spec_refs(rule: Rule) -> frozenset[str]:
    return frozenset(_dag_spec_refs(rule.context))


def _dag_spec_refs(dag: Any) -> set[str]:
    refs: set[str] = set()
    for node in dag.nodes:
        if node.op == "spec_ref":
            refs.add(str(node.args["spec_id"]))
    return refs


def _inner_windows(
    *,
    start: datetime,
    step_seconds: int,
    train_end_offset: int,
    config: ValidateConfig,
) -> tuple[ValidateWindow, ...]:
    if config.inner_folds == 0:
        return ()
    train_bars = train_end_offset + 1
    inner_bars = max(1, min(config.holdout_bars, train_bars // (config.inner_folds + 1)))
    windows: list[ValidateWindow] = []
    for i in range(config.inner_folds):
        end_offset = train_end_offset - (config.inner_folds - i - 1) * inner_bars
        start_offset = max(0, end_offset - inner_bars + 1)
        windows.append(_window_from_offsets(start, step_seconds, start_offset, end_offset))
    return tuple(windows)


def _window_from_offsets(
    start: datetime,
    step_seconds: int,
    start_offset: int,
    end_offset: int,
) -> ValidateWindow:
    step = timedelta(seconds=step_seconds)
    return ValidateWindow(
        (start + start_offset * step).isoformat(),
        (start + end_offset * step).isoformat(),
    )


def _bar_times(start: datetime, end: datetime, step_seconds: int) -> tuple[datetime, ...]:
    step = timedelta(seconds=step_seconds)
    times: list[datetime] = []
    t = start
    while t <= end:
        times.append(t)
        t += step
    return tuple(times)


def _bar_count(start: datetime, end: datetime, step_seconds: int) -> int:
    if step_seconds <= 0:
        raise ValueError("step_seconds must be positive")
    return int((end - start).total_seconds() // step_seconds) + 1


def _price_at(spec_id: str, t: datetime, access: Any, spec_registry: Any) -> float:
    raw = coerce_scalar(resolve_spec_output(spec_id, t, access, spec_registry))
    if isinstance(raw, bool):
        raise TypeError("price output must be numeric")
    return float(raw)


def _trade(
    *,
    entry_t: datetime,
    exit_t: datetime,
    side: str,
    side_sign: int,
    entry_price: float,
    exit_price: float,
    exit_reason: str,
) -> Trade:
    return Trade(
        entry_t=entry_t,
        exit_t=exit_t,
        side=side,  # type: ignore[arg-type]
        entry_price=entry_price,
        exit_price=exit_price,
        holding_return=(exit_price - entry_price) / entry_price * side_sign,
        exit_reason=exit_reason,  # type: ignore[arg-type]
    )


def _side_sign(side: str) -> int:
    if side == "long":
        return 1
    if side == "short":
        return -1
    raise ValueError("cash side has no position sign")


def _seed(rule_id: str, fold_id: str, config: ValidateConfig, salt: str) -> int:
    digest = hashlib.sha256(
        canonicalize(
            {
                "rule_id": rule_id,
                "fold_id": fold_id,
                "config_hash": config_hash(config),
                "seed": config.context_random_seed,
                "salt": salt,
            }
        )
    ).hexdigest()
    return int(digest[:16], 16)


def _hash_payload(payload: dict[str, Any]) -> str:
    return hashlib.sha256(canonicalize(payload)).hexdigest()


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


def _report_from_dict(raw: dict[str, Any]) -> ValidationReport:
    return ValidationReport(
        rule_id=str(raw["rule_id"]),
        validate_protocol_version=str(raw["validate_protocol_version"]),
        result=str(raw["result"]),
        validate_window=ValidateWindow(**raw["validate_window"]),
        windows_used=tuple(_fold_from_dict(item) for item in raw["windows_used"]),
        disjointness_proof=dict(raw["disjointness_proof"]),
        utility_distribution=_distribution_from_dict(raw["utility_distribution"]),
        challenger_reports=tuple(
            _challenger_from_dict(item) for item in raw["challenger_reports"]
        ),
        robustness_profile=RobustnessProfile(
            items=tuple(
                RobustnessItem(
                    perturbation_id=str(item["perturbation_id"]),
                    utility_distribution=_distribution_from_dict(item["utility_distribution"]),
                )
                for item in raw["robustness_profile"]["items"]
            )
        ),
        partition_profile=dict(raw["partition_profile"]),
        config_hash=str(raw["config_hash"]),
    )


def _fold_from_dict(item: dict[str, Any]) -> ValidateFold:
    return ValidateFold(
        fold_id=str(item["fold_id"]),
        train_window=ValidateWindow(**item["train_window"]),
        gap_window=None if item["gap_window"] is None else ValidateWindow(**item["gap_window"]),
        holdout_window=ValidateWindow(**item["holdout_window"]),
        inner_windows=tuple(ValidateWindow(**window) for window in item["inner_windows"]),
    )


def _distribution_from_dict(item: dict[str, Any]) -> UtilityDistribution:
    return UtilityDistribution(
        construction=str(item["construction"]),
        samples=tuple(float(raw) for raw in item["samples"]),
    )


def _challenger_from_dict(item: dict[str, Any]) -> ChallengerReport:
    return ChallengerReport(
        challenger_id=str(item["challenger_id"]),
        utility_distribution=_distribution_from_dict(item["utility_distribution"]),
        partition_results=tuple(
            PartitionResult(
                partition_id=str(result["partition_id"]),
                dominance_order=int(result["dominance_order"]),
                dominance_grid=tuple(
                    {key: float(raw) for key, raw in grid_item.items()}
                    for grid_item in result["dominance_grid"]
                ),
                dominates=bool(result["dominates"]),
            )
            for result in item["partition_results"]
        ),
        dominance_fraction=float(item["dominance_fraction"]),
        result=str(item["result"]),
    )
