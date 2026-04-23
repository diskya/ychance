from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

from access import AccessLayer, RawStoreWriter
from audit import AuditLog, canonicalize
from pipeline import ArtifactStore, CostCeiling, CostCeilingExceeded, PipelineDAG
from rawstore import Provenance, RawStore
from represent import (
    DependencyEnvelopeError,
    LLMResponse,
    RepresentInput,
    RepresentStage,
    SpecRegistry,
    StubLLMClient,
    finalize_spec,
)
from represent.llm_client import params_hash, prompt_hash


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
def writer(rawstore: RawStore, audit: AuditLog) -> RawStoreWriter:
    return RawStoreWriter(rawstore, audit)


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


def _llm_args(
    *,
    declared_cost_usd: float = 0.001,
    cost_tolerance: float = 0.20,
    prompt_template: str = "fixed prompt",
    input_names: list[str] | None = None,
) -> dict:
    args = {
        "model": "qwen-plus",
        "prompt_template": prompt_template,
        "params": {"temperature": 0, "max_tokens": 16},
        "input_names": [] if input_names is None else list(input_names),
        "declared_cost_usd": declared_cost_usd,
        "cost_tolerance": cost_tolerance,
    }
    return args


def _llm_text_body(args: dict | None = None) -> dict:
    return {
        "schema_version": 1,
        "name": "llm_text",
        "graph": {
            "nodes": [
                {
                    "id": "call",
                    "op": "llm_call",
                    "args": _llm_args() if args is None else dict(args),
                    "inputs": [],
                },
            ],
            "output": "call",
        },
        "deps": [],
        "cost": {
            "compute_usd": 0.0001,
            "llm_usd": 0.001,
            "storage_bytes": 16,
        },
        "output_schema": {
            "dtype": "<U5",
            "shape": [],
        },
    }


