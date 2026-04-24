from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

import numpy as np

from audit import canonicalize
from pipeline import CostCeiling, InvariantViolation, Stage, StageContext, StageResult
from rule import Rule, load_rule
from rule.grounding import Grounding, GroundingWindow

from .config import ScreenConfig, config_hash, load_screen_config


class CandidateCostExceeded(RuntimeError):
    """Raised before a candidate would exceed its Screen cost cap."""


@dataclass(frozen=True)
class ScreenWindow:
    t0: str
    t1: str

    def __post_init__(self) -> None:
        start = _parse_time(self.t0, "t0")
        end = _parse_time(self.t1, "t1")
        if end < start:
            raise ValueError("screen window t1 must be >= t0")
        object.__setattr__(self, "t0", start.isoformat())
        object.__setattr__(self, "t1", end.isoformat())

    def as_tuple(self) -> tuple[datetime, datetime]:
        return _parse_time(self.t0, "t0"), _parse_time(self.t1, "t1")

    def as_dict(self) -> dict[str, str]:
        return {"t0": self.t0, "t1": self.t1}


@dataclass(frozen=True)
class ScreenInput:
    cycle_id: str
    candidates: tuple[Rule | Mapping[str, Any], ...]
    screen_window: ScreenWindow
    config: ScreenConfig = field(default_factory=load_screen_config)

    def __post_init__(self) -> None:
        if not isinstance(self.cycle_id, str) or not self.cycle_id:
            raise ValueError("cycle_id must be a non-empty string")
        loaded: list[Rule] = []
        for item in self.candidates:
            loaded.append(item if isinstance(item, Rule) else load_rule(item))
        object.__setattr__(self, "candidates", tuple(loaded))

    def as_dict(self) -> dict[str, Any]:
        return {
            "cycle_id": self.cycle_id,
            "candidates": [rule.to_dict() for rule in self.candidates],
            "screen_window": self.screen_window.as_dict(),
            "config": self.config.as_dict(),
        }


@dataclass(frozen=True)
class ScreenStatistics:
    rule_id: str
    bar_count: int
    trade_count: int
    gross_mean_return: float
    net_mean_return: float
    net_return_std: float
    signal_to_noise: float
    turnover_per_bar: float
    estimated_total_cost_return: float
    gross_abs_return: float
    cost_to_gross_return: float
    grounding_reproducible: bool
    candidate_cost_usd: float
    candidate_data_reads: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "bar_count": self.bar_count,
            "trade_count": self.trade_count,
            "gross_mean_return": self.gross_mean_return,
            "net_mean_return": self.net_mean_return,
            "net_return_std": self.net_return_std,
            "signal_to_noise": self.signal_to_noise,
            "turnover_per_bar": self.turnover_per_bar,
            "estimated_total_cost_return": self.estimated_total_cost_return,
            "gross_abs_return": self.gross_abs_return,
            "cost_to_gross_return": self.cost_to_gross_return,
            "grounding_reproducible": self.grounding_reproducible,
            "candidate_cost_usd": self.candidate_cost_usd,
            "candidate_data_reads": self.candidate_data_reads,
        }


@dataclass(frozen=True)
class ScreenDecision:
    rule_id: str
    result: str
    screen_window: ScreenWindow
    statistics: ScreenStatistics
    failed_checks: tuple[str, ...]
    reservation_id: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "result": self.result,
            "pass/fail": self.result,
            "screen_window": self.screen_window.as_dict(),
            "statistics": self.statistics.as_dict(),
            "failed_checks": list(self.failed_checks),
            "reservation_id": self.reservation_id,
        }


@dataclass(frozen=True)
class ScreenOutput:
    survivors: tuple[Rule, ...]
    decisions: tuple[ScreenDecision, ...]
    config_hash: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "survivors": [rule.to_dict() for rule in self.survivors],
            "decisions": [decision.as_dict() for decision in self.decisions],
            "config_hash": self.config_hash,
        }


