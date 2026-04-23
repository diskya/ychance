from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

from access import AccessLayer
from audit import AuditLog
from pipeline import ArtifactStore, CostCeiling, CostCeilingExceeded, PipelineDAG
from rawstore import Provenance, RawStore
from represent import (
    DependencyEnvelopeError,
    RepresentInput,
    RepresentStage,
    SpecRegistry,
    finalize_spec,
)


BASE_TIME = datetime(2026, 4, 23, 12, 0, 0, tzinfo=timezone.utc)


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
def access(rawstore: RawStore, audit: AuditLog) -> AccessLayer:
    return AccessLayer(rawstore, audit, cycle_id="c1", max_reads_per_cycle=100)


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


def _put_json(rawstore: RawStore, payload: dict, *, vendor_offset_hours: int = 1) -> str:
    data = json.dumps(payload, sort_keys=True).encode("utf-8")
    return rawstore.put(
        data,
        Provenance(
            "source-A",
            BASE_TIME - timedelta(hours=vendor_offset_hours),
            BASE_TIME - timedelta(hours=vendor_offset_hours),
        ),
    )


def _scalar_body(raw_hash: str, *, deps: list[str] | None = None, name: str = "trial_one") -> dict:
    return {
        "schema_version": 1,
        "name": name,
        "graph": {
            "nodes": [
                {
                    "id": "read",
                    "op": "raw_get",
                    "args": {"hash": raw_hash},
                    "inputs": [],
                },
                {
                    "id": "parsed",
                    "op": "decode_json",
                    "args": {},
                    "inputs": ["read"],
                },
                {
                    "id": "picked",
                    "op": "json_get",
                    "args": {"path": ["value"]},
                    "inputs": ["parsed"],
                },
                {
                    "id": "cast",
                    "op": "cast_float64",
                    "args": {},
                    "inputs": ["picked"],
                },
            ],
            "output": "cast",
        },
        "deps": [raw_hash] if deps is None else list(deps),
        "cost": {
            "compute_usd": 0.0001,
            "llm_usd": 0.0,
            "storage_bytes": 8,
        },
        "output_schema": {
            "dtype": "float64",
            "shape": [],
        },
    }


def _runner(
    *,
    registry: SpecRegistry,
    artifacts: ArtifactStore,
    audit: AuditLog,
    access: AccessLayer,
) -> RepresentStage:
    return RepresentStage(
        registry=registry,
        artifacts=artifacts,
        audit=audit,
        access=access,
    )


def test_programmatic_spec_emission_runs_and_is_byte_identical(
    tmp_path: Path,
    rawstore: RawStore,
    audit: AuditLog,
    access: AccessLayer,
) -> None:
    raw_hash = _put_json(rawstore, {"value": 12.5})
    body = _scalar_body(raw_hash)
    finalized = finalize_spec(body)
    registry = SpecRegistry()
    spec_version = registry.register(finalized)

    artifacts_one = ArtifactStore(tmp_path / "artifacts-one")
    artifacts_two = ArtifactStore(tmp_path / "artifacts-two")
    try:
        stage_one = _runner(
            registry=registry,
            artifacts=artifacts_one,
            audit=audit,
            access=access,
        )
        stage_two = _runner(
            registry=registry,
            artifacts=artifacts_two,
            audit=audit,
            access=access,
        )

        run_input = RepresentInput(spec_version=spec_version, query_time=BASE_TIME.isoformat())
        first = stage_one.run(run_input)
        second = stage_two.run(run_input)

        assert first.outputs.spec_version == spec_version
        assert second.outputs.spec_version == spec_version
        assert first.outputs.tensor.dtype == np.dtype("float64")
        assert first.outputs.tensor.shape == ()
        assert first.outputs.tensor.item() == pytest.approx(12.5)
        assert first.outputs.tensor.tobytes() == second.outputs.tensor.tobytes()
        assert first.output_hash == second.output_hash
    finally:
        artifacts_one.close()
        artifacts_two.close()


