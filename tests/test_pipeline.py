from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from access import AccessLayer
from audit import AuditLog
from pipeline import (
    ArtifactStore,
    CostCeiling,
    CostCeilingExceeded,
    InvariantViolation,
    PipelineDAG,
    Stage,
    StageContext,
)
from rawstore import Provenance, RawStore


BASE_T = datetime(2026, 4, 22, 12, 0, 0, tzinfo=timezone.utc)


# --- fixtures --------------------------------------------------------------

@pytest.fixture
def audit(tmp_path: Path) -> AuditLog:
    return AuditLog(tmp_path / "audit")


@pytest.fixture
def artifacts(tmp_path: Path):
    s = ArtifactStore(tmp_path / "art")
    try:
        yield s
    finally:
        s.close()


def _audit_records(log: AuditLog) -> list[dict]:
    records: list[dict] = []
    for path in sorted(log._root.glob("*.jsonl")):
        for line in path.read_text().splitlines():
            if line:
                records.append(json.loads(line))
    return records


# --- toy stages used throughout --------------------------------------------

@dataclass
class IntInput:
    value: int


@dataclass
class IntOutput:
    value: int


class AddOne(Stage):
    name = "addone"
    version = "1"
    cost_ceiling = CostCeiling(compute_usd=1.0)
    InputType = IntInput
    OutputType = IntOutput

    def compute(self, inputs: IntInput, ctx: StageContext) -> IntOutput:
        ctx.charge_compute(0.01)
        return IntOutput(value=inputs.value + 1)

    def invariant(self, inputs: IntInput, outputs: IntOutput) -> None:
        assert outputs.value == inputs.value + 1


class Double(Stage):
    name = "double"
    version = "1"
    cost_ceiling = CostCeiling(compute_usd=1.0)
    InputType = IntInput
    OutputType = IntOutput

    def compute(self, inputs: IntInput, ctx: StageContext) -> IntOutput:
        ctx.charge_compute(0.02)
        return IntOutput(value=inputs.value * 2)

    def invariant(self, inputs: IntInput, outputs: IntOutput) -> None:
        assert outputs.value == inputs.value * 2


# --- artifact store --------------------------------------------------------

def test_artifact_store_put_get_idempotent(artifacts: ArtifactStore) -> None:
    h1 = artifacts.put(b"hello")
    h2 = artifacts.put(b"hello")
    assert h1 == h2
    assert artifacts.get(h1) == b"hello"
    assert artifacts.has(h1)


def test_artifact_store_get_unknown_raises(artifacts: ArtifactStore) -> None:
    with pytest.raises(KeyError):
        artifacts.get("0" * 64)


def test_artifact_store_fingerprint_roundtrip(artifacts: ArtifactStore) -> None:
    h = artifacts.put(b"payload")
    artifacts.record_fingerprint(
        "fp1",
        stage_name="s",
        stage_version="1",
        inputs_hash="i1",
        output_hash=h,
    )
    assert artifacts.lookup_fingerprint("fp1") == h
    assert artifacts.lookup_fingerprint("nope") is None


def test_artifact_store_rejects_fingerprint_for_missing_artifact(
    artifacts: ArtifactStore,
) -> None:
    with pytest.raises(KeyError):
        artifacts.record_fingerprint(
            "fp1",
            stage_name="s",
            stage_version="1",
            inputs_hash="i1",
            output_hash="0" * 64,
        )


# --- stage basics ----------------------------------------------------------

def test_stage_run_emits_one_audit_record(
    artifacts: ArtifactStore, audit: AuditLog
) -> None:
    stage = AddOne(artifacts=artifacts, audit=audit)
    result = stage.run(IntInput(value=3), envelope={"cycle_id": "c1"})
    assert result.outputs == IntOutput(value=4)
    assert result.cache_hit is False
    records = _audit_records(audit)
    assert len(records) == 1
    r = records[0]
    assert r["category"] == "Stage"
    assert r["stage"] == "addone"
    assert r["stage_version"] == "1"
    assert r["envelope"] == {"cycle_id": "c1"}
    assert r["output_hash"] == result.output_hash
    assert r["compute_cost"] == 0.01
    assert r["llm_cost"] == 0.0
    assert r["data_reads"] == 0


def test_stage_rerun_same_inputs_is_cache_hit_no_audit(
    artifacts: ArtifactStore, audit: AuditLog
) -> None:
    stage = AddOne(artifacts=artifacts, audit=audit)
    r1 = stage.run(IntInput(value=3))
    before = len(_audit_records(audit))
    r2 = stage.run(IntInput(value=3))
    after = len(_audit_records(audit))
    assert r2.cache_hit is True
    assert r2.outputs == r1.outputs
    assert r2.output_hash == r1.output_hash
    assert after == before  # no new audit record