class ScreenStage(Stage):
    name = "screen_stage"
    version = "1"
    audit_stage = "Screen"
    cost_ceiling = CostCeiling(compute_usd=10.0, llm_usd=0.0, data_reads=100000)
    InputType = ScreenInput
    OutputType = ScreenOutput

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
        result = super().run(inputs, envelope=envelope)
        if result.cache_hit and isinstance(inputs, ScreenInput):
            self._ensure_cached_reservations(inputs, result.outputs)
        return result

    def fingerprint(self, inputs: Any) -> tuple[str, str]:
        if not isinstance(inputs, ScreenInput):
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

    def compute(self, inputs: ScreenInput, ctx: StageContext) -> ScreenOutput:
        if ctx.access is None:
            raise RuntimeError("ScreenStage requires an AccessLayer")
        survivors: list[Rule] = []
        decisions: list[ScreenDecision] = []
        for rule in inputs.candidates:
            decision = self._evaluate_candidate(rule, inputs.screen_window, inputs.config, ctx)
            decisions.append(decision)
            if decision.result == "pass":
                survivors.append(rule)
        return ScreenOutput(
            survivors=tuple(survivors),
            decisions=tuple(decisions),
            config_hash=config_hash(inputs.config),
        )

    def invariant(self, inputs: ScreenInput, outputs: ScreenOutput) -> None:
        if len(outputs.decisions) != len(inputs.candidates):
            raise InvariantViolation("one Screen decision is required per candidate")
        input_ids = [rule.rule_id for rule in inputs.candidates]
        decision_ids = [decision.rule_id for decision in outputs.decisions]
        if decision_ids != input_ids:
            raise InvariantViolation("decision order must match candidate order")
        passed = [decision.rule_id for decision in outputs.decisions if decision.result == "pass"]
        survivor_ids = [rule.rule_id for rule in outputs.survivors]
        if survivor_ids != passed:
            raise InvariantViolation("survivors must match passed candidates")
        if outputs.config_hash != config_hash(inputs.config):
            raise InvariantViolation("config_hash does not match ScreenInput config")
        for decision in outputs.decisions:
            if decision.result not in {"pass", "fail"}:
                raise InvariantViolation("Screen decision result must be pass or fail")
            if decision.result == "pass" and decision.failed_checks:
                raise InvariantViolation("passed Screen decision cannot have failed checks")
            if decision.statistics.candidate_cost_usd > inputs.config.max_candidate_compute_usd:
                raise InvariantViolation("candidate cost exceeded configured cap")

    def audit_extra_payload(
        self,
        inputs: ScreenInput,
        outputs: ScreenOutput,
        ctx: StageContext,
        *,
        inputs_hash: str,
        output_hash: str,
    ) -> dict[str, Any]:
        return {
            "cycle_id": inputs.cycle_id,
            "screen_window": inputs.screen_window.as_dict(),
            "config_hash": outputs.config_hash,
            "records": [decision.as_dict() for decision in outputs.decisions],
            "passed_rule_ids": [rule.rule_id for rule in outputs.survivors],
            "failed_rule_ids": [
                decision.rule_id for decision in outputs.decisions if decision.result == "fail"
            ],
        }

    def _serialize_output(self, outputs: ScreenOutput) -> bytes:
        return canonicalize(outputs.as_dict())

    def _deserialize_output(self, data: bytes) -> ScreenOutput:
        raw = json.loads(data.decode("utf-8"))
        return ScreenOutput(
            survivors=tuple(load_rule(item) for item in raw["survivors"]),
            decisions=tuple(_decision_from_dict(item) for item in raw["decisions"]),
            config_hash=str(raw["config_hash"]),
        )

    def _evaluate_candidate(
        self,
        rule: Rule,
        window: ScreenWindow,
        config: ScreenConfig,
        ctx: StageContext,
    ) -> ScreenDecision:
        start, end = window.as_tuple()
        bar_count = _bar_count(start, end, rule.cadence.step_seconds)
        estimated_bar_cost = bar_count * config.compute_cost_per_bar_usd
        if estimated_bar_cost > config.max_candidate_compute_usd:
            stats = _empty_stats(
                rule_id=rule.rule_id,
                bar_count=bar_count,
                cost_usd=0.0,
            )
            return ScreenDecision(
                rule_id=rule.rule_id,
                result="fail",
                screen_window=window,
                statistics=stats,
                failed_checks=("cost_cap",),
                reservation_id=None,
            )

        tracker = _CandidateCostTracker(rule.rule_id, config, ctx)
        tracker.charge_compute(estimated_bar_cost)
        assert ctx.access is not None
        reservation = ctx.access.reserve_window(
            rule_id=rule.rule_id,
            stage="Screen",
            t0=start,
            t1=end,
        )
        access = _CostedAccess(ctx.access, tracker)
        try:
            trades = rule.simulate((start, end), access, self._registry)
            tracker.charge_compute(len(trades) * config.compute_cost_per_trade_usd)
            grounding = Grounding(
                spec_ref=rule.grounding.spec_ref,
                assertion=rule.grounding.assertion,
                window=GroundingWindow(t0=start, t1=end),
            )
            grounding_reproducible = grounding.evaluate(access, self._registry)
            stats = _statistics(
                rule_id=rule.rule_id,
                bar_count=bar_count,
                trades=trades,
                config=config,
                grounding_reproducible=grounding_reproducible,
                candidate_cost_usd=tracker.usd,
                candidate_data_reads=tracker.data_reads,
            )
            failed = _failed_checks(stats, config)
        except CandidateCostExceeded:
            stats = _empty_stats(
                rule_id=rule.rule_id,
                bar_count=bar_count,
                cost_usd=tracker.usd,
                data_reads=tracker.data_reads,
            )
            failed = ("cost_cap",)
        except Exception as exc:
            stats = _empty_stats(
                rule_id=rule.rule_id,
                bar_count=bar_count,
                cost_usd=tracker.usd,
                data_reads=tracker.data_reads,
            )
            failed = (f"execution_error:{type(exc).__name__}",)

        return ScreenDecision(
            rule_id=rule.rule_id,
            result="pass" if not failed else "fail",
            screen_window=window,
            statistics=stats,
            failed_checks=tuple(failed),
            reservation_id=reservation.reservation_id,
        )

    def _ensure_cached_reservations(
        self,
        inputs: ScreenInput,
        outputs: ScreenOutput,
    ) -> None:
        if self._access is None:
            return
        start, end = inputs.screen_window.as_tuple()
        for decision in outputs.decisions:
            if decision.reservation_id is not None:
                self._access.ensure_window_reserved(
                    rule_id=decision.rule_id,
                    stage="Screen",
                    t0=start,
                    t1=end,
                )