def _mixed_raw_llm_body(raw_hash: str, args: dict | None = None) -> dict:
    return {
        "schema_version": 1,
        "name": "mixed_raw_llm",
        "graph": {
            "nodes": [
                {
                    "id": "read",
                    "op": "raw_get",
                    "args": {"hash": raw_hash},
                    "inputs": [],
                },
                {
                    "id": "raw_json",
                    "op": "decode_json",
                    "args": {},
                    "inputs": ["read"],
                },
                {
                    "id": "raw_value",
                    "op": "json_get",
                    "args": {"path": ["value"]},
                    "inputs": ["raw_json"],
                },
                {
                    "id": "call",
                    "op": "llm_call",
                    "args": _llm_args(prompt_template="value is {value}", input_names=["value"])
                    if args is None
                    else dict(args),
                    "inputs": ["raw_value"],
                },
                {
                    "id": "parsed",
                    "op": "decode_json",
                    "args": {},
                    "inputs": ["call"],
                },
                {
                    "id": "picked",
                    "op": "json_get",
                    "args": {"path": ["score"]},
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
        "deps": [raw_hash],
        "cost": {
            "compute_usd": 0.0001,
            "llm_usd": 0.001,
            "storage_bytes": 8,
        },
        "output_schema": {
            "dtype": "float64",
            "shape": [],
        },
    }


def _llm_key(args: dict, prompt: str) -> tuple[str, str, str]:
    return (
        args["model"],
        prompt_hash(prompt),
        params_hash(model=args["model"], params=args["params"]),
    )


def _seed_llm_cache(
    rawstore: RawStore,
    *,
    model: str,
    prompt_hash_value: str,
    params_hash_value: str,
    text: str,
    input_tokens: int,
    output_tokens: int,
    fetch_time: datetime = BASE_TIME - timedelta(minutes=1),
) -> str:
    body = canonicalize(
        {
            "model": model,
            "prompt_hash": prompt_hash_value,
            "params_hash": params_hash_value,
            "response": {
                "text": text,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            },
        }
    )
    bytes_hash = rawstore.put(
        body,
        Provenance(
            f"llm:{model}",
            fetch_time,
            fetch_time,
        ),
    )
    reader = rawstore._issue_reader()
    rawstore._insert_llm_cache(
        reader,
        model_id=model,
        prompt_hash=prompt_hash_value,
        params_hash=params_hash_value,
        bytes_hash=bytes_hash,
    )
    return bytes_hash


def _runner(
    *,
    registry: SpecRegistry,
    artifacts: ArtifactStore,
    audit: AuditLog,
    access: AccessLayer,
    writer: RawStoreWriter | None = None,
    llm_client=None,
) -> RepresentStage:
    return RepresentStage(
        registry=registry,
        artifacts=artifacts,
        audit=audit,
        access=access,
        writer=writer,
        llm_client=llm_client,
        fetch_time_provider=lambda: BASE_TIME,
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


def test_llm_call_miss_then_hit_uses_cache_and_keeps_input_hashes(
    tmp_path: Path,
    rawstore: RawStore,
    audit: AuditLog,
    access: AccessLayer,
    writer: RawStoreWriter,
) -> None:
    args = _llm_args()
    response = LLMResponse(
        text="hello",
        input_tokens=10,
        output_tokens=5,
        raw_json={},
    )
    registry = SpecRegistry()
    spec_version = registry.register(finalize_spec(_llm_text_body(args)))

    artifacts_one = ArtifactStore(tmp_path / "artifacts-llm-one")
    artifacts_two = ArtifactStore(tmp_path / "artifacts-llm-two")
    try:
        stage_one = _runner(
            registry=registry,
            artifacts=artifacts_one,
            audit=audit,
            access=access,
            writer=writer,
            llm_client=StubLLMClient({_llm_key(args, "fixed prompt"): response}),
        )
        first = stage_one.run(
            RepresentInput(spec_version=spec_version, query_time=BASE_TIME.isoformat())
        )

        stage_two = _runner(
            registry=registry,
            artifacts=artifacts_two,
            audit=audit,
            access=access,
            writer=writer,
            llm_client=StubLLMClient({}),
        )
        second = stage_two.run(
            RepresentInput(spec_version=spec_version, query_time=BASE_TIME.isoformat())
        )

        assert first.outputs.tensor.item() == "hello"
        assert second.outputs.tensor.item() == "hello"
        assert first.outputs.tensor.tobytes() == second.outputs.tensor.tobytes()
        assert first.outputs.input_hashes == second.outputs.input_hashes
        assert first.output_hash == second.output_hash
        assert len(first.outputs.input_hashes) == 1
    finally:
        artifacts_one.close()
        artifacts_two.close()


def test_mixed_raw_get_and_llm_call_replays_same_tensor_bytes(
    tmp_path: Path,
    rawstore: RawStore,
    audit: AuditLog,
    access: AccessLayer,
    writer: RawStoreWriter,
) -> None:
    raw_hash = _put_json(rawstore, {"value": 3.5})
    body = _mixed_raw_llm_body(raw_hash)
    args = body["graph"]["nodes"][3]["args"]
    response = LLMResponse(
        text='{"score": 8.25}',
        input_tokens=20,
        output_tokens=10,
        raw_json={},
    )
    registry = SpecRegistry()
    spec_version = registry.register(finalize_spec(body))

    artifacts_one = ArtifactStore(tmp_path / "artifacts-mixed-one")
    artifacts_two = ArtifactStore(tmp_path / "artifacts-mixed-two")
    try:
        first = _runner(
            registry=registry,
            artifacts=artifacts_one,
            audit=audit,
            access=access,
            writer=writer,
            llm_client=StubLLMClient({_llm_key(args, "value is 3.5"): response}),
        ).run(RepresentInput(spec_version=spec_version, query_time=BASE_TIME.isoformat()))

        second = _runner(
            registry=registry,
            artifacts=artifacts_two,
            audit=audit,
            access=access,
            writer=writer,
            llm_client=StubLLMClient({}),
        ).run(RepresentInput(spec_version=spec_version, query_time=BASE_TIME.isoformat()))

        assert first.outputs.tensor.item() == pytest.approx(8.25)
        assert first.outputs.tensor.tobytes() == second.outputs.tensor.tobytes()
        assert first.output_hash == second.output_hash
        assert set(first.outputs.input_hashes) == set(second.outputs.input_hashes)
        assert raw_hash in first.outputs.input_hashes
        assert len(first.outputs.input_hashes) == 2
    finally:
        artifacts_one.close()
        artifacts_two.close()


def test_llm_cache_hash_is_not_required_in_deps_but_raw_get_still_is(
    rawstore: RawStore,
    artifacts: ArtifactStore,
    audit: AuditLog,
    access: AccessLayer,
    writer: RawStoreWriter,
) -> None:
    raw_hash = _put_json(rawstore, {"value": 4.0})
    body = _mixed_raw_llm_body(raw_hash)
    args = body["graph"]["nodes"][3]["args"]
    response = LLMResponse(text='{"score": 6.0}', input_tokens=10, output_tokens=4, raw_json={})
    registry = SpecRegistry()
    spec_version = registry.register(finalize_spec(body))
    result = _runner(
        registry=registry,
        artifacts=artifacts,
        audit=audit,
        access=access,
        writer=writer,
        llm_client=StubLLMClient({_llm_key(args, "value is 4.0"): response}),
    ).run(RepresentInput(spec_version=spec_version, query_time=BASE_TIME.isoformat()))

    assert result.outputs.tensor.item() == pytest.approx(6.0)
    assert raw_hash in result.outputs.input_hashes
    assert len(result.outputs.input_hashes) == 2

    missing_raw_dep = _mixed_raw_llm_body(raw_hash)
    missing_raw_dep["deps"] = []
    bad_registry = SpecRegistry()
    bad_spec = bad_registry.register(finalize_spec(missing_raw_dep))
    bad_stage = _runner(
        registry=bad_registry,
        artifacts=artifacts,
        audit=audit,
        access=access,
        writer=writer,
        llm_client=StubLLMClient({}),
    )
    with pytest.raises(DependencyEnvelopeError):
        bad_stage.run(RepresentInput(spec_version=bad_spec, query_time=BASE_TIME.isoformat()))


def test_represent_stage_requires_writer_before_llm_execution(
    artifacts: ArtifactStore,
    audit: AuditLog,
    access: AccessLayer,
) -> None:
    registry = SpecRegistry()
    spec_version = registry.register(finalize_spec(_llm_text_body()))
    stage = _runner(
        registry=registry,
        artifacts=artifacts,
        audit=audit,
        access=access,
        writer=None,
        llm_client=StubLLMClient({}),
    )

    with pytest.raises(RuntimeError, match="requires a writer"):
        stage.run(RepresentInput(spec_version=spec_version, query_time=BASE_TIME.isoformat()))


def test_cost_drift_records_on_miss_and_hit(
    tmp_path: Path,
    rawstore: RawStore,
    audit: AuditLog,
    access: AccessLayer,
    writer: RawStoreWriter,
) -> None:
    args = _llm_args(declared_cost_usd=0.001, cost_tolerance=0.20)
    response = LLMResponse(text="hello", input_tokens=1000, output_tokens=1000, raw_json={})
    registry = SpecRegistry()
    spec_version = registry.register(finalize_spec(_llm_text_body(args)))
    artifacts_one = ArtifactStore(tmp_path / "artifacts-drift-one")
    artifacts_two = ArtifactStore(tmp_path / "artifacts-drift-two")
    try:
        miss = _runner(
            registry=registry,
            artifacts=artifacts_one,
            audit=audit,
            access=access,
            writer=writer,
            llm_client=StubLLMClient({_llm_key(args, "fixed prompt"): response}),
        ).run(RepresentInput(spec_version=spec_version, query_time=BASE_TIME.isoformat()))
        hit = _runner(
            registry=registry,
            artifacts=artifacts_two,
            audit=audit,
            access=access,
            writer=writer,
            llm_client=StubLLMClient({}),
        ).run(RepresentInput(spec_version=spec_version, query_time=BASE_TIME.isoformat()))
    finally:
        artifacts_one.close()
        artifacts_two.close()

    drift_records = [r for r in _audit_records(audit) if r["category"] == "CostDrift"]
    assert len(drift_records) == 2
    assert {r["node_id"] for r in drift_records} == {"call"}
    assert drift_records[0]["realized_usd"] == pytest.approx(0.0028)
    assert miss.outputs.cost_used.llm_usd == pytest.approx(0.0028)
    assert hit.outputs.cost_used.llm_usd == pytest.approx(0.0028)


def test_cost_drift_within_tolerance_emits_no_record(
    rawstore: RawStore,
    artifacts: ArtifactStore,
    audit: AuditLog,
    access: AccessLayer,
    writer: RawStoreWriter,
) -> None:
    args = _llm_args(declared_cost_usd=0.003, cost_tolerance=0.20)
    p_hash = prompt_hash("fixed prompt")
    par_hash = params_hash(model=args["model"], params=args["params"])
    _seed_llm_cache(
        rawstore,
        model=args["model"],
        prompt_hash_value=p_hash,
        params_hash_value=par_hash,
        text="hello",
        input_tokens=1000,
        output_tokens=1000,
    )
    registry = SpecRegistry()
    spec_version = registry.register(finalize_spec(_llm_text_body(args)))
    _runner(
        registry=registry,
        artifacts=artifacts,
        audit=audit,
        access=access,
        writer=writer,
        llm_client=StubLLMClient({}),
    ).run(RepresentInput(spec_version=spec_version, query_time=BASE_TIME.isoformat()))

    assert [r for r in _audit_records(audit) if r["category"] == "CostDrift"] == []


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