def test_stage_different_inputs_miss_cache(
    artifacts: ArtifactStore, audit: AuditLog
) -> None:
    stage = AddOne(artifacts=artifacts, audit=audit)
    stage.run(IntInput(value=3))
    stage.run(IntInput(value=4))
    records = _audit_records(audit)
    assert len(records) == 2


def test_stage_version_bump_invalidates_cache(
    artifacts: ArtifactStore, audit: AuditLog
) -> None:
    class AddOneV2(AddOne):
        version = "2"

    s1 = AddOne(artifacts=artifacts, audit=audit)
    s2 = AddOneV2(artifacts=artifacts, audit=audit)
    s1.run(IntInput(value=7))
    r2 = s2.run(IntInput(value=7))
    assert r2.cache_hit is False
    records = _audit_records(audit)
    assert len(records) == 2


def test_stage_rejects_wrong_input_type(
    artifacts: ArtifactStore, audit: AuditLog
) -> None:
    stage = AddOne(artifacts=artifacts, audit=audit)
    with pytest.raises(TypeError):
        stage.run({"value": 3})  # type: ignore[arg-type]


def test_stage_rejects_wrong_output_type(
    artifacts: ArtifactStore, audit: AuditLog
) -> None:
    class BadOutput(AddOne):
        name = "badout"

        def compute(self, inputs, ctx):  # type: ignore[override]
            ctx.charge_compute(0.01)
            return {"value": inputs.value + 1}  # not an IntOutput

    stage = BadOutput(artifacts=artifacts, audit=audit)
    with pytest.raises(TypeError):
        stage.run(IntInput(value=1))


def test_stage_requires_name_and_version(
    artifacts: ArtifactStore, audit: AuditLog
) -> None:
    class NoName(AddOne):
        name = ""

    with pytest.raises(ValueError):
        NoName(artifacts=artifacts, audit=audit)

    class NoVersion(AddOne):
        version = ""

    with pytest.raises(ValueError):
        NoVersion(artifacts=artifacts, audit=audit)


# --- cost ceiling ----------------------------------------------------------

def test_cost_ceiling_exceeded_raises(
    artifacts: ArtifactStore, audit: AuditLog
) -> None:
    class Greedy(AddOne):
        name = "greedy"
        cost_ceiling = CostCeiling(compute_usd=0.005)  # below the 0.01 charge

    stage = Greedy(artifacts=artifacts, audit=audit)
    with pytest.raises(CostCeilingExceeded):
        stage.run(IntInput(value=1))
    # No artifact cached; no audit record written.
    assert len(_audit_records(audit)) == 0


def test_cost_ceiling_charges_accumulate(
    artifacts: ArtifactStore, audit: AuditLog
) -> None:
    class Multicharge(AddOne):
        name = "multi"
        cost_ceiling = CostCeiling(compute_usd=0.05, llm_usd=0.10, data_reads=3)

        def compute(self, inputs, ctx):
            ctx.charge_compute(0.02)
            ctx.charge_compute(0.02)
            ctx.charge_llm(0.05)
            ctx.charge_data_read(2)
            return IntOutput(value=inputs.value + 1)

    stage = Multicharge(artifacts=artifacts, audit=audit)
    stage.run(IntInput(value=1))
    r = _audit_records(audit)[0]
    assert r["compute_cost"] == pytest.approx(0.04)
    assert r["llm_cost"] == pytest.approx(0.05)
    assert r["data_reads"] == 2


# --- invariants ------------------------------------------------------------

def test_invariant_violation_halts_and_does_not_cache(
    artifacts: ArtifactStore, audit: AuditLog
) -> None:
    class Broken(AddOne):
        name = "broken"

        def compute(self, inputs, ctx):
            ctx.charge_compute(0.01)
            return IntOutput(value=inputs.value + 999)  # violates invariant

    stage = Broken(artifacts=artifacts, audit=audit)
    with pytest.raises(AssertionError):
        stage.run(IntInput(value=1))
    assert len(_audit_records(audit)) == 0
    # Next call re-runs (no cache entry).
    with pytest.raises(AssertionError):
        stage.run(IntInput(value=1))


def test_invariant_returning_false_raises_invariant_violation(
    artifacts: ArtifactStore, audit: AuditLog
) -> None:
    class FalseInvariant(AddOne):
        name = "false_inv"

        def invariant(self, inputs, outputs):
            return False

    stage = FalseInvariant(artifacts=artifacts, audit=audit)
    with pytest.raises(InvariantViolation):
        stage.run(IntInput(value=1))


# --- DAG -------------------------------------------------------------------

