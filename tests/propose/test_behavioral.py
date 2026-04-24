"""Behavioral tests for Propose stage — integration with cache, budget, LLM, and rules."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from access import AccessLayer, RawStoreWriter
from audit import AuditLog
from pipeline import ArtifactStore, StageContext
from propose import (
    ProposeInput,
    ProposeOutput,
    ProposeStage,
    BudgetConfig,
)
from propose.prompts import make_draft_prompt, make_adjudicate_prompt
from rawstore import RawStore
from represent.llm_client import LLMResponse, StubLLMClient, prompt_hash, params_hash
from rule import Rule


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


def audit_records(log: AuditLog) -> list[dict]:
    records = []
    for path in sorted(log._root.glob("*.jsonl")):
        for line in path.read_text().splitlines():
            if line:
                records.append(json.loads(line))
    return records


def make_minimal_valid_rule_dict():
    """Create a minimal valid rule dict that round-trips cleanly.

    Context and exit must produce boolean values. This rule has:
    - context: always True
    - exit: always False
    Both are minimal but valid boolean DAGs.
    """
    return {
        "context": {
            "nodes": [{"id": "c0", "op": "literal", "args": {"value": True}, "inputs": []}],
            "output": "c0",
        },
        "exit": {
            "nodes": [{"id": "e0", "op": "literal", "args": {"value": False}, "inputs": []}],
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


# ============================================================================
# Test a: Cache hit on second invocation
# ============================================================================

def test_cache_hit_on_second_llm_call(artifacts, audit_log, access_layer, writer):
    """Cache hit on second invocation: same prompt twice → cached on second, stub call count = 1."""
    # Minimal valid rule dict
    valid_rule = make_minimal_valid_rule_dict()
    response_text = json.dumps([valid_rule])

    # Create a stub LLM client with a call counter
    class CountingStub:
        def __init__(self):
            self.call_count = 0

        def complete(self, *, model: str, prompt: str, params: dict) -> LLMResponse:
            self.call_count += 1
            return LLMResponse(
                text=response_text,
                input_tokens=100,
                output_tokens=50,
                raw_json={"choices": [{"message": {"content": response_text}}]},
            )

    stub_client = CountingStub()

    # Create stage with the counting stub client
    stage = ProposeStage(
        artifacts=artifacts,
        audit=audit_log,
        access=access_layer,
        writer=writer,
        llm_client=stub_client,
    )

    # Same prompt and params for both calls
    model = "qwen-plus"
    prompt = "Generate a candidate rule."
    params = {}
    query_time = datetime.now(timezone.utc)

    # First _call_llm invocation: cache miss
    result1 = stage._call_llm(
        pass_name="draft",
        model=model,
        prompt=prompt,
        ctx=StageContext(ceiling=stage.cost_ceiling, access=access_layer, writer=writer),
        query_time=query_time,
    )

    # Second _call_llm invocation with same params: cache hit
    result2 = stage._call_llm(
        pass_name="draft",
        model=model,
        prompt=prompt,
        ctx=StageContext(ceiling=stage.cost_ceiling, access=access_layer, writer=writer),
        query_time=query_time,
    )

    # Verify: stub client called only once (second call was cached)
    assert stub_client.call_count == 1, f"Expected 1 stub call, got {stub_client.call_count}"
    assert result1 == result2, "Both results should be identical"
    assert response_text in result1, "Response should contain the rule text"


# ============================================================================
# Test b: Malformed LLM output → zero candidates, no raise
# ============================================================================

def test_malformed_llm_output_no_raise(artifacts, audit_log, access_layer, writer):
    """Malformed LLM output → zero candidates, no raise, rejection recorded."""
    # Return invalid JSON (missing required keys)
    invalid_response = '{"context": {}, "exit": {}}'  # Missing many required fields

    # Generate the actual draft prompt to get the hash
    draft_prompt = make_draft_prompt(
        slice_description="test",
        available_specs=["spec1"],
        anti_patterns=None,
        live_rule_groundings=None,
    )
    p_hash = prompt_hash(draft_prompt)
    params_h = params_hash(model="qwen-plus", params={})

    stub_client = StubLLMClient(
        responses={
            ("qwen-plus", p_hash, params_h): LLMResponse(
                text=invalid_response,
                input_tokens=10,
                output_tokens=20,
                raw_json={"choices": [{"message": {"content": invalid_response}}]},
            ),
        }
    )

    stage = ProposeStage(
        artifacts=artifacts,
        audit=audit_log,
        access=access_layer,
        writer=writer,
        llm_client=stub_client,
    )

    inputs = ProposeInput(
        cycle_id="test",
        query_time=datetime.now(timezone.utc),
        slice_description="test",
        available_spec_ids=["spec1"],
    )

    ctx = StageContext(ceiling=stage.cost_ceiling, access=access_layer, writer=writer)

    # compute() should not raise, even with malformed output
    output = stage.compute(inputs, ctx)

    # Assert no candidates emitted
    assert output.candidates == [], "Expected zero candidates from malformed output"
    assert isinstance(output, ProposeOutput), "Output should be a ProposeOutput"


# ============================================================================
# Test c: Budget exhaustion → no LLM client calls
# ============================================================================

def test_budget_exhaustion_no_llm_calls(artifacts, audit_log, access_layer, writer):
    """Budget exhaustion (target_candidates_per_cycle=0) → zero LLM calls, zero candidates."""

    class CountingStub:
        def __init__(self):
            self.call_count = 0

        def complete(self, *, model: str, prompt: str, params: dict) -> LLMResponse:
            self.call_count += 1
            return LLMResponse(text="[]", input_tokens=0, output_tokens=0, raw_json={})

    stub_client = CountingStub()

    # BudgetConfig with zero target candidates per cycle
    zero_budget = BudgetConfig(
        target_candidates_per_cycle=0,
        draft_lm_budget_usd=2.0,
        adjudicate_lm_budget_usd=3.0,
        draft_score_threshold=0.5,
    )

    stage = ProposeStage(
        artifacts=artifacts,
        audit=audit_log,
        access=access_layer,
        writer=writer,
        llm_client=stub_client,
        budget_config=zero_budget,
    )

    inputs = ProposeInput(
        cycle_id="test",
        query_time=datetime.now(timezone.utc),
        slice_description="test",
        available_spec_ids=["spec1"],
    )

    ctx = StageContext(ceiling=stage.cost_ceiling, access=access_layer, writer=writer)

    # With zero target_candidates_per_cycle, compute should short-circuit
    # and return no candidates without calling the LLM
    output = stage.compute(inputs, ctx)

    # Assert: no LLM calls and no candidates
    assert stub_client.call_count == 0, f"Expected 0 LLM calls, got {stub_client.call_count}"
    assert output.candidates == [], "Expected zero candidates with exhausted budget"


# ============================================================================
# Test d: Empty anti-pattern + empty live-grounding → valid fixture rule end-to-end
# ============================================================================

def test_empty_anti_pattern_and_grounding_emits_valid_rule(
    artifacts, audit_log, access_layer, writer
):
    """Empty anti-pattern + empty live-grounding → emits valid rule that round-trips."""
    valid_rule = make_minimal_valid_rule_dict()

    # Generate the draft prompt to get the hash
    draft_prompt = make_draft_prompt(
        slice_description="test",
        available_specs=["spec1"],
        anti_patterns=None,
        live_rule_groundings=None,
    )
    draft_hash = prompt_hash(draft_prompt)
    params_h = params_hash(model="qwen-plus", params={})

    # For adjudicate pass, generate the actual prompt with the candidates
    adjudicate_response = json.dumps({"decisions": [{"index": 0, "keep": True, "assessment": "Valid"}]})
    adjudicate_prompt = make_adjudicate_prompt(
        candidates_json=json.dumps([valid_rule]),
        candidate_count=1,
    )
    adjudicate_hash = prompt_hash(adjudicate_prompt)

    stub_client = StubLLMClient(
        responses={
            ("qwen-plus", draft_hash, params_h): LLMResponse(
                text=json.dumps([valid_rule]),
                input_tokens=100,
                output_tokens=50,
                raw_json={"choices": [{"message": {"content": json.dumps([valid_rule])}}]},
            ),
            ("qwen-plus", adjudicate_hash, params_h): LLMResponse(
                text=adjudicate_response,
                input_tokens=100,
                output_tokens=50,
                raw_json={"choices": [{"message": {"content": adjudicate_response}}]},
            ),
        }
    )

    stage = ProposeStage(
        artifacts=artifacts,
        audit=audit_log,
        access=access_layer,
        writer=writer,
        llm_client=stub_client,
    )

    # ProposeInput with None anti_pattern_list and live_rule_groundings (defaults)
    inputs = ProposeInput(
        cycle_id="test",
        query_time=datetime.now(timezone.utc),
        slice_description="test",
        available_spec_ids=["spec1"],
        anti_pattern_list=None,
        live_rule_groundings=None,
    )

    ctx = StageContext(ceiling=stage.cost_ceiling, access=access_layer, writer=writer)

    output = stage.compute(inputs, ctx)

    # Assert at least one candidate was emitted
    assert len(output.candidates) > 0, f"Expected at least one candidate, got {len(output.candidates)}"

    # Assert the first candidate is a Rule with a rule_id
    candidate = output.candidates[0]
    assert isinstance(candidate, Rule), "Candidate should be a Rule"
    assert hasattr(candidate, "rule_id"), "Candidate should have a rule_id"
    assert candidate.rule_id is not None, "rule_id should not be None"

    # Assert round-trip: serialize and load back
    candidate_dict = candidate.to_dict()
    from rule import load_rule
    reloaded = load_rule(candidate_dict)
    assert reloaded.rule_id == candidate.rule_id, "rule_id should survive round-trip"


def test_stage_run_records_candidate_and_llm_audit_payload(
    artifacts, audit_log, access_layer, writer
):
    """Stage audit contains candidate-level verdicts and prompt/response hashes."""
    valid_rule = make_minimal_valid_rule_dict()

    draft_prompt = make_draft_prompt(
        slice_description="test",
        available_specs=["spec1"],
        anti_patterns=None,
        live_rule_groundings=None,
    )
    params_h = params_hash(model="qwen-plus", params={})
    draft_hash = prompt_hash(draft_prompt)

    adjudicate_response = json.dumps(
        {"decisions": [{"index": 0, "keep": True, "assessment": "Valid"}]}
    )
    adjudicate_prompt = make_adjudicate_prompt(
        candidates_json=json.dumps([valid_rule]),
        candidate_count=1,
    )
    adjudicate_hash = prompt_hash(adjudicate_prompt)

    stub_client = StubLLMClient(
        responses={
            ("qwen-plus", draft_hash, params_h): LLMResponse(
                text=json.dumps([valid_rule]),
                input_tokens=100,
                output_tokens=50,
                raw_json={"choices": [{"message": {"content": json.dumps([valid_rule])}}]},
            ),
            ("qwen-plus", adjudicate_hash, params_h): LLMResponse(
                text=adjudicate_response,
                input_tokens=90,
                output_tokens=40,
                raw_json={"choices": [{"message": {"content": adjudicate_response}}]},
            ),
        }
    )

    stage = ProposeStage(
        artifacts=artifacts,
        audit=audit_log,
        access=access_layer,
        writer=writer,
        llm_client=stub_client,
    )

    result = stage.run(
        ProposeInput(
            cycle_id="test",
            query_time=datetime.now(timezone.utc),
            slice_description="test",
            available_spec_ids=["spec1"],
            input_slice_hashes=["c" * 64],
        ),
        envelope={"cycle_id": "test"},
    )

    assert len(result.outputs.candidates) == 1
    propose_records = [r for r in audit_records(audit_log) if r["category"] == "Propose"]
    assert len(propose_records) == 1
    record = propose_records[0]
    assert record["input_slice_hashes"] == ["c" * 64]
    assert len(record["candidate_audits"]) == 1
    candidate_record = record["candidate_audits"][0]
    assert candidate_record["verdict"] == "accepted"
    assert candidate_record["free_text_rationale"] == "Valid"
    assert candidate_record["rule_id"] in record["accepted_rule_ids"]
    assert len(record["llm_calls"]) == 2
    assert {call["pass_name"] for call in record["llm_calls"]} == {"draft", "adjudicate"}
    assert all(call["prompt_hash"] and call["response_hash"] for call in record["llm_calls"])


# ============================================================================
# Test e: No real Qwen client instantiation in test files
# ============================================================================

def test_no_real_llm_client_in_tests():
    """Static check: no test file under tests/propose/ instantiates real LLM client classes."""
    test_dir = Path("/home/ubuntu/ychance/tests/propose")
    test_files = list(test_dir.glob("*.py"))

    # Search for real client class constructors in other test files (exclude self)
    real_client_patterns = [
        "QwenOpenAICompatibleClient(",
    ]

    found_real_clients = []
    for test_file in test_files:
        # Skip this file itself since it's checking for patterns
        if test_file.name == "test_behavioral.py":
            continue

        content = test_file.read_text()
        lines = content.split("\n")
        for i, line in enumerate(lines, 1):
            for pattern in real_client_patterns:
                if pattern in line and not line.strip().startswith("#"):
                    found_real_clients.append(f"{test_file.name}:{i}: {line.strip()}")

    # Should be empty — all tests use StubLLMClient
    assert (
        not found_real_clients
    ), f"Found real LLM client instantiation in tests: {found_real_clients}"
