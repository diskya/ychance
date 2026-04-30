from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

import numpy as np

from access import WindowReservationError
from audit import canonicalize
from partitions import (
    PartitionAssignment,
    fallback_profile,
    load_partition_assignment,
    partition_id_for_window,
)
from pattern import Assertion, Pattern, load_assertion, load_pattern
from pipeline import CostCeiling, InvariantViolation, Stage, StageContext
from represent import RepresentInput, RepresentOutput, RepresentStage, SpecRegistry


class EmpiricalTestProtocolError(ValueError):
    """Raised when a Pattern's replication protocol cannot be executed."""


@dataclass(frozen=True)
class EmpiricalTestInput:
    cycle_id: str
    query_time: str
    pattern_artifact_hash: str | None = None
    pattern: dict[str, Any] | None = None
    partition_assignment_hash: str | None = None


@dataclass(frozen=True)
class HeldOutWindow:
    window_id: str
    t0: str
    t1: str

    def as_tuple(self) -> tuple[datetime, datetime]:
        return _parse_time(self.t0, "window.t0"), _parse_time(self.t1, "window.t1")

    def as_dict(self) -> dict[str, str]:
        return {"window_id": self.window_id, "t0": self.t0, "t1": self.t1}


@dataclass(frozen=True)
class WindowResult:
    window_id: str
    t0: str
    t1: str
    result: bool
    partition_id: str
    value_summary: dict[str, Any]
    lineage_hashes: tuple[str, ...]
    fingerprint_hash: str


@dataclass(frozen=True)
class PartitionResult:
    partition_id: str
    window_count: int
    pass_count: int
    required_pass_count: int
    pass_ratio: float
    verdict: bool


@dataclass(frozen=True)
class PerturbationWindowResult:
    window_id: str
    original_result: bool
    perturbed_result: bool
    passed: bool
    value_summary: dict[str, Any]


@dataclass(frozen=True)
class PerturbationResult:
    control: str
    passed: bool
    expectation: str
    window_results: tuple[PerturbationWindowResult, ...]


@dataclass(frozen=True)
class LineageWindowAudit:
    window_id: str
    t0: str
    t1: str
    lineage_hashes: tuple[str, ...]
    overlap_hashes: tuple[str, ...]
    clean: bool


@dataclass(frozen=True)
class DisjointnessAudit:
    clean: bool
    observation_window: dict[str, str]
    observation_lineage_hashes: tuple[str, ...]
    heldout_windows: tuple[LineageWindowAudit, ...]
    overlap_hashes: tuple[str, ...]
    reservation_failures: tuple[str, ...]
    gap_failures: tuple[str, ...]
    reservation_check_unavailable: tuple[str, ...]


@dataclass(frozen=True)
class EmpiricalTestCost:
    compute_usd: float
    llm_usd: float
    data_reads: int
    window_evaluations: int
    perturbation_evaluations: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "compute_usd": self.compute_usd,
            "llm_usd": self.llm_usd,
            "data_reads": self.data_reads,
            "window_evaluations": self.window_evaluations,
            "perturbation_evaluations": self.perturbation_evaluations,
        }


@dataclass(frozen=True)
class EmpiricalTestReport:
    pattern_id: str
    verdict: bool
    replication_verdict: bool
    partition_verdict: bool
    perturbation_verdict: bool
    disjointness_verdict: bool
    heldout_windows: tuple[HeldOutWindow, ...]
    window_results: tuple[WindowResult, ...]
    partition_results: tuple[PartitionResult, ...]
    perturbation_results: tuple[PerturbationResult, ...]
    disjointness_audit: DisjointnessAudit
    pass_gate: dict[str, Any]
    partition_profile: dict[str, Any]
    compute_cost: EmpiricalTestCost
    selection_seed: str


@dataclass(frozen=True)
class _Evaluation:
    window: HeldOutWindow
    value: Any
    result: bool
    lineage_hashes: tuple[str, ...]
    value_summary: dict[str, Any]
    fingerprint_hash: str
    partition_id: str
    compute_usd: float
    llm_usd: float
    data_reads: int