def _make_dag(audit: AuditLog, artifacts: ArtifactStore) -> PipelineDAG:
    dag = PipelineDAG(audit=audit, envelope={"cycle_id": "c1"})
    dag.add(
        AddOne(artifacts=artifacts, audit=audit),
        inputs=lambda init, results: IntInput(value=init["x"]),
    )
    dag.add(
        Double(artifacts=artifacts, audit=audit),
        inputs=lambda init, results: IntInput(value=results["addone"].value),
    )
    return dag


def test_dag_runs_topologically_and_threads_outputs(
    artifacts: ArtifactStore, audit: AuditLog
) -> None:
    dag = _make_dag(audit, artifacts)
    results = dag.run({"x": 5})
    assert results["addone"].outputs == IntOutput(value=6)
    assert results["double"].outputs == IntOutput(value=12)


def test_dag_refuses_stage_without_invariant(
    artifacts: ArtifactStore, audit: AuditLog
) -> None:
    class NoInvariant(Stage):
        name = "noinv"
        version = "1"
        cost_ceiling = CostCeiling(compute_usd=1.0)
        InputType = IntInput
        OutputType = IntOutput

        def compute(self, inputs, ctx):
            return IntOutput(value=inputs.value)

    dag = PipelineDAG(audit=audit)
    with pytest.raises(ValueError, match="invariant"):
        dag.add(
            NoInvariant(artifacts=artifacts, audit=audit),
            inputs=lambda init, results: IntInput(value=init["x"]),
        )


def test_dag_refuses_stage_without_compute(
    artifacts: ArtifactStore, audit: AuditLog
) -> None:
    class NoCompute(Stage):
        name = "nocompute"
        version = "1"
        cost_ceiling = CostCeiling(compute_usd=1.0)
        InputType = IntInput
        OutputType = IntOutput

        def invariant(self, inputs, outputs):
            return None

    dag = PipelineDAG(audit=audit)
    with pytest.raises(ValueError, match="compute"):
        dag.add(
            NoCompute(artifacts=artifacts, audit=audit),
            inputs=lambda init, results: IntInput(value=init["x"]),
        )


def test_dag_refuses_duplicate_stage_names(
    artifacts: ArtifactStore, audit: AuditLog
) -> None:
    dag = PipelineDAG(audit=audit)
    dag.add(
        AddOne(artifacts=artifacts, audit=audit),
        inputs=lambda init, results: IntInput(value=init["x"]),
    )
    with pytest.raises(ValueError, match="duplicate"):
        dag.add(
            AddOne(artifacts=artifacts, audit=audit),
            inputs=lambda init, results: IntInput(value=init["x"]),
        )


def test_dag_emits_run_start_and_run_end_markers(
    artifacts: ArtifactStore, audit: AuditLog
) -> None:
    dag = _make_dag(audit, artifacts)
    dag.run({"x": 5})
    records = _audit_records(audit)
    # 1 run_start + 2 stage records + 1 run_end
    assert records[0]["category"] == "DAGRun"
    assert records[0]["event"] == "run_start"
    assert records[-1]["category"] == "DAGRun"
    assert records[-1]["event"] == "run_end"
    assert records[-1]["status"] == "success"
    assert records[0]["run_id"] == records[-1]["run_id"]
    # stage_order recorded
    assert records[0]["stage_order"] == ["addone", "double"]


# --- the phase-1.4 exit criterion ------------------------------------------

def test_rerun_unchanged_dag_emits_only_dag_markers(
    artifacts: ArtifactStore, audit: AuditLog
) -> None:
    """The 1.4 exit criterion: re-running an unchanged DAG must produce
    zero new audit records other than the re-run's DAG-level start/end
    markers. Stage cache hits must NOT write any record - not even a
    "skipped" marker - or the ledger grows unboundedly on idempotent
    reruns, which breaks the chain's cost and readability guarantees."""
    dag = _make_dag(audit, artifacts)
    dag.run({"x": 5})
    first_pass = _audit_records(audit)
    # Expect 1 start + 2 stage + 1 end = 4 records.
    assert len(first_pass) == 4
    assert [r.get("event") for r in first_pass if r["category"] == "DAGRun"] == [
        "run_start",
        "run_end",
    ]
    assert [r["stage"] for r in first_pass if r["category"] == "Stage"] == [
        "addone",
        "double",
    ]

    dag.run({"x": 5})
    second_pass = _audit_records(audit)
    new_records = second_pass[len(first_pass):]
    assert len(new_records) == 2
    assert [r["event"] for r in new_records] == ["run_start", "run_end"]
    assert all(r["category"] == "DAGRun" for r in new_records)
    # And the DAG signature is identical across the two runs.
    starts = [r for r in second_pass if r.get("event") == "run_start"]
    assert starts[0]["dag_signature"] == starts[1]["dag_signature"]

    # Cross-day check: the audit chain still verifies end-to-end after
    # two runs of cached stages.
    day_file = next(iter((audit._root).glob("*.jsonl")))
    day = datetime.fromisoformat(day_file.stem.replace(".jsonl", "") + "T00:00:00+00:00").date()
    assert audit.verify_chain(day) is True


