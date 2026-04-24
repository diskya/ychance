from __future__ import annotations

import json
from pathlib import Path

import pytest

from access import AccessLayer, WindowReservationBook, WindowReservationError
from audit import AuditLog
from pipeline import ArtifactStore
from rawstore import RawStore
from rule import finalize_rule
from screen import ScreenConfig, ScreenInput, ScreenStage, ScreenWindow
from tests.rule.fixtures.helpers import (
    GROUND_SPEC,
    PRICE_SPEC,
    SeriesRegistry,
    context_price_gt,
    exit_after,
    rule_body,
    tick,
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
        cycle_id="screen-cycle",
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


def _config(**overrides) -> ScreenConfig:
    values = {
        "config_version": "test-screen",
        "max_candidate_compute_usd": 0.01,
        "compute_cost_per_bar_usd": 0.000001,
        "compute_cost_per_trade_usd": 0.000001,
        "data_read_cost_usd": 0.000001,
        "min_trades": 1,
        "min_signal_to_noise": 0.0,
        "noise_floor": 0.000001,
        "max_turnover_per_bar": 1.0,
        "round_trip_cost_bps": 1.0,
        "max_cost_to_gross_return": 1.0,
    }
    values.update(overrides)
    return ScreenConfig(**values)


def _stage(
    *,
    registry: SeriesRegistry,
    artifacts: ArtifactStore,
    audit: AuditLog,
    access: AccessLayer,
) -> ScreenStage:
    return ScreenStage(
        registry=registry,
        artifacts=artifacts,
        audit=audit,
        access=access,
    )


def _input(rule, *, config: ScreenConfig | None = None) -> ScreenInput:
    return ScreenInput(
        cycle_id="screen-cycle",
        candidates=(rule,),
        screen_window=ScreenWindow(tick(0).isoformat(), tick(5).isoformat()),
        config=_config() if config is None else config,
    )


def test_screen_passes_and_reserves_window(
    artifacts: ArtifactStore,
    audit: AuditLog,
    access: AccessLayer,
) -> None:
    registry = SeriesRegistry(
        {
            PRICE_SPEC: [99, 101, 103, 99, 101, 103],
            GROUND_SPEC: [1, 1, 1, 1, 1, 1],
        }
    )
    rule = finalize_rule(
        rule_body(context=context_price_gt(100), exit=exit_after(1), horizon_bars=5)
    )

    result = _stage(registry=registry, artifacts=artifacts, audit=audit, access=access).run(
        _input(rule),
        envelope={"cycle_id": "screen-cycle"},
    )

    assert result.outputs.survivors == (rule,)
    decision = result.outputs.decisions[0]
    assert decision.result == "pass"
    assert decision.failed_checks == ()
    assert decision.statistics.trade_count == 2
    assert decision.statistics.grounding_reproducible is True

    with pytest.raises(WindowReservationError):
        access.assert_window_available(
            rule_id=rule.rule_id,
            stage="Validate",
            t0=tick(1),
            t1=tick(2),
        )
    access.assert_window_available(
        rule_id=rule.rule_id,
        stage="Validate",
        t0=tick(6),
        t1=tick(7),
    )

    records = _audit_records(audit)
    screen_records = [record for record in records if record["category"] == "Screen"]
    assert len(screen_records) == 1
    assert screen_records[0]["screen_window"] == {"t0": tick(0).isoformat(), "t1": tick(5).isoformat()}
    assert screen_records[0]["records"][0]["rule_id"] == rule.rule_id
    assert screen_records[0]["records"][0]["statistics"]["signal_to_noise"] > 0


def test_signal_to_noise_threshold_is_config_driven(
    artifacts: ArtifactStore,
    audit: AuditLog,
    access: AccessLayer,
) -> None:
    registry = SeriesRegistry(
        {
            PRICE_SPEC: [99, 101, 103, 99, 101, 103],
            GROUND_SPEC: [1, 1, 1, 1, 1, 1],
        }
    )
    rule = finalize_rule(
        rule_body(context=context_price_gt(100), exit=exit_after(1), horizon_bars=5)
    )
    config = _config(min_signal_to_noise=100000.0)

    output = _stage(registry=registry, artifacts=artifacts, audit=audit, access=access).run(
        _input(rule, config=config)
    ).outputs

    assert output.survivors == ()
    assert output.decisions[0].result == "fail"
    assert "signal_to_noise" in output.decisions[0].failed_checks


def test_turnover_cost_consistency_is_checked(
    artifacts: ArtifactStore,
    audit: AuditLog,
    access: AccessLayer,
) -> None:
    registry = SeriesRegistry(
        {
            PRICE_SPEC: [101, 102, 103, 104, 105, 106],
            GROUND_SPEC: [1, 1, 1, 1, 1, 1],
        }
    )
    rule = finalize_rule(
        rule_body(context=context_price_gt(100), exit=exit_after(1), horizon_bars=5)
    )
    config = _config(max_turnover_per_bar=0.01)

    output = _stage(registry=registry, artifacts=artifacts, audit=audit, access=access).run(
        _input(rule, config=config)
    ).outputs

    assert output.survivors == ()
    assert output.decisions[0].statistics.turnover_per_bar > config.max_turnover_per_bar
    assert "turnover_cost_consistency" in output.decisions[0].failed_checks


def test_grounding_reproducibility_uses_screen_window(
    artifacts: ArtifactStore,
    audit: AuditLog,
    access: AccessLayer,
) -> None:
    registry = SeriesRegistry(
        {
            PRICE_SPEC: [99, 101, 103, 99, 101, 103],
            GROUND_SPEC: [-1, -1, -1, -1, -1, -1],
        }
    )
    rule = finalize_rule(
        rule_body(context=context_price_gt(100), exit=exit_after(1), horizon_bars=5)
    )

    output = _stage(registry=registry, artifacts=artifacts, audit=audit, access=access).run(
        _input(rule)
    ).outputs

    assert output.survivors == ()
    assert output.decisions[0].statistics.grounding_reproducible is False
    assert "grounding_reproducibility" in output.decisions[0].failed_checks


def test_candidate_cost_cap_refuses_before_window_reservation(
    artifacts: ArtifactStore,
    audit: AuditLog,
    access: AccessLayer,
) -> None:
    registry = SeriesRegistry({})
    rule = finalize_rule(
        rule_body(context=context_price_gt(100), exit=exit_after(1), horizon_bars=5)
    )
    config = _config(max_candidate_compute_usd=0.000001, compute_cost_per_bar_usd=0.000001)

    output = _stage(registry=registry, artifacts=artifacts, audit=audit, access=access).run(
        _input(rule, config=config)
    ).outputs

    assert output.survivors == ()
    assert output.decisions[0].failed_checks == ("cost_cap",)
    assert output.decisions[0].reservation_id is None
    access.assert_window_available(
        rule_id=rule.rule_id,
        stage="Validate",
        t0=tick(0),
        t1=tick(5),
    )


def test_cache_hit_restores_missing_reservation(
    tmp_path: Path,
    artifacts: ArtifactStore,
    rawstore: RawStore,
    audit: AuditLog,
) -> None:
    registry = SeriesRegistry(
        {
            PRICE_SPEC: [99, 101, 103, 99, 101, 103],
            GROUND_SPEC: [1, 1, 1, 1, 1, 1],
        }
    )
    rule = finalize_rule(
        rule_body(context=context_price_gt(100), exit=exit_after(1), horizon_bars=5)
    )
    first_book = WindowReservationBook(tmp_path / "reservations-1")
    second_book = WindowReservationBook(tmp_path / "reservations-2")
    try:
        first_access = AccessLayer(
            rawstore,
            audit,
            cycle_id="screen-cycle",
            max_reads_per_cycle=1000,
            reservation_book=first_book,
        )
        stage = _stage(
            registry=registry,
            artifacts=artifacts,
            audit=audit,
            access=first_access,
        )
        inputs = _input(rule)
        first = stage.run(inputs)
        assert first.cache_hit is False

        second_access = AccessLayer(
            rawstore,
            audit,
            cycle_id="screen-cycle",
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
        with pytest.raises(WindowReservationError):
            second_access.assert_window_available(
                rule_id=rule.rule_id,
                stage="Validate",
                t0=tick(1),
                t1=tick(2),
            )
    finally:
        first_book.close()
        second_book.close()