class EmpiricalTest(Stage):
    name = "empirical_test"
    version = "1"
    audit_stage = "EmpiricalTest"
    cost_ceiling = CostCeiling(compute_usd=10.0, llm_usd=10.0, data_reads=100_000)
    InputType = EmpiricalTestInput
    OutputType = EmpiricalTestReport

    def __init__(
        self,
        *,
        registry: Any,
        artifacts,
        audit,
        access=None,
        writer=None,
        represent_llm_client: Any = None,
    ) -> None:
        super().__init__(artifacts=artifacts, audit=audit, access=access, writer=writer)
        self._registry = registry
        self._represent_llm_client = represent_llm_client

    def compute(self, inputs: EmpiricalTestInput, ctx: StageContext) -> EmpiricalTestReport:
        if ctx.access is not None:
            ctx.access.begin_cycle(inputs.cycle_id)

        query_time = _parse_time(inputs.query_time, "query_time")
        pattern = self._load_input_pattern(inputs)
        windows = select_heldout_windows(pattern)
        selection_seed = _digest_jsonable(
            {
                "pattern_id": pattern.pattern_id,
                "replication_protocol": pattern.replication_protocol.as_dict(),
            }
        )
        assignment, assignment_hash_value = self._load_partition_assignment(
            inputs.partition_assignment_hash
        )
        partition_ids = self._partition_ids(
            windows=windows,
            assignment=assignment,
        )

        observation_window = HeldOutWindow(
            window_id="observation",
            t0=pattern.observation_window.t0,
            t1=pattern.observation_window.t1,
        )
        observation_eval = self._evaluate_window(
            pattern=pattern,
            window=observation_window,
            partition_id="observation",
            query_time=query_time,
            ctx=ctx,
        )
        evaluations: list[_Evaluation] = []
        reservation_failures: list[str] = []
        reservation_unavailable: list[str] = []
        for window in windows:
            self._check_and_reserve_window(
                pattern_id=pattern.pattern_id,
                window=window,
                ctx=ctx,
                reservation_failures=reservation_failures,
                reservation_unavailable=reservation_unavailable,
            )
            evaluations.append(
                self._evaluate_window(
                    pattern=pattern,
                    window=window,
                    partition_id=partition_ids[window.window_id],
                    query_time=query_time,
                    ctx=ctx,
                )
            )

        gap_failures = _gap_failures(pattern, windows)
        disjointness = _disjointness_audit(
            pattern=pattern,
            observation=observation_eval,
            heldout=evaluations,
            reservation_failures=tuple(reservation_failures),
            gap_failures=gap_failures,
            reservation_unavailable=tuple(reservation_unavailable),
        )
        replication_required = _required_pass_count(
            len(evaluations),
            _float_arg(pattern.replication_protocol.args, "pass_threshold", 0.5),
        )
        replication_passes = sum(1 for item in evaluations if item.result)
        replication_verdict = bool(evaluations) and replication_passes >= replication_required

        partition_results = _partition_results(
            evaluations,
            threshold=_float_arg(
                pattern.replication_protocol.args,
                "partition_pass_threshold",
                _float_arg(pattern.replication_protocol.args, "pass_threshold", 0.5),
            ),
        )
        partition_required = _required_pass_count(len(partition_results), 0.5)
        partition_verdict = bool(partition_results) and (
            sum(1 for item in partition_results if item.verdict) >= partition_required
        )

        perturbation_results = self._perturbation_results(
            pattern=pattern,
            evaluations=evaluations,
            query_time=query_time,
            ctx=ctx,
        )
        perturbation_verdict = (
            bool(perturbation_results) and all(item.passed for item in perturbation_results)
        )
        disjointness_verdict = disjointness.clean
        verdict = all(
            (
                replication_verdict,
                partition_verdict,
                perturbation_verdict,
                disjointness_verdict,
            )
        )

        profile = _partition_profile(
            windows=windows,
            partition_ids=partition_ids,
            assignment=assignment,
            assignment_hash_value=assignment_hash_value,
        )
        window_evaluation_count = 1 + len(evaluations)
        perturbation_evaluation_count = sum(
            len(item.window_results) for item in perturbation_results
        )
        compute_cost = EmpiricalTestCost(
            compute_usd=ctx.usage.compute_usd,
            llm_usd=ctx.usage.llm_usd,
            data_reads=ctx.usage.data_reads,
            window_evaluations=window_evaluation_count,
            perturbation_evaluations=perturbation_evaluation_count,
        )
        return EmpiricalTestReport(
            pattern_id=pattern.pattern_id,
            verdict=verdict,
            replication_verdict=replication_verdict,
            partition_verdict=partition_verdict,
            perturbation_verdict=perturbation_verdict,
            disjointness_verdict=disjointness_verdict,
            heldout_windows=tuple(windows),
            window_results=tuple(_window_result(item) for item in evaluations),
            partition_results=tuple(partition_results),
            perturbation_results=tuple(perturbation_results),
            disjointness_audit=disjointness,
            pass_gate={
                "replication_required_pass_count": replication_required,
                "replication_pass_count": replication_passes,
                "partition_required_pass_count": partition_required,
                "partition_pass_count": sum(1 for item in partition_results if item.verdict),
                "all_perturbation_controls_passed": perturbation_verdict,
                "disjointness_clean": disjointness_verdict,
            },
            partition_profile=profile,
            compute_cost=compute_cost,
            selection_seed=selection_seed,
        )

    def invariant(self, inputs: EmpiricalTestInput, outputs: EmpiricalTestReport) -> None:
        if len(outputs.pattern_id) != 64:
            raise InvariantViolation("EmpiricalTest pattern_id must be a sha256 hex digest")
        if outputs.verdict != all(
            (
                outputs.replication_verdict,
                outputs.partition_verdict,
                outputs.perturbation_verdict,
                outputs.disjointness_verdict,
            )
        ):
            raise InvariantViolation("EmpiricalTest verdict does not match pass gate")
        if len(outputs.window_results) != len(outputs.heldout_windows):
            raise InvariantViolation("window result count must match held-out windows")
        if outputs.disjointness_verdict != outputs.disjointness_audit.clean:
            raise InvariantViolation("disjointness verdict mismatch")
        if outputs.compute_cost.compute_usd < 0 or outputs.compute_cost.llm_usd < 0:
            raise InvariantViolation("cost fields must be non-negative")

    def audit_extra_payload(
        self,
        inputs: EmpiricalTestInput,
        outputs: EmpiricalTestReport,
        ctx: StageContext,
        *,
        inputs_hash: str,
        output_hash: str,
    ) -> dict[str, Any]:
        return {
            "kind": "EmpiricalTestReport",
            "pattern_id": outputs.pattern_id,
            "verdict": outputs.verdict,
            "replication_verdict": outputs.replication_verdict,
            "partition_verdict": outputs.partition_verdict,
            "perturbation_verdict": outputs.perturbation_verdict,
            "disjointness_verdict": outputs.disjointness_verdict,
            "pass_gate": outputs.pass_gate,
            "heldout_window_count": len(outputs.heldout_windows),
            "partition_results": [
                {
                    "partition_id": item.partition_id,
                    "verdict": item.verdict,
                    "window_count": item.window_count,
                    "pass_count": item.pass_count,
                }
                for item in outputs.partition_results
            ],
            "perturbation_results": [
                {
                    "control": item.control,
                    "passed": item.passed,
                    "window_count": len(item.window_results),
                }
                for item in outputs.perturbation_results
            ],
            "disjointness_audit": {
                "clean": outputs.disjointness_audit.clean,
                "overlap_hashes": list(outputs.disjointness_audit.overlap_hashes),
                "reservation_failures": list(outputs.disjointness_audit.reservation_failures),
                "gap_failures": list(outputs.disjointness_audit.gap_failures),
            },
            "compute_cost": outputs.compute_cost.as_dict(),
            "selection_seed": outputs.selection_seed,
        }

    def _load_input_pattern(self, inputs: EmpiricalTestInput) -> Pattern:
        if inputs.pattern is not None and inputs.pattern_artifact_hash is not None:
            raise EmpiricalTestProtocolError(
                "provide either pattern or pattern_artifact_hash, not both"
            )
        if inputs.pattern is not None:
            return load_pattern(inputs.pattern)
        if inputs.pattern_artifact_hash is None:
            raise EmpiricalTestProtocolError("EmpiricalTestInput requires a Pattern")
        return load_pattern(self._artifacts.get(inputs.pattern_artifact_hash))

    def _load_partition_assignment(
        self,
        assignment_hash_value: str | None,
    ) -> tuple[PartitionAssignment | None, str | None]:
        if assignment_hash_value is None:
            return None, None
        return load_partition_assignment(self._artifacts.get(assignment_hash_value)), assignment_hash_value

    def _partition_ids(
        self,
        *,
        windows: tuple[HeldOutWindow, ...],
        assignment: PartitionAssignment | None,
    ) -> dict[str, str]:
        if assignment is None:
            return {window.window_id: "partition_0" for window in windows}
        ids: dict[str, str] = {}
        for window in windows:
            t0, t1 = window.as_tuple()
            ids[window.window_id] = partition_id_for_window(assignment, t0=t0, t1=t1)
        return ids

    def _check_and_reserve_window(
        self,
        *,
        pattern_id: str,
        window: HeldOutWindow,
        ctx: StageContext,
        reservation_failures: list[str],
        reservation_unavailable: list[str],
    ) -> None:
        if ctx.access is None:
            return
        t0, t1 = window.as_tuple()
        try:
            ctx.access.assert_window_available(
                pattern_id=pattern_id,
                stage="EmpiricalTest",
                t0=t0,
                t1=t1,
            )
        except WindowReservationError as exc:
            reservation_failures.append(f"{window.window_id}: {exc}")
            return
        except RuntimeError as exc:
            reservation_unavailable.append(f"{window.window_id}: {exc}")
            return
        ctx.access.ensure_window_reserved(
            pattern_id=pattern_id,
            stage="EmpiricalTest",
            t0=t0,
            t1=t1,
        )

    def _evaluate_window(
        self,
        *,
        pattern: Pattern,
        window: HeldOutWindow,
        partition_id: str,
        query_time: datetime,
        ctx: StageContext,
    ) -> _Evaluation:
        del query_time
        ctx.charge_compute(0.00001)
        value, lineage, compute_usd, llm_usd, data_reads = self._resolve_window(
            pattern=pattern,
            window=window,
            ctx=ctx,
            control=None,
            seed=None,
        )
        lineage_hashes = _lineage_hashes(
            explicit=lineage,
            registry=self._registry,
            pattern=pattern,
            window=window,
            access=ctx.access,
        )
        result = pattern.assertion.evaluate(value)
        summary = _summary_stats(value)
        fingerprint_hash = _digest_jsonable(
            {
                "spec_ref": pattern.spec_ref,
                "assertion": pattern.assertion.hash_dict(),
                "window": window.as_dict(),
                "result": result,
                "summary": summary,
                "lineage_hashes": list(lineage_hashes),
            }
        )
        return _Evaluation(
            window=window,
            value=value,
            result=result,
            lineage_hashes=lineage_hashes,
            value_summary=summary,
            fingerprint_hash=fingerprint_hash,
            partition_id=partition_id,
            compute_usd=compute_usd,
            llm_usd=llm_usd,
            data_reads=data_reads,
        )

    def _perturbation_results(
        self,
        *,
        pattern: Pattern,
        evaluations: list[_Evaluation],
        query_time: datetime,
        ctx: StageContext,
    ) -> tuple[PerturbationResult, ...]:
        del query_time
        return (
            self._time_shuffled_control(pattern, evaluations, ctx),
            self._scope_randomized_control(pattern, evaluations, ctx),
            self._threshold_perturbed_control(pattern, evaluations, ctx),
        )

    def _time_shuffled_control(
        self,
        pattern: Pattern,
        evaluations: list[_Evaluation],
        ctx: StageContext,
    ) -> PerturbationResult:
        details: list[PerturbationWindowResult] = []
        for evaluation in evaluations:
            ctx.charge_compute(0.000005)
            seed = _control_seed(pattern.pattern_id, "time_shuffled", evaluation.window)
            value = self._control_value_or_default(
                pattern=pattern,
                evaluation=evaluation,
                control="time_shuffled",
                seed=seed,
                ctx=ctx,
                fallback=lambda item: _shuffle_time_axis(item.value, seed),
            )
            perturbed_result = pattern.assertion.evaluate(value)
            details.append(
                PerturbationWindowResult(
                    window_id=evaluation.window.window_id,
                    original_result=evaluation.result,
                    perturbed_result=perturbed_result,
                    passed=not perturbed_result,
                    value_summary=_summary_stats(value),
                )
            )
        return PerturbationResult(
            control="time_shuffled",
            passed=bool(details) and all(item.passed for item in details),
            expectation="assertion_rejects_time_shuffled_values",
            window_results=tuple(details),
        )

    def _scope_randomized_control(
        self,
        pattern: Pattern,
        evaluations: list[_Evaluation],
        ctx: StageContext,
    ) -> PerturbationResult:
        details: list[PerturbationWindowResult] = []
        for evaluation in evaluations:
            ctx.charge_compute(0.000005)
            seed = _control_seed(pattern.pattern_id, "scope_randomized", evaluation.window)
            value = self._control_value_or_default(
                pattern=pattern,
                evaluation=evaluation,
                control="scope_randomized",
                seed=seed,
                ctx=ctx,
                fallback=lambda item: _scope_resample(item.value, seed),
            )
            perturbed_result = pattern.assertion.evaluate(value)
            details.append(
                PerturbationWindowResult(
                    window_id=evaluation.window.window_id,
                    original_result=evaluation.result,
                    perturbed_result=perturbed_result,
                    passed=not perturbed_result,
                    value_summary=_summary_stats(value),
                )
            )
        return PerturbationResult(
            control="scope_randomized",
            passed=bool(details) and all(item.passed for item in details),
            expectation="assertion_rejects_scope_randomized_values",
            window_results=tuple(details),
        )

    def _threshold_perturbed_control(
        self,
        pattern: Pattern,
        evaluations: list[_Evaluation],
        ctx: StageContext,
    ) -> PerturbationResult:
        details: list[PerturbationWindowResult] = []
        band = _float_arg(pattern.replication_protocol.args, "threshold_band", 0.05)
        perturbed = _threshold_perturbed_assertion(pattern.assertion, band)
        for evaluation in evaluations:
            ctx.charge_compute(0.000005)
            perturbed_result = perturbed.evaluate(evaluation.value)
            details.append(
                PerturbationWindowResult(
                    window_id=evaluation.window.window_id,
                    original_result=evaluation.result,
                    perturbed_result=perturbed_result,
                    passed=perturbed_result == evaluation.result,
                    value_summary=evaluation.value_summary,
                )
            )
        return PerturbationResult(
            control="threshold_perturbed",
            passed=bool(details) and all(item.passed for item in details),
            expectation="assertion_verdict_is_stable_under_small_threshold_change",
            window_results=tuple(details),
        )

    def _control_value_or_default(
        self,
        *,
        pattern: Pattern,
        evaluation: _Evaluation,
        control: str,
        seed: int,
        ctx: StageContext,
        fallback,
    ) -> Any:
        try:
            value, _, compute_usd, llm_usd, data_reads = self._resolve_window(
                pattern=pattern,
                window=evaluation.window,
                ctx=ctx,
                control=control,
                seed=seed,
            )
        except EmpiricalTestProtocolError:
            return fallback(evaluation)
        _charge_child_cost(ctx, compute_usd, llm_usd, data_reads)
        return value

    def _resolve_window(
        self,
        *,
        pattern: Pattern,
        window: HeldOutWindow,
        ctx: StageContext,
        control: str | None,
        seed: int | None,
    ) -> tuple[Any, tuple[str, ...] | None, float, float, int]:
        reads_before = _reads_used(ctx.access)
        hook_value = self._resolve_with_registry_hook(
            pattern=pattern,
            window=window,
            ctx=ctx,
            control=control,
            seed=seed,
        )
        reads_delta = max(0, _reads_used(ctx.access) - reads_before)
        if hook_value is not None:
            if reads_delta:
                ctx.charge_data_read(reads_delta)
            value, lineage = _split_value_and_lineage(hook_value)
            return value, lineage, 0.0, 0.0, 0
        if control is not None:
            raise EmpiricalTestProtocolError(f"no registry hook for {control}")
        if isinstance(self._registry, SpecRegistry):
            output, result = self._represent_window(pattern, window, ctx)
            return (
                output.tensor,
                tuple(output.input_hashes),
                float(result.cost_used.compute_usd),
                float(result.cost_used.llm_usd),
                int(result.cost_used.data_reads),
            )
        value = self._resolve_by_points(pattern=pattern, window=window, ctx=ctx)
        return value, None, 0.0, 0.0, 0

    def _resolve_with_registry_hook(
        self,
        *,
        pattern: Pattern,
        window: HeldOutWindow,
        ctx: StageContext,
        control: str | None,
        seed: int | None,
    ) -> Any | None:
        t0, t1 = window.as_tuple()
        scope = pattern.scope.public_dict()
        for method_name in ("empirical_value", "window", "evaluate_window"):
            method = getattr(self._registry, method_name, None)
            if not callable(method):
                continue
            try:
                return method(
                    spec_ref=pattern.spec_ref,
                    t0=t0,
                    t1=t1,
                    access=ctx.access,
                    scope=scope,
                    control=control,
                    seed=seed,
                )
            except TypeError:
                if control is not None:
                    continue
                try:
                    return method(pattern.spec_ref, t0, t1, ctx.access)
                except TypeError:
                    continue
        if control is None:
            series = getattr(self._registry, "series", None)
            if callable(series):
                try:
                    return series(pattern.spec_ref, t0, t1, ctx.access)
                except TypeError:
                    return series(spec_ref=pattern.spec_ref, t0=t0, t1=t1, access=ctx.access)
        return None

    def _represent_window(
        self,
        pattern: Pattern,
        window: HeldOutWindow,
        ctx: StageContext,
    ) -> tuple[RepresentOutput, Any]:
        stage = RepresentStage(
            registry=self._registry,
            artifacts=self._artifacts,
            audit=self._audit,
            access=ctx.access,
            writer=ctx.writer,
            llm_client=self._represent_llm_client,
        )
        _, t1 = window.as_tuple()
        result = stage.run(
            RepresentInput(spec_version=pattern.spec_ref, query_time=t1.isoformat()),
            envelope=dict(ctx.envelope),
        )
        output = result.outputs
        _charge_child_cost(
            ctx,
            float(result.cost_used.compute_usd),
            float(result.cost_used.llm_usd),
            int(result.cost_used.data_reads),
        )
        return output, result

    def _resolve_by_points(
        self,
        *,
        pattern: Pattern,
        window: HeldOutWindow,
        ctx: StageContext,
    ) -> np.ndarray:
        t0, t1 = window.as_tuple()
        step_seconds = _positive_int_arg(
            pattern.replication_protocol.args,
            "step_seconds",
            default=max(1, int((t1 - t0).total_seconds()) or 1),
        )
        values: list[Any] = []
        for t in _bar_times(t0, t1, step_seconds):
            if not pattern.scope.matches(
                spec_ref=pattern.spec_ref,
                t=t,
                access=ctx.access,
                registry=self._registry,
            ):
                continue
            values.append(_resolve_at(self._registry, pattern.spec_ref, t, ctx.access))
        return np.asarray(values, dtype=float)