def test_deps_envelope_fails_before_access_call(
    rawstore: RawStore,
    artifacts: ArtifactStore,
    audit: AuditLog,
    access: AccessLayer,
) -> None:
    raw_hash = _put_json(rawstore, {"value": 7.0})
    finalized = finalize_spec(_scalar_body(raw_hash, deps=[]))
    registry = SpecRegistry()
    spec_version = registry.register(finalized)
    stage = _runner(registry=registry, artifacts=artifacts, audit=audit, access=access)

    calls: list[str] = []
    original_get = access.get

    def tracking_get(hash_value: str, query_time: datetime) -> bytes:
        calls.append(hash_value)
        return original_get(hash_value, query_time)

    access.get = tracking_get

    with pytest.raises(DependencyEnvelopeError):
        stage.run(RepresentInput(spec_version=spec_version, query_time=BASE_TIME.isoformat()))

    assert calls == []


def test_deps_superset_is_allowed_and_audit_records_actual_reads(
    rawstore: RawStore,
    artifacts: ArtifactStore,
    audit: AuditLog,
    access: AccessLayer,
) -> None:
    used_hash = _put_json(rawstore, {"value": 3.0})
    unused_hash = _put_json(rawstore, {"value": 99.0}, vendor_offset_hours=2)
    finalized = finalize_spec(_scalar_body(used_hash, deps=[unused_hash, used_hash]))
    registry = SpecRegistry()
    spec_version = registry.register(finalized)
    stage = _runner(registry=registry, artifacts=artifacts, audit=audit, access=access)

    result = stage.run(RepresentInput(spec_version=spec_version, query_time=BASE_TIME.isoformat()))

    assert result.outputs.input_hashes == (used_hash,)
    represent_record = [r for r in _audit_records(audit) if r["category"] == "Represent"][0]
    assert represent_record["hashes_read"] == [used_hash]


def test_tight_data_read_ceiling_raises(
    rawstore: RawStore,
    artifacts: ArtifactStore,
    audit: AuditLog,
    access: AccessLayer,
) -> None:
    raw_hash = _put_json(rawstore, {"value": 2.0})
    finalized = finalize_spec(_scalar_body(raw_hash))
    registry = SpecRegistry()
    spec_version = registry.register(finalized)

    class TightRepresentStage(RepresentStage):
        cost_ceiling = CostCeiling(compute_usd=1.0, data_reads=0)

    stage = TightRepresentStage(
        registry=registry,
        artifacts=artifacts,
        audit=audit,
        access=access,
    )

    with pytest.raises(CostCeilingExceeded):
        stage.run(RepresentInput(spec_version=spec_version, query_time=BASE_TIME.isoformat()))


def test_represent_stage_in_dag_keeps_cache_hit_no_audit_property(
    rawstore: RawStore,
    artifacts: ArtifactStore,
    audit: AuditLog,
    access: AccessLayer,
) -> None:
    raw_hash = _put_json(rawstore, {"value": 5.0})
    registry = SpecRegistry()
    spec_version = registry.register(finalize_spec(_scalar_body(raw_hash)))
    stage = _runner(registry=registry, artifacts=artifacts, audit=audit, access=access)

    dag = PipelineDAG(audit=audit, envelope={"cycle_id": "c1"})
    dag.add(
        stage,
        inputs=lambda init, results: RepresentInput(
            spec_version=spec_version,
            query_time=BASE_TIME.isoformat(),
        ),
    )

    dag.run({})
    first_records = _audit_records(audit)
    assert [record["category"] for record in first_records] == ["Audit", "Access", "Represent", "Audit"]

    dag.run({})
    new_records = _audit_records(audit)[len(first_records) :]
    assert [record["category"] for record in new_records] == ["Audit", "Audit"]
    assert [record["event"] for record in new_records] == ["run_start", "run_end"]


def test_end_to_end_represent_run_records_hashes_and_category(
    rawstore: RawStore,
    artifacts: ArtifactStore,
    audit: AuditLog,
    access: AccessLayer,
) -> None:
    raw_hash = _put_json(rawstore, {"value": 41.0})
    registry = SpecRegistry()
    spec_version = registry.register(finalize_spec(_scalar_body(raw_hash, name="trial_end_to_end")))
    stage = _runner(registry=registry, artifacts=artifacts, audit=audit, access=access)

    result = stage.run(RepresentInput(spec_version=spec_version, query_time=BASE_TIME.isoformat()))

    assert result.outputs.tensor.item() == pytest.approx(41.0)
    represent_records = [record for record in _audit_records(audit) if record["category"] == "Represent"]
    assert len(represent_records) == 1
    assert represent_records[0]["stage"] == "Represent"
    assert represent_records[0]["hashes_read"] == [raw_hash]
