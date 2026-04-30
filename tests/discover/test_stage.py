from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from access import AccessLayer, RawStoreWriter, WindowReservationBook
from audit import AuditLog
from discover import DiscoverInput, DiscoverStage, DiscoverToolRouter, DiscoverToolState, ToolCallError
from discover.audit import digest_jsonable
from discover.budget import CycleBudget
from pattern import finalize_pattern
from pipeline import ArtifactStore, StageContext
from rawstore import Provenance, RawStore
from represent import LLMResponse, SpecRegistry, finalize_spec


BASE_TIME = datetime(2026, 4, 23, 12, 0, 0, tzinfo=timezone.utc)


class QueueLLM:
    def __init__(self, responses: list[str], *, cost_usd: float = 0.0001) -> None:
        self._responses = list(responses)
        self.cost_usd = cost_usd
        self.calls: list[dict[str, Any]] = []

    def complete(self, *, model: str, prompt: str, params: dict[str, Any]) -> LLMResponse:
        self.calls.append({"model": model, "prompt": prompt, "params": dict(params)})
        if not self._responses:
            raise AssertionError("unexpected Discover model call")
        return LLMResponse(
            text=self._responses.pop(0),
            input_tokens=10,
            output_tokens=5,
            raw_json={"cost_usd": self.cost_usd},
        )


@pytest.fixture
def stack(tmp_path: Path):
    store = RawStore(tmp_path / "rawstore")
    audit = AuditLog(tmp_path / "audit")
    artifacts = ArtifactStore(tmp_path / "artifacts")
    reservations = WindowReservationBook(tmp_path / "reservations")
    access = AccessLayer(
        store,
        audit,
        cycle_id="bootstrap",
        max_reads_per_cycle=100,
        reservation_book=reservations,
    )
    writer = RawStoreWriter(store, audit)
    registry = SpecRegistry()
    try:
        yield {
            "store": store,
            "audit": audit,
            "artifacts": artifacts,
            "reservations": reservations,
            "access": access,
            "writer": writer,
            "registry": registry,
        }
    finally:
        artifacts.close()
        reservations.close()
        store.close()


def _audit_records(log: AuditLog) -> list[dict]:
    records: list[dict] = []
    for path in sorted(log._root.glob("*.jsonl")):
        for line in path.read_text().splitlines():
            if line:
                records.append(json.loads(line))
    return records


def _put_json(store: RawStore, payload: dict) -> str:
    data = json.dumps(payload, sort_keys=True).encode("utf-8")
    return store.put(
        data,
        Provenance(
            "source-A",
            BASE_TIME - timedelta(hours=2),
            BASE_TIME - timedelta(hours=2),
        ),
    )


def _scalar_spec(raw_hash: str) -> dict:
    return {
        "schema_version": 1,
        "name": "scalar_spec",
        "graph": {
            "nodes": [
                {"id": "read", "op": "raw_get", "args": {"hash": raw_hash}, "inputs": []},
                {"id": "parsed", "op": "decode_json", "args": {}, "inputs": ["read"]},
                {"id": "picked", "op": "json_get", "args": {"path": ["value"]}, "inputs": ["parsed"]},
                {"id": "cast", "op": "cast_float64", "args": {}, "inputs": ["picked"]},
            ],
            "output": "cast",
        },
        "deps": [raw_hash],
        "cost": {"compute_usd": 0.0001, "llm_usd": 0.0, "storage_bytes": 8},
        "output_schema": {"dtype": "float64", "shape": []},
    }


def _register_scalar(registry: SpecRegistry, store: RawStore) -> str:
    raw_hash = _put_json(store, {"value": 2.0})
    spec = finalize_spec(_scalar_spec(raw_hash))
    return registry.register(spec)


def _window(start_hours: int, end_hours: int) -> dict[str, str]:
    return {
        "t0": (BASE_TIME + timedelta(hours=start_hours)).isoformat(),
        "t1": (BASE_TIME + timedelta(hours=end_hours)).isoformat(),
    }


def _assertion() -> dict:
    return {"kind": "in_range", "args": {"lo": 1.0, "hi": 3.0}}


