from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from access import AccessLayer, WindowReservationBook, WindowReservationError
from audit import AuditLog
from pipeline import ArtifactStore
from rawstore import RawStore
from rule import finalize_rule
from tests.rule.fixtures.helpers import (
    GROUND_SPEC,
    PRICE_SPEC,
    SeriesRegistry,
    context_price_le,
    exit_after,
    rule_body,
    tick,
)
from validate import (
    ValidateConfig,
    ValidateInput,
    ValidateStage,
    ValidateWindow,
    build_validate_folds,
)


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
        cycle_id="validate-cycle",
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


def _audit_records(log: AuditLog) -> list[dict]:
    records: list[dict] = []
    for path in sorted(log._root.glob("*.jsonl")):
        for line in path.read_text().splitlines():
            if line:
                records.append(json.loads(line))
    return records


def _config(**overrides) -> ValidateConfig:
    cfg = {
        "config_version": "test-validate",
        "max_rule_compute_usd": 1.0,
        "compute_cost_per_bar_usd": 0.000001,
        "compute_cost_per_trade_usd": 0.000001,
        "data_read_cost_usd": 0.000001,
        "outer_folds": 3,
        "holdout_bars": 4,
        "min_train_bars": 3,
        "inner_folds": 1,
        "min_gap_bars": 1,
        "max_dependency_gap_bars": 100,
        "round_trip_cost_bps": 0.0,
        "tax_rate": 0.0,
        "drawdown_penalty": 0.0,
        "min_return_floor": 0.000001,
        "dominance_order": 1,
        "dominance_epsilon": 0.0,
        "min_challenger_pass_fraction": 0.0,
        "require_strict_dominance": False,
        "context_random_seed": 7,
        "context_shift_fraction": 0.01,
    }
    cfg.update(overrides)
    return ValidateConfig(**cfg)


def _registry(length: int = 48) -> SeriesRegistry:
    block = [99.0, 101.0, 103.0, 98.0]
    return SeriesRegistry(
        {
            PRICE_SPEC: [block[i % len(block)] for i in range(length)],
            GROUND_SPEC: [1.0 for _ in range(length)],
        }
    )


def _rule(*, side: str = "long"):
    return finalize_rule(
        rule_body(
            context=context_price_le(99),
            exit=exit_after(1),
            horizon_bars=4,
            side=side,
        )
    )


def _input(rule, *, config: ValidateConfig | None = None) -> ValidateInput:
    return ValidateInput(
        cycle_id="validate-cycle",
        rule=rule,
        validate_window=ValidateWindow(tick(6).isoformat(), tick(35).isoformat()),
        config=_config() if config is None else config,
        screen_output_hash="a" * 64,
    )


def _stage(
    *,
    registry: SeriesRegistry,
    artifacts: ArtifactStore,
    audit: AuditLog,
    access: AccessLayer,
) -> ValidateStage:
    return ValidateStage(
        registry=registry,
        artifacts=artifacts,
        audit=audit,
        access=access,
    )


@dataclass(frozen=True)
class _FakeNode:
    op: str
    args: dict


@dataclass(frozen=True)
class _FakeSpec:
    nodes: tuple[_FakeNode, ...]


class _RegistryWithUnknownSpan(SeriesRegistry):
    def get(self, spec_id: str):
        return _FakeSpec(nodes=(_FakeNode(op="custom_op", args={}),))


def test_validate_runs_disjoint_and_emits_distribution_report(
    artifacts: ArtifactStore,
    audit: AuditLog,
    access: AccessLayer,
    reservations: WindowReservationBook,
) -> None:
    registry = _registry()
    rule = _rule()
    access.reserve_window(rule_id=rule.rule_id, stage="Screen", t0=tick(0), t1=tick(5))

    result = _stage(
        registry=registry,
        artifacts=artifacts,
        audit=audit,
        access=access,
    ).run(_input(rule))

    report = result.outputs
    assert result.cache_hit is False
    assert report.rule_id == rule.rule_id
    assert report.result == "pass"
    assert len(report.utility_distribution.samples) == 3
    assert {item.challenger_id for item in report.challenger_reports} == {
        "inactive",
        "context_removed",
        "context_randomized",
        "input_permuted",
    }
    assert all(item.utility_distribution.samples for item in report.challenger_reports)
    assert report.partition_profile["active_partitions"] == ["partition_0"]
    assert report.disjointness_proof["checked_by"] == "AccessLayer.assert_window_available"
    assert reservations.exact(
        rule_id=rule.rule_id,
        stage="Validate",
        t0=tick(6),
        t1=tick(35),
    )

    records = _audit_records(audit)
    validate_records = [record for record in records if record["category"] == "Validate"]
    assert len(validate_records) == 1
    validate_record = validate_records[0]
    assert validate_record["rule_id"] == rule.rule_id
    assert validate_record["validate_protocol_version"] == "test-validate"
    assert validate_record["utility_distribution"]["samples"]
    assert validate_record["challenger_reports"][0]["utility_distribution"]["samples"]
    assert validate_record["partition_profile"]["active_partitions"] == ["partition_0"]


def test_validate_refuses_screen_overlap_before_stage_record(
    artifacts: ArtifactStore,
    audit: AuditLog,
    access: AccessLayer,
) -> None:
    registry = _registry()
    rule = _rule()
    access.reserve_window(rule_id=rule.rule_id, stage="Screen", t0=tick(10), t1=tick(14))

    with pytest.raises(WindowReservationError):
        _stage(
            registry=registry,
            artifacts=artifacts,
            audit=audit,
            access=access,
        ).run(_input(rule))

    records = _audit_records(audit)
    assert not [record for record in records if record["category"] == "Validate"]
    checks = [
        record
        for record in records
        if record["category"] == "Access"
        and record.get("kind") == "window_reservation_check"
        and record["envelope"].get("rule_id") == rule.rule_id
    ]
    assert checks[-1]["outcome"] == "refused"
    raw_reads = [record for record in records if record["category"] == "Access" and record.get("kind") == "bytes"]
    assert raw_reads == []