def select_heldout_windows(pattern: Pattern) -> tuple[HeldOutWindow, ...]:
    if not isinstance(pattern, Pattern):
        raise TypeError("select_heldout_windows requires a Pattern")
    protocol = pattern.replication_protocol
    args = protocol.args
    if protocol.kind == "fixed_windows":
        raw_windows = args.get("windows")
        if not isinstance(raw_windows, list) or not raw_windows:
            raise EmpiricalTestProtocolError("fixed_windows requires a non-empty windows list")
        candidates = tuple(_window_from_mapping(item, index) for index, item in enumerate(raw_windows))
    elif protocol.kind in {"deterministic_windows", "deterministic_grid"}:
        candidates = _grid_windows(pattern)
    else:
        raise EmpiricalTestProtocolError(
            f"unsupported replication protocol kind {protocol.kind!r}"
        )
    count = _positive_int_arg(args, "window_count", default=len(candidates))
    if count > len(candidates):
        raise EmpiricalTestProtocolError("window_count exceeds available held-out windows")
    if protocol.kind == "fixed_windows" and count == len(candidates):
        return tuple(candidates)
    ordered = sorted(
        candidates,
        key=lambda window: _digest_jsonable(
            {
                "pattern_id": pattern.pattern_id,
                "replication_protocol": protocol.as_dict(),
                "window": window.as_dict(),
            }
        ),
    )
    selected = tuple(sorted(ordered[:count], key=lambda item: (item.t0, item.t1)))
    if protocol.kind == "fixed_windows":
        return selected
    return tuple(
        HeldOutWindow(window_id=f"heldout_{index}", t0=item.t0, t1=item.t1)
        for index, item in enumerate(selected)
    )