class _CandidateCostTracker:
    def __init__(
        self,
        rule_id: str,
        config: ScreenConfig,
        ctx: StageContext,
    ) -> None:
        self.rule_id = rule_id
        self.config = config
        self.ctx = ctx
        self.usd = 0.0
        self.data_reads = 0

    def charge_compute(self, usd: float) -> None:
        self._charge_candidate(usd)
        self.ctx.charge_compute(usd)

    def charge_data_read(self) -> None:
        self._charge_candidate(self.config.data_read_cost_usd)
        self.ctx.charge_data_read(1)
        self.data_reads += 1

    def _charge_candidate(self, usd: float) -> None:
        if self.usd + usd > self.config.max_candidate_compute_usd:
            raise CandidateCostExceeded(self.rule_id)
        self.usd += usd


class _CostedAccess:
    def __init__(self, base: Any, tracker: _CandidateCostTracker) -> None:
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


def _failed_checks(stats: ScreenStatistics, config: ScreenConfig) -> list[str]:
    failed: list[str] = []
    if stats.trade_count < config.min_trades:
        failed.append("min_trades")
    if stats.signal_to_noise < config.min_signal_to_noise:
        failed.append("signal_to_noise")
    if stats.turnover_per_bar > config.max_turnover_per_bar:
        failed.append("turnover_cost_consistency")
    if stats.cost_to_gross_return > config.max_cost_to_gross_return:
        failed.append("turnover_cost_consistency")
    if not stats.grounding_reproducible:
        failed.append("grounding_reproducibility")
    return failed