def _pattern_body(spec_id: str, window: dict[str, str]) -> dict:
    return {
        "spec_ref": spec_id,
        "assertion": _assertion(),
        "scope": {"kind": "all", "args": {}},
        "observation_window": dict(window),
        "replication_protocol": {
            "kind": "fixed_windows",
            "args": {
                "pass_threshold": 1.0,
                "windows": [_window(24, 25)],
            },
        },
    }


def _stage(stack: dict, cheap: QueueLLM, frontier: QueueLLM, **kwargs) -> DiscoverStage:
    config = {
        "cheap_model": "cheap-model",
        "frontier_model": "frontier-model",
        "cheap_call_reserved_usd": 0.001,
        "frontier_call_reserved_usd": 0.002,
        "cycle_cost_cap_usd": 0.05,
    }
    config.update(kwargs)
    return DiscoverStage(
        registry=stack["registry"],
        artifacts=stack["artifacts"],
        audit=stack["audit"],
        access=stack["access"],
        writer=stack["writer"],
        cheap_client=cheap,
        frontier_client=frontier,
        **config,
    )


def _input(spec_id: str, *, operator_inputs: tuple[str, ...] = ()) -> DiscoverInput:
    return DiscoverInput(
        cycle_id="cycle-1",
        query_time=BASE_TIME.isoformat(),
        spec_ids=(spec_id,),
        archive_snapshot_hash=None,
        anti_pattern_list_hash=None,
        operator_inputs=operator_inputs,
        max_patterns=1,
    )


def test_no_pattern_output_is_valid_and_audited(stack: dict) -> None:
    spec_id = _register_scalar(stack["registry"], stack["store"])
    cheap = QueueLLM(["NO_PATTERN"])
    frontier = QueueLLM([])
    result = _stage(stack, cheap, frontier).run(_input(spec_id), envelope={"cycle_id": "cycle-1"})

    assert result.outputs.status == "no_pattern"
    assert result.outputs.no_pattern_reason == "cheap_model_returned_no_pattern"
    assert result.outputs.pattern_ids == ()
    records = _audit_records(stack["audit"])
    assert any(r.get("kind") == "DiscoverNoPattern" for r in records)
    assert len(frontier.calls) == 0


def test_content_shaped_operator_input_is_rejected_and_omitted_from_prompt(stack: dict) -> None:
    spec_id = _register_scalar(stack["registry"], stack["store"])
    cheap = QueueLLM(["NO_PATTERN"])
    frontier = QueueLLM([])
    result = _stage(stack, cheap, frontier).run(
        _input(
            spec_id,
            operator_inputs=(
                "What about momentum?",
                "Compute that on a different window.",
            ),
        ),
        envelope={"cycle_id": "cycle-1"},
    )

    assert result.outputs.status == "no_pattern"
    inputs = [r for r in _audit_records(stack["audit"]) if r.get("kind") == "CoResearchInput"]
    assert [r["shape_classification"] for r in inputs] == ["flagged", "tool_request"]
    assert inputs[0]["input_text"] == "What about momentum?"
    assert "momentum" not in cheap.calls[0]["prompt"].lower()
    assert "Compute that" not in cheap.calls[0]["prompt"]


def test_cycle_cost_cap_stops_before_model_call(stack: dict) -> None:
    spec_id = _register_scalar(stack["registry"], stack["store"])
    cheap = QueueLLM(["NO_PATTERN"])
    frontier = QueueLLM([])
    stage = _stage(stack, cheap, frontier, cycle_cost_cap_usd=0.0005)
    result = stage.run(_input(spec_id), envelope={"cycle_id": "cycle-1"})

    assert result.outputs.status == "killed_budget"
    assert cheap.calls == []
    records = _audit_records(stack["audit"])
    assert any(r.get("kind") == "DiscoverBudgetKill" for r in records)
    assert not any(r.get("kind") == "DiscoverModelCall" for r in records)