def _grid_windows(pattern: Pattern) -> tuple[HeldOutWindow, ...]:
    args = pattern.replication_protocol.args
    search_t0 = _parse_time(args.get("search_t0", args.get("t0")), "search_t0")
    search_t1 = _parse_time(args.get("search_t1", args.get("t1")), "search_t1")
    window_seconds = _positive_int_arg(args, "window_seconds")
    step_seconds = _positive_int_arg(args, "step_seconds", default=window_seconds)
    gap_seconds = _gap_seconds(args)
    _, obs_t1 = pattern.observation_window.as_tuple()
    earliest = obs_t1 + timedelta(seconds=gap_seconds)
    windows: list[HeldOutWindow] = []
    index = 0
    start = max(search_t0, earliest)
    duration = timedelta(seconds=window_seconds)
    step = timedelta(seconds=step_seconds)
    while start + duration <= search_t1:
        windows.append(
            HeldOutWindow(
                window_id=f"candidate_{index}",
                t0=start.isoformat(),
                t1=(start + duration).isoformat(),
            )
        )
        index += 1
        start += step
    if not windows:
        raise EmpiricalTestProtocolError("deterministic window grid produced no candidates")
    return tuple(windows)


def _window_from_mapping(raw: Any, index: int) -> HeldOutWindow:
    if not isinstance(raw, Mapping) or set(raw.keys()) < {"t0", "t1"}:
        raise EmpiricalTestProtocolError("held-out window must contain t0 and t1")
    start = _parse_time(raw["t0"], "window.t0")
    end = _parse_time(raw["t1"], "window.t1")
    if end < start:
        raise EmpiricalTestProtocolError("held-out window t1 must be >= t0")
    raw_id = raw.get("window_id", f"heldout_{index}")
    if not isinstance(raw_id, str) or not raw_id:
        raise EmpiricalTestProtocolError("held-out window_id must be a non-empty string")
    return HeldOutWindow(window_id=raw_id, t0=start.isoformat(), t1=end.isoformat())