def _statistics(
    *,
    rule_id: str,
    bar_count: int,
    trades: list[Any],
    config: ScreenConfig,
    grounding_reproducible: bool,
    candidate_cost_usd: float,
    candidate_data_reads: int,
) -> ScreenStatistics:
    gross = np.asarray([float(trade.holding_return) for trade in trades], dtype=float)
    cost_per_trade = config.round_trip_cost_bps / 10000.0
    if gross.size:
        net = gross - cost_per_trade
        gross_mean = float(np.mean(gross))
        net_mean = float(np.mean(net))
        if net.size > 1:
            net_std = float(np.std(net, ddof=1))
        else:
            net_std = 0.0
        denominator = max(net_std, config.noise_floor)
        signal_to_noise = net_mean / denominator
        gross_abs_return = float(np.sum(np.abs(gross)))
    else:
        net_mean = 0.0
        gross_mean = 0.0
        net_std = 0.0
        signal_to_noise = 0.0
        gross_abs_return = 0.0
    trade_count = int(gross.size)
    estimated_total_cost = trade_count * cost_per_trade
    cost_to_gross = (
        1e308
        if estimated_total_cost > 0 and gross_abs_return == 0
        else estimated_total_cost / gross_abs_return
        if gross_abs_return > 0
        else 0.0
    )
    return ScreenStatistics(
        rule_id=rule_id,
        bar_count=bar_count,
        trade_count=trade_count,
        gross_mean_return=gross_mean,
        net_mean_return=net_mean,
        net_return_std=net_std,
        signal_to_noise=float(signal_to_noise),
        turnover_per_bar=trade_count / bar_count if bar_count else 1e308,
        estimated_total_cost_return=float(estimated_total_cost),
        gross_abs_return=float(gross_abs_return),
        cost_to_gross_return=float(cost_to_gross),
        grounding_reproducible=grounding_reproducible,
        candidate_cost_usd=float(candidate_cost_usd),
        candidate_data_reads=candidate_data_reads,
    )


def _empty_stats(
    *,
    rule_id: str,
    bar_count: int,
    cost_usd: float,
    data_reads: int = 0,
) -> ScreenStatistics:
    return ScreenStatistics(
        rule_id=rule_id,
        bar_count=bar_count,
        trade_count=0,
        gross_mean_return=0.0,
        net_mean_return=0.0,
        net_return_std=0.0,
        signal_to_noise=0.0,
        turnover_per_bar=0.0,
        estimated_total_cost_return=0.0,
        gross_abs_return=0.0,
        cost_to_gross_return=0.0,
        grounding_reproducible=False,
        candidate_cost_usd=float(cost_usd),
        candidate_data_reads=data_reads,
    )


def _decision_from_dict(item: dict[str, Any]) -> ScreenDecision:
    stats = item["statistics"]
    return ScreenDecision(
        rule_id=str(item["rule_id"]),
        result=str(item["result"]),
        screen_window=ScreenWindow(**item["screen_window"]),
        statistics=ScreenStatistics(
            rule_id=str(stats["rule_id"]),
            bar_count=int(stats["bar_count"]),
            trade_count=int(stats["trade_count"]),
            gross_mean_return=float(stats["gross_mean_return"]),
            net_mean_return=float(stats["net_mean_return"]),
            net_return_std=float(stats["net_return_std"]),
            signal_to_noise=float(stats["signal_to_noise"]),
            turnover_per_bar=float(stats["turnover_per_bar"]),
            estimated_total_cost_return=float(stats["estimated_total_cost_return"]),
            gross_abs_return=float(stats["gross_abs_return"]),
            cost_to_gross_return=float(stats["cost_to_gross_return"]),
            grounding_reproducible=bool(stats["grounding_reproducible"]),
            candidate_cost_usd=float(stats["candidate_cost_usd"]),
            candidate_data_reads=int(stats["candidate_data_reads"]),
        ),
        failed_checks=tuple(str(check) for check in item["failed_checks"]),
        reservation_id=item["reservation_id"],
    )


def _hash_payload(payload: dict[str, Any]) -> str:
    return hashlib.sha256(canonicalize(payload)).hexdigest()


def _bar_count(start: datetime, end: datetime, step_seconds: int) -> int:
    if step_seconds <= 0:
        raise ValueError("step_seconds must be positive")
    return int((end - start).total_seconds() // step_seconds) + 1


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