def test_access_read_limit_exhaustion_returns_killed_budget(stack: dict) -> None:
    spec_id = _register_scalar(stack["registry"], stack["store"])
    limited_access = AccessLayer(
        stack["store"],
        stack["audit"],
        cycle_id="limited",
        max_reads_per_cycle=0,
        reservation_book=stack["reservations"],
    )
    local = dict(stack)
    local["access"] = limited_access
    cheap = QueueLLM(
        [
            json.dumps(
                {
                    "actions": [
                        {
                            "tool": "test_assertion",
                            "args": {
                                "spec_ref": spec_id,
                                "assertion": _assertion(),
                                "window": _window(-1, 0),
                            },
                        }
                    ]
                }
            )
        ]
    )
    frontier = QueueLLM([])
    result = _stage(local, cheap, frontier).run(_input(spec_id), envelope={"cycle_id": "cycle-1"})

    assert result.outputs.status == "killed_budget"
    records = _audit_records(stack["audit"])
    assert any(r.get("kind") == "DiscoverBudgetKill" for r in records)
    assert any(r.get("outcome") == "rate_limited" for r in records)


def test_submitted_pattern_reserves_observation_and_tool_touched_windows(stack: dict) -> None:
    spec_id = _register_scalar(stack["registry"], stack["store"])
    touch_window = _window(-3, -2)
    observed_window = _window(-1, 0)
    cheap = QueueLLM(
        [
            json.dumps(
                {
                    "actions": [
                        {"tool": "compute", "args": {"spec_id": spec_id, "window": touch_window}},
                        {
                            "tool": "test_assertion",
                            "args": {
                                "spec_ref": spec_id,
                                "assertion": _assertion(),
                                "window": observed_window,
                            },
                        },
                    ]
                }
            )
        ]
    )
    frontier = QueueLLM(
        [
            json.dumps(
                {
                    "actions": [
                        {
                            "tool": "submit_pattern",
                            "args": {"pattern_body": _pattern_body(spec_id, observed_window)},
                        }
                    ],
                    "rationale": "withheld review note",
                }
            )
        ]
    )
    result = _stage(stack, cheap, frontier).run(_input(spec_id), envelope={"cycle_id": "cycle-1"})

    assert result.outputs.status == "submitted"
    pattern_id = result.outputs.pattern_ids[0]
    touch_reservations = stack["reservations"].overlapping(
        pattern_id=pattern_id,
        t0=datetime.fromisoformat(touch_window["t0"]),
        t1=datetime.fromisoformat(touch_window["t1"]),
        stage="Discover",
    )
    observed_reservations = stack["reservations"].overlapping(
        pattern_id=pattern_id,
        t0=datetime.fromisoformat(observed_window["t0"]),
        t1=datetime.fromisoformat(observed_window["t1"]),
        stage="Discover",
    )
    assert touch_reservations
    assert observed_reservations
    pattern = json.loads(stack["artifacts"].get(result.outputs.pattern_artifact_hashes[0]))
    assert "rationale" not in pattern
    rationale_records = [r for r in _audit_records(stack["audit"]) if r.get("kind") == "DiscoverRationale"]
    assert rationale_records[0]["withheld_from_council"] is True


def test_audit_trace_reconstructs_output_tool_trace_hash(stack: dict) -> None:
    spec_id = _register_scalar(stack["registry"], stack["store"])
    observed_window = _window(-1, 0)
    cheap = QueueLLM(
        [
            json.dumps(
                {
                    "actions": [
                        {"tool": "inspect_spec", "args": {"spec_id": spec_id}},
                        {
                            "tool": "test_assertion",
                            "args": {
                                "spec_ref": spec_id,
                                "assertion": _assertion(),
                                "window": observed_window,
                            },
                        },
                    ]
                }
            )
        ]
    )
    frontier = QueueLLM(
        [
            json.dumps(
                {
                    "actions": [
                        {
                            "tool": "submit_pattern",
                            "args": {"pattern_body": _pattern_body(spec_id, observed_window)},
                        }
                    ]
                }
            )
        ]
    )
    result = _stage(stack, cheap, frontier).run(_input(spec_id), envelope={"cycle_id": "cycle-1"})

    ends = sorted(
        (r for r in _audit_records(stack["audit"]) if r.get("kind") == "DiscoverToolCallEnd"),
        key=lambda r: r["step_index"],
    )
    reconstructed = []
    for record in ends:
        reconstructed.append(
            {
                "tool_call_id": record["tool_call_id"],
                "step_index": record["step_index"],
                "phase": record["phase"],
                "tool_name": record["tool_name"],
                "args_hash": record["args_hash"],
                "result_hash": record["result_hash"],
                "outcome": record["outcome"],
                "error_type": record["error_type"],
                "cost_before": record["cost_before"],
                "cost_after": record["cost_after"],
            }
        )
    assert result.outputs.tool_trace_hash == digest_jsonable(reconstructed)