def _window_result(evaluation: _Evaluation) -> WindowResult:
    return WindowResult(
        window_id=evaluation.window.window_id,
        t0=evaluation.window.t0,
        t1=evaluation.window.t1,
        result=evaluation.result,
        partition_id=evaluation.partition_id,
        value_summary=evaluation.value_summary,
        lineage_hashes=evaluation.lineage_hashes,
        fingerprint_hash=evaluation.fingerprint_hash,
    )


def _partition_results(
    evaluations: list[_Evaluation],
    *,
    threshold: float,
) -> list[PartitionResult]:
    grouped: dict[str, list[_Evaluation]] = {}
    for item in evaluations:
        grouped.setdefault(item.partition_id, []).append(item)
    results: list[PartitionResult] = []
    for partition_id in sorted(grouped, key=_partition_sort_key):
        items = grouped[partition_id]
        pass_count = sum(1 for item in items if item.result)
        required = _required_pass_count(len(items), threshold)
        results.append(
            PartitionResult(
                partition_id=partition_id,
                window_count=len(items),
                pass_count=pass_count,
                required_pass_count=required,
                pass_ratio=pass_count / len(items),
                verdict=pass_count >= required,
            )
        )
    return results


def _partition_profile(
    *,
    windows: tuple[HeldOutWindow, ...],
    partition_ids: dict[str, str],
    assignment: PartitionAssignment | None,
    assignment_hash_value: str | None,
) -> dict[str, Any]:
    fold_partitions = tuple(
        {"fold_id": window.window_id, "partition_id": partition_ids[window.window_id]}
        for window in windows
    )
    if assignment is None:
        return fallback_profile(fold_ids=tuple(window.window_id for window in windows))
    from partitions import assignment_profile

    return assignment_profile(
        assignment,
        assignment_hash_value=assignment_hash_value or "",
        fold_partitions=fold_partitions,
    )


