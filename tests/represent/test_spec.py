from __future__ import annotations

from dataclasses import replace

import pytest

import represent.registry as registry_module
from represent import DEFAULT_OPS, SpecRegistry, SpecValidationError, finalize_spec


RAW_HASH = "a" * 64


def _base_body() -> dict:
    return {
        "schema_version": 1,
        "name": "trial_one",
        "graph": {
            "nodes": [
                {
                    "id": "read",
                    "op": "raw_get",
                    "args": {"hash": RAW_HASH},
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
        "deps": [RAW_HASH],
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


def _llm_body() -> dict:
    return {
        "schema_version": 1,
        "name": "llm_spec",
        "graph": {
            "nodes": [
                {
                    "id": "call",
                    "op": "llm_call",
                    "args": {
                        "model": "qwen-plus",
                        "prompt_template": "fixed prompt",
                        "params": {"temperature": 0, "max_tokens": 16},
                        "input_names": [],
                        "declared_cost_usd": 0.001,
                    },
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


def test_identical_spec_content_produces_identical_spec_id() -> None:
    first = finalize_spec(_base_body())
    second = finalize_spec(_base_body())

    assert first["spec_id"] == second["spec_id"]


def test_spec_id_changes_on_name_args_op_and_op_version() -> None:
    base = finalize_spec(_base_body())["spec_id"]

    name_body = _base_body()
    name_body["name"] = "trial_two"

    args_body = _base_body()
    args_body["graph"]["nodes"][2]["args"] = {"path": ["other_value"]}

    op_body = _base_body()
    op_body["graph"]["nodes"][1]["op"] = "decode_text"

    shifted_ops = dict(DEFAULT_OPS)
    shifted_ops["cast_float64"] = replace(shifted_ops["cast_float64"], op_version="2")

    assert finalize_spec(name_body)["spec_id"] != base
    assert finalize_spec(args_body)["spec_id"] != base
    assert finalize_spec(op_body)["spec_id"] != base
    assert finalize_spec(_base_body(), op_registry=shifted_ops)["spec_id"] != base


def test_llm_call_op_version_is_part_of_spec_id() -> None:
    base = finalize_spec(_llm_body())["spec_id"]

    shifted_ops = dict(DEFAULT_OPS)
    shifted_ops["llm_call"] = replace(shifted_ops["llm_call"], op_version="2")

    assert finalize_spec(_llm_body(), op_registry=shifted_ops)["spec_id"] != base


def test_llm_call_rejects_nonzero_temperature_at_finalize() -> None:
    body = _llm_body()
    body["graph"]["nodes"][0]["args"]["params"]["temperature"] = 0.1

    with pytest.raises(ValueError, match="temperature must be 0"):
        finalize_spec(body)


def test_llm_call_registration_does_not_mutate_default_ops() -> None:
    before = tuple(sorted(DEFAULT_OPS))

    registry = SpecRegistry()
    registry.register(finalize_spec(_llm_body()))
    registry.register(finalize_spec(_base_body()))

    assert tuple(sorted(DEFAULT_OPS)) == before


def test_registry_is_idempotent_and_rejects_wrong_spec_id() -> None:
    registry = SpecRegistry()
    finalized = finalize_spec(_base_body())

    first = registry.register(finalized)
    second = registry.register(finalized)

    assert first == second
    assert registry.list() == [first]

    wrong = dict(finalized)
    wrong["spec_id"] = "0" * 64
    with pytest.raises(SpecValidationError):
        registry.register(wrong)


def test_registry_register_raw_body_routes_through_finalize(monkeypatch: pytest.MonkeyPatch) -> None:
    original = registry_module.finalize_spec
    calls: list[str] = []

    def tracking_finalize(spec, *, op_registry=None):
        calls.append(spec["name"])
        return original(spec, op_registry=op_registry)

    monkeypatch.setattr(registry_module, "finalize_spec", tracking_finalize)
    registry = SpecRegistry()

    spec_version = registry.register(_base_body())

    assert calls == ["trial_one"]
    assert spec_version == finalize_spec(_base_body())["spec_id"]