def test_cheap_iteration_cannot_call_submit_pattern(stack: dict) -> None:
    spec_id = _register_scalar(stack["registry"], stack["store"])
    cheap = QueueLLM(
        [
            json.dumps(
                {
                    "actions": [
                        {
                            "tool": "submit_pattern",
                            "args": {"pattern_body": _pattern_body(spec_id, _window(-1, 0))},
                        }
                    ]
                }
            )
        ]
    )
    frontier = QueueLLM([])
    result = _stage(stack, cheap, frontier).run(_input(spec_id), envelope={"cycle_id": "cycle-1"})

    assert result.outputs.status == "error"
    records = [r for r in _audit_records(stack["audit"]) if r.get("kind") == "DiscoverToolCallEnd"]
    assert records[0]["outcome"] == "rejected"
    assert records[0]["error_type"] == "PhaseToolViolation"
    assert frontier.calls == []


def test_frontier_submission_cannot_call_exploratory_tools(stack: dict) -> None:
    spec_id = _register_scalar(stack["registry"], stack["store"])
    observed_window = _window(-1, 0)
    cheap = QueueLLM(
        [
            json.dumps(
                {
                    "actions": [
                        {
                            "tool": "test_assertion",
                            "args": {
                                "spec_ref": spec_id,
                                "assertion": _assertion(),
                                "window": observed_window,
                            },
                        }
                    ]
                }
            )
        ]
    )
    frontier = QueueLLM([json.dumps({"actions": [{"tool": "inspect_spec", "args": {"spec_id": spec_id}}]})])
    result = _stage(stack, cheap, frontier).run(_input(spec_id), envelope={"cycle_id": "cycle-1"})

    assert result.outputs.status == "error"
    ends = [r for r in _audit_records(stack["audit"]) if r.get("kind") == "DiscoverToolCallEnd"]
    assert ends[-1]["phase"] == "frontier_submission"
    assert ends[-1]["tool_name"] == "inspect_spec"
    assert ends[-1]["outcome"] == "rejected"
    assert ends[-1]["error_type"] == "PhaseToolViolation"


def test_submit_pattern_requires_prior_successful_test_assertion(stack: dict) -> None:
    spec_id = _register_scalar(stack["registry"], stack["store"])
    router = DiscoverToolRouter(
        registry=stack["registry"],
        artifacts=stack["artifacts"],
        audit=stack["audit"],
        access=stack["access"],
        writer=stack["writer"],
    )
    state = DiscoverToolState(cycle_id="cycle-1", query_time=BASE_TIME.isoformat())
    budget = CycleBudget(cap_usd=0.05)
    ctx = StageContext(
        ceiling=DiscoverStage.cost_ceiling,
        access=stack["access"],
        writer=stack["writer"],
        envelope={"cycle_id": "cycle-1"},
    )

    with pytest.raises(ToolCallError):
        router.call(
            tool_name="submit_pattern",
            args={"pattern_body": finalize_pattern(_pattern_body(spec_id, _window(-1, 0)))},
            phase="frontier_submission",
            step_index=0,
            envelope={"cycle_id": "cycle-1"},
            state=state,
            budget=budget,
            ctx=ctx,
        )

    end = [r for r in _audit_records(stack["audit"]) if r.get("kind") == "DiscoverToolCallEnd"][0]
    assert end["outcome"] == "error"
    assert end["error_type"] == "PermissionError"