def _disjointness_audit(
    *,
    pattern: Pattern,
    observation: _Evaluation,
    heldout: list[_Evaluation],
    reservation_failures: tuple[str, ...],
    gap_failures: tuple[str, ...],
    reservation_unavailable: tuple[str, ...],
) -> DisjointnessAudit:
    del pattern
    observation_set = set(observation.lineage_hashes)
    audits: list[LineageWindowAudit] = []
    all_overlaps: set[str] = set()
    for evaluation in heldout:
        overlap = tuple(sorted(observation_set & set(evaluation.lineage_hashes)))
        all_overlaps.update(overlap)
        audits.append(
            LineageWindowAudit(
                window_id=evaluation.window.window_id,
                t0=evaluation.window.t0,
                t1=evaluation.window.t1,
                lineage_hashes=evaluation.lineage_hashes,
                overlap_hashes=overlap,
                clean=not overlap,
            )
        )
    clean = not all_overlaps and not reservation_failures and not gap_failures
    return DisjointnessAudit(
        clean=clean,
        observation_window={
            "t0": observation.window.t0,
            "t1": observation.window.t1,
        },
        observation_lineage_hashes=observation.lineage_hashes,
        heldout_windows=tuple(audits),
        overlap_hashes=tuple(sorted(all_overlaps)),
        reservation_failures=reservation_failures,
        gap_failures=gap_failures,
        reservation_check_unavailable=reservation_unavailable,
    )


