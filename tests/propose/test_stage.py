"""Tests for the Propose stage."""

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import pytest

from access import AccessLayer, RawStoreWriter
from audit import AuditLog
from pipeline import ArtifactStore, CostUsage
from propose import ProposeInput, ProposeOutput, ProposeStage
from rawstore import RawStore
from represent.llm_client import LLMResponse, StubLLMClient
from rule import load_rule


@pytest.fixture
def temp_dir(tmp_path):
    return tmp_path


@pytest.fixture
def rawstore(temp_dir):
    return RawStore(temp_dir / "rawstore")


@pytest.fixture
def audit_log(temp_dir):
    return AuditLog(temp_dir / "audit")


@pytest.fixture
def artifacts(temp_dir):
    return ArtifactStore(temp_dir / "artifacts")


@pytest.fixture
def access_layer(rawstore, audit_log):
    return AccessLayer(rawstore, audit_log, cycle_id="test", max_reads_per_cycle=1000)


@pytest.fixture
def writer(rawstore, audit_log):
    return RawStoreWriter(rawstore, audit_log)


def make_minimal_rule_dict():
    """Create a minimal valid rule dict for testing."""
    return {
        "context": {
            "nodes": [{"id": "c0", "op": "literal", "args": {"value": 1}, "inputs": []}],
            "output": "c0",
        },
        "exit": {
            "nodes": [{"id": "e0", "op": "literal", "args": {"value": 1}, "inputs": []}],
            "output": "e0",
        },
        "action": {"side": "long", "size_multiplier": 1.0},
        "action_schema_version": 1,
        "horizon_bars": 10,
        "cadence": {"kind": "fixed_step", "step_seconds": 60},
        "grounding": {
            "spec_ref": "a" * 64,
            "assertion": {"kind": "sign", "expected_sign": 1},
            "window": {
                "t0": "2024-01-01T00:00:00+00:00",
                "t1": "2024-01-02T00:00:00+00:00",
            },
        },
        "price_spec_ref": "b" * 64,
    }


def test_propose_stage_initialization(artifacts, audit_log, access_layer, writer):
    """Test that ProposeStage initializes correctly."""
    stage = ProposeStage(
        artifacts=artifacts,
        audit=audit_log,
        access=access_layer,
        writer=writer,
        llm_client=None,
    )
    assert stage.name == "propose_stage"
    assert stage.audit_stage == "Propose"


def test_propose_stage_requires_writer(artifacts, audit_log, access_layer):
    """Test that compute raises if writer is not provided."""
    stage = ProposeStage(
        artifacts=artifacts,
        audit=audit_log,
        access=access_layer,
        writer=None,  # No writer
        llm_client=None,
    )

    inputs = ProposeInput(
        cycle_id="cycle1",
        query_time=datetime.now(timezone.utc).isoformat(),
        slice_description="test data",
        available_spec_ids=[],
    )

    from pipeline import StageContext
    ctx = StageContext(ceiling=stage.cost_ceiling, access=access_layer, writer=None)

    with pytest.raises(RuntimeError, match="requires a writer"):
        stage.compute(inputs, ctx)


def test_propose_stage_requires_llm_client(artifacts, audit_log, access_layer, writer):
    """Test that compute raises if LLM client is not provided."""
    stage = ProposeStage(
        artifacts=artifacts,
        audit=audit_log,
        access=access_layer,
        writer=writer,
        llm_client=None,
    )

    inputs = ProposeInput(
        cycle_id="cycle1",
        query_time=datetime.now(timezone.utc).isoformat(),
        slice_description="test data",
        available_spec_ids=[],
    )

    from pipeline import StageContext
    ctx = StageContext(ceiling=stage.cost_ceiling, access=access_layer, writer=writer)

    with pytest.raises(RuntimeError, match="requires an LLM client"):
        stage.compute(inputs, ctx)


def test_propose_stage_output_type():
    """Test that ProposeOutput is correct type."""
    output = ProposeOutput(candidates=[])
    assert isinstance(output.candidates, list)
    assert len(output.candidates) == 0


def test_propose_input_dataclass():
    """Test ProposeInput dataclass."""
    now = datetime.now(timezone.utc)
    inputs = ProposeInput(
        cycle_id="test_cycle",
        query_time=now,
        slice_description="test slice",
        available_spec_ids=["spec1", "spec2"],
        anti_pattern_list=[{"description": "avoid X"}],
        live_rule_groundings=[],
    )
    assert inputs.cycle_id == "test_cycle"
    assert inputs.query_time == now.isoformat()
    assert len(inputs.available_spec_ids) == 2
    assert len(inputs.anti_pattern_list) == 1


def test_propose_stage_invariant_checks_candidates(artifacts, audit_log):
    """Test that invariant validates output."""
    stage = ProposeStage(
        artifacts=artifacts,
        audit=audit_log,
    )

    inputs = ProposeInput(
        cycle_id="cycle1",
        query_time=datetime.now(timezone.utc),
        slice_description="test",
        available_spec_ids=[],
    )

    # Valid output
    output = ProposeOutput(candidates=[])
    stage.invariant(inputs, output)  # Should not raise

    # Invalid: not a list
    bad_output = ProposeOutput(candidates="not a list")
    with pytest.raises(Exception):
        stage.invariant(inputs, bad_output)