def test_other_rule_screen_overlap_does_not_refuse(
    artifacts: ArtifactStore,
    audit: AuditLog,
    access: AccessLayer,
) -> None:
    registry = _registry()
    rule = _rule()
    access.reserve_window(rule_id="f" * 64, stage="Screen", t0=tick(10), t1=tick(14))

    report = _stage(
        registry=registry,
        artifacts=artifacts,
        audit=audit,
        access=access,
    ).run(_input(rule)).outputs

    assert report.rule_id == rule.rule_id


def test_boundary_touching_screen_window_refuses(
    artifacts: ArtifactStore,
    audit: AuditLog,
    access: AccessLayer,
) -> None:
    registry = _registry()
    rule = _rule()
    access.reserve_window(rule_id=rule.rule_id, stage="Screen", t0=tick(0), t1=tick(6))

    with pytest.raises(WindowReservationError):
        _stage(
            registry=registry,
            artifacts=artifacts,
            audit=audit,
            access=access,
        ).run(_input(rule))


def test_cache_hit_restores_missing_validate_reservation(
    tmp_path: Path,
    artifacts: ArtifactStore,
    rawstore: RawStore,
    audit: AuditLog,
) -> None:
    registry = _registry()
    rule = _rule()
    inputs = _input(rule)
    first_book = WindowReservationBook(tmp_path / "reservations-1")
    second_book = WindowReservationBook(tmp_path / "reservations-2")
    try:
        first_access = AccessLayer(
            rawstore,
            audit,
            cycle_id="validate-cycle",
            max_reads_per_cycle=1000,
            reservation_book=first_book,
        )
        first = _stage(
            registry=registry,
            artifacts=artifacts,
            audit=audit,
            access=first_access,
        ).run(inputs)
        assert first.cache_hit is False

        second_access = AccessLayer(
            rawstore,
            audit,
            cycle_id="validate-cycle",
            max_reads_per_cycle=1000,
            reservation_book=second_book,
        )
        second = _stage(
            registry=registry,
            artifacts=artifacts,
            audit=audit,
            access=second_access,
        ).run(inputs)

        assert second.cache_hit is True
        assert second_book.exact(
            rule_id=rule.rule_id,
            stage="Validate",
            t0=tick(6),
            t1=tick(35),
        )
    finally:
        first_book.close()
        second_book.close()


def test_cache_hit_rechecks_new_screen_reservation(
    artifacts: ArtifactStore,
    audit: AuditLog,
    access: AccessLayer,
) -> None:
    registry = _registry()
    rule = _rule()
    inputs = _input(rule)
    stage = _stage(registry=registry, artifacts=artifacts, audit=audit, access=access)

    first = stage.run(inputs)
    assert first.cache_hit is False
    access.reserve_window(rule_id=rule.rule_id, stage="Screen", t0=tick(12), t1=tick(13))

    with pytest.raises(WindowReservationError):
        stage.run(inputs)


def test_configured_strict_dominance_can_fail_equal_distributions(
    artifacts: ArtifactStore,
    audit: AuditLog,
    access: AccessLayer,
) -> None:
    registry = _registry()
    rule = _rule(side="cash")
    config = _config(min_challenger_pass_fraction=1.0, require_strict_dominance=True)

    report = _stage(
        registry=registry,
        artifacts=artifacts,
        audit=audit,
        access=access,
    ).run(_input(rule, config=config)).outputs

    assert report.result == "fail"
    assert all(item.result == "fail" for item in report.challenger_reports)


def test_unknown_feature_dependency_span_refuses_closed(
    artifacts: ArtifactStore,
    audit: AuditLog,
    access: AccessLayer,
) -> None:
    registry = _RegistryWithUnknownSpan(_registry().series_by_id)
    rule = _rule()

    with pytest.raises(ValueError, match="dependency span"):
        _stage(
            registry=registry,
            artifacts=artifacts,
            audit=audit,
            access=access,
        ).run(_input(rule))


@given(
    outer_folds=st.integers(min_value=1, max_value=5),
    holdout_bars=st.integers(min_value=1, max_value=6),
    min_train_bars=st.integers(min_value=1, max_value=8),
    gap_bars=st.integers(min_value=0, max_value=4),
)
def test_build_validate_folds_keeps_holdouts_after_gap(
    outer_folds: int,
    holdout_bars: int,
    min_train_bars: int,
    gap_bars: int,
) -> None:
    config = _config(
        outer_folds=outer_folds,
        holdout_bars=holdout_bars,
        min_train_bars=min_train_bars,
        min_gap_bars=gap_bars,
        inner_folds=1,
    )
    required = min_train_bars + gap_bars + outer_folds * holdout_bars
    window = ValidateWindow(tick(0).isoformat(), tick(required + 2).isoformat())

    folds = build_validate_folds(
        window,
        step_seconds=60,
        config=config,
        dependency_gap_bars=0,
    )

    assert len(folds) == outer_folds
    for fold in folds:
        train_start, train_end = fold.train_window.as_tuple()
        holdout_start, holdout_end = fold.holdout_window.as_tuple()
        assert train_start <= train_end < holdout_start <= holdout_end
        if fold.gap_window is not None:
            gap_start, gap_end = fold.gap_window.as_tuple()
            assert train_end < gap_start <= gap_end < holdout_start
        for inner in fold.inner_windows:
            inner_start, inner_end = inner.as_tuple()
            assert train_start <= inner_start <= inner_end <= train_end