def test_rerun_with_changed_input_re_executes(
    artifacts: ArtifactStore, audit: AuditLog
) -> None:
    dag = _make_dag(audit, artifacts)
    dag.run({"x": 5})
    first_pass = len(_audit_records(audit))
    dag.run({"x": 6})  # different initial input -> different inputs_hash
    new = _audit_records(audit)[first_pass:]
    # run_start + 2 stage records (both miss) + run_end
    kinds = [(r["category"], r.get("event") or r["stage"]) for r in new]
    assert kinds == [
        ("DAGRun", "run_start"),
        ("Stage", "addone"),
        ("Stage", "double"),
        ("DAGRun", "run_end"),
    ]


def test_dag_run_end_marker_still_emitted_on_failure(
    artifacts: ArtifactStore, audit: AuditLog
) -> None:
    class Fails(AddOne):
        name = "fails"

        def compute(self, inputs, ctx):
            ctx.charge_compute(0.01)
            raise RuntimeError("boom")

    dag = PipelineDAG(audit=audit, envelope={"cycle_id": "c1"})
    dag.add(
        Fails(artifacts=artifacts, audit=audit),
        inputs=lambda init, results: IntInput(value=init["x"]),
    )
    with pytest.raises(RuntimeError, match="boom"):
        dag.run({"x": 5})
    records = _audit_records(audit)
    events = [r.get("event") for r in records if r["category"] == "DAGRun"]
    assert events == ["run_start", "run_end"]
    end = [r for r in records if r.get("event") == "run_end"][0]
    assert end["status"] == "error"
    assert end["error"]["failed_stage"] == "fails"


# --- integration: stage with an AccessLayer --------------------------------

@dataclass
class ReadInput:
    rawstore_hash: str
    query_time_iso: str


@dataclass
class ReadOutput:
    bytes_size: int


class ReadStage(Stage):
    name = "readstage"
    version = "1"
    cost_ceiling = CostCeiling(compute_usd=0.0, data_reads=1)
    InputType = ReadInput
    OutputType = ReadOutput

    def compute(self, inputs: ReadInput, ctx: StageContext) -> ReadOutput:
        assert ctx.access is not None, "ReadStage requires AccessLayer"
        qt = datetime.fromisoformat(inputs.query_time_iso)
        data = ctx.access.get(inputs.rawstore_hash, query_time=qt)
        ctx.charge_data_read(1)
        return ReadOutput(bytes_size=len(data))

    def invariant(self, inputs, outputs):
        assert outputs.bytes_size >= 0


def test_stage_with_access_layer_reads_via_access(tmp_path: Path) -> None:
    """Stages never touch RawStore directly; they receive an AccessLayer.
    AccessLayer emits its own per-read audit record; the Stage emits a
    single Stage record for the invocation. Both should be present, and
    a re-run should see only the DAG markers (Access reads happen inside
    the stage's compute, which is skipped on cache hit)."""
    rs = RawStore(tmp_path / "rs")
    audit = AuditLog(tmp_path / "audit")
    artifacts = ArtifactStore(tmp_path / "art")
    access = AccessLayer(
        rs, audit, cycle_id="c1", max_reads_per_cycle=100
    )
    try:
        h = rs.put(
            b"payload-for-stage",
            Provenance(
                "vendor-A", BASE_T - timedelta(hours=1), BASE_T - timedelta(hours=1)
            ),
        )
        stage = ReadStage(artifacts=artifacts, audit=audit, access=access)
        dag = PipelineDAG(audit=audit, envelope={"cycle_id": "c1"})
        dag.add(
            stage,
            inputs=lambda init, results: ReadInput(
                rawstore_hash=h, query_time_iso=BASE_T.isoformat()
            ),
        )
        dag.run({})
        records_after_first = _audit_records(audit)
        # Access record for the get + Stage record for the stage + DAG
        # start + DAG end = 4.
        categories = [r["category"] for r in records_after_first]
        assert categories == ["DAGRun", "Access", "Stage", "DAGRun"]

        dag.run({})
        new = _audit_records(audit)[len(records_after_first):]
        # On re-run the compute is skipped, so no Access record, no
        # Stage record -- only the DAG markers.
        assert [r["category"] for r in new] == ["DAGRun", "DAGRun"]
        assert [r.get("event") for r in new] == ["run_start", "run_end"]
    finally:
        artifacts.close()
        rs.close()