def _lineage_hashes(
    *,
    explicit: tuple[str, ...] | None,
    registry: Any,
    pattern: Pattern,
    window: HeldOutWindow,
    access: Any,
) -> tuple[str, ...]:
    if explicit is not None:
        return _normalize_hash_tuple(explicit)
    t0, t1 = window.as_tuple()
    for method_name in ("empirical_lineage", "lineage", "lineage_for_window"):
        method = getattr(registry, method_name, None)
        if not callable(method):
            continue
        try:
            raw = method(
                spec_ref=pattern.spec_ref,
                t0=t0,
                t1=t1,
                access=access,
                scope=pattern.scope.public_dict(),
            )
        except TypeError:
            try:
                raw = method(pattern.spec_ref, t0, t1, access)
            except TypeError:
                continue
        return _normalize_hash_tuple(raw)
    get = getattr(registry, "get", None)
    if callable(get):
        spec = get(pattern.spec_ref)
        deps = getattr(spec, "deps", None)
        if deps is not None:
            return _normalize_hash_tuple(deps)
    raise EmpiricalTestProtocolError(
        "cannot prove raw-store lineage for empirical-test window"
    )


def _split_value_and_lineage(raw: Any) -> tuple[Any, tuple[str, ...] | None]:
    if isinstance(raw, Mapping):
        if "value" in raw:
            value = raw["value"]
        elif "tensor" in raw:
            value = raw["tensor"]
        else:
            value = raw
        lineage = raw.get("lineage_hashes", raw.get("input_hashes"))
        return value, None if lineage is None else _normalize_hash_tuple(lineage)
    if isinstance(raw, tuple) and len(raw) == 2:
        return raw[0], _normalize_hash_tuple(raw[1])
    for value_attr in ("value", "tensor"):
        if hasattr(raw, value_attr):
            value = getattr(raw, value_attr)
            for lineage_attr in ("lineage_hashes", "input_hashes"):
                if hasattr(raw, lineage_attr):
                    return value, _normalize_hash_tuple(getattr(raw, lineage_attr))
            return value, None
    return raw, None


def _normalize_hash_tuple(raw: Any) -> tuple[str, ...]:
    if isinstance(raw, str):
        raw_values = (raw,)
    else:
        raw_values = tuple(raw)
    values = tuple(sorted(str(item) for item in raw_values))
    for item in values:
        if len(item) != 64:
            raise EmpiricalTestProtocolError("lineage entries must be sha256 hashes")
        int(item, 16)
    return values


def _threshold_perturbed_assertion(assertion: Assertion, band: float) -> Assertion:
    if band < 0:
        raise EmpiricalTestProtocolError("threshold_band must be non-negative")
    body = assertion.public_dict()
    args = dict(body["args"])
    if assertion.kind == "in_range":
        lo = float(args["lo"])
        hi = float(args["hi"])
        span = max(hi - lo, abs(hi), abs(lo), 1.0)
        delta = span * band
        new_lo = lo + delta
        new_hi = hi - delta
        if new_hi < new_lo:
            midpoint = (lo + hi) / 2.0
            new_lo = midpoint
            new_hi = midpoint
        args = {"lo": new_lo, "hi": new_hi}
    elif assertion.kind == "quantile_ge":
        threshold = float(args["threshold"])
        delta = max(abs(threshold), 1.0) * band
        args = {"p": args["p"], "threshold": threshold + delta}
    elif assertion.kind == "sign":
        args = dict(args)
    else:
        raise EmpiricalTestProtocolError(
            f"threshold perturbation does not support assertion kind {assertion.kind!r}"
        )
    return load_assertion({"kind": assertion.kind, "args": args})


def _gap_failures(pattern: Pattern, windows: tuple[HeldOutWindow, ...]) -> tuple[str, ...]:
    _, obs_end = pattern.observation_window.as_tuple()
    gap = timedelta(seconds=_gap_seconds(pattern.replication_protocol.args))
    earliest = obs_end + gap
    failures: list[str] = []
    for window in windows:
        t0, _ = window.as_tuple()
        if t0 < earliest:
            failures.append(
                f"{window.window_id}: starts {t0.isoformat()} before required {earliest.isoformat()}"
            )
    return tuple(failures)


def _gap_seconds(args: Mapping[str, Any]) -> int:
    for key in ("gap_seconds", "dependency_gap_seconds", "longest_dependency_seconds"):
        if key in args:
            return _positive_int_arg(args, key, default=0, allow_zero=True)
    return 0


def _required_pass_count(n: int, threshold: float) -> int:
    if n <= 0:
        return 1
    if threshold < 0.0 or threshold > 1.0:
        raise EmpiricalTestProtocolError("pass thresholds must be in [0, 1]")
    threshold_required = int(math.ceil(n * threshold))
    majority_required = (n // 2) + 1
    return max(1, threshold_required, majority_required)


def _resolve_at(registry: Any, spec_ref: str, t: datetime, access: Any) -> Any:
    for method_name in ("resolve", "evaluate", "at"):
        method = getattr(registry, method_name, None)
        if callable(method):
            try:
                return method(spec_ref=spec_ref, t=t, access=access)
            except TypeError:
                return method(spec_ref, t, access)
    raise EmpiricalTestProtocolError(
        "registry must expose empirical_value(), series(), resolve(), evaluate(), or at()"
    )


def _charge_child_cost(
    ctx: StageContext,
    compute_usd: float,
    llm_usd: float,
    data_reads: int,
) -> None:
    if compute_usd:
        ctx.charge_compute(compute_usd)
    if llm_usd:
        ctx.charge_llm(llm_usd)
    if data_reads:
        ctx.charge_data_read(data_reads)


def _reads_used(access: Any) -> int:
    if access is None:
        return 0
    value = getattr(access, "reads_used", 0)
    return int(value) if isinstance(value, int) else 0


def _summary_stats(value: Any) -> dict[str, Any]:
    array = np.asarray(value)
    payload: dict[str, Any] = {
        "dtype": str(array.dtype),
        "shape": list(array.shape),
        "size": int(array.size),
    }
    try:
        numeric = np.asarray(value, dtype=float).reshape(-1)
    except (TypeError, ValueError):
        return payload | {"numeric": False}
    finite = numeric[np.isfinite(numeric)]
    payload["numeric"] = True
    payload["finite_count"] = int(finite.size)
    if finite.size:
        payload["min"] = _round_float(float(np.min(finite)))
        payload["max"] = _round_float(float(np.max(finite)))
        payload["mean"] = _round_float(float(np.mean(finite)))
        payload["q50"] = _round_float(float(np.quantile(finite, 0.5)))
    return payload


def _shuffle_time_axis(value: Any, seed: int) -> np.ndarray:
    array = np.array(value, copy=True)
    if array.size <= 1:
        return array
    rng = np.random.default_rng(seed)
    if array.ndim == 0:
        return array
    indices = np.arange(array.shape[0])
    rng.shuffle(indices)
    return np.ascontiguousarray(array[indices])


def _scope_resample(value: Any, seed: int) -> np.ndarray:
    array = np.asarray(value, dtype=float).reshape(-1)
    if array.size == 0:
        return array
    rng = np.random.default_rng(seed)
    indices = rng.integers(0, array.size, size=array.size)
    return np.ascontiguousarray(array[indices])


def _control_seed(pattern_id: str, control: str, window: HeldOutWindow) -> int:
    h = _digest_jsonable(
        {"pattern_id": pattern_id, "control": control, "window": window.as_dict()}
    )
    return int(h[:16], 16)


def _digest_jsonable(value: Any) -> str:
    return hashlib.sha256(canonicalize(_jsonable(value))).hexdigest()


def _jsonable(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if hasattr(value, "as_dict"):
        return value.as_dict()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _parse_time(raw: Any, field: str) -> datetime:
    if isinstance(raw, datetime):
        dt = raw
    elif isinstance(raw, str) and raw:
        dt = datetime.fromisoformat(raw)
    else:
        raise EmpiricalTestProtocolError(f"{field} must be an ISO-8601 timestamp")
    if dt.tzinfo is None:
        raise EmpiricalTestProtocolError(f"{field} must be timezone-aware")
    return dt.astimezone(timezone.utc)


def _positive_int_arg(
    args: Mapping[str, Any],
    key: str,
    default: int | None = None,
    *,
    allow_zero: bool = False,
) -> int:
    raw = args.get(key, default)
    if raw is None:
        raise EmpiricalTestProtocolError(f"{key} is required")
    if not isinstance(raw, int) or isinstance(raw, bool):
        raise EmpiricalTestProtocolError(f"{key} must be an integer")
    if allow_zero:
        if raw < 0:
            raise EmpiricalTestProtocolError(f"{key} must be >= 0")
    elif raw <= 0:
        raise EmpiricalTestProtocolError(f"{key} must be > 0")
    return raw


def _float_arg(args: Mapping[str, Any], key: str, default: float) -> float:
    raw = args.get(key, default)
    if not isinstance(raw, (int, float)) or isinstance(raw, bool):
        raise EmpiricalTestProtocolError(f"{key} must be numeric")
    value = float(raw)
    if not math.isfinite(value):
        raise EmpiricalTestProtocolError(f"{key} must be finite")
    return value


def _bar_times(start: datetime, end: datetime, step_seconds: int) -> tuple[datetime, ...]:
    if end < start:
        raise EmpiricalTestProtocolError("window end must be >= start")
    step = timedelta(seconds=step_seconds)
    times: list[datetime] = []
    t = start
    while t <= end:
        times.append(t)
        t += step
    return tuple(times)


def _partition_sort_key(partition_id: str) -> tuple[int, str]:
    if partition_id.startswith("partition_"):
        suffix = partition_id.split("_", 1)[1]
        if suffix.isdigit():
            return int(suffix), partition_id
    return 10**9, partition_id


def _round_float(value: float) -> float:
    rounded = round(float(value), 12)
    if rounded == -0.0:
        return 0.0
    return rounded


__all__ = [
    "DisjointnessAudit",
    "EmpiricalTest",
    "EmpiricalTestCost",
    "EmpiricalTestInput",
    "EmpiricalTestProtocolError",
    "EmpiricalTestReport",
    "HeldOutWindow",
    "LineageWindowAudit",
    "PartitionResult",
    "PerturbationResult",
    "PerturbationWindowResult",
    "WindowResult",
    "select_heldout_windows",
]
