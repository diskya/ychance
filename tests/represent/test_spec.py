from __future__ import annotations

from dataclasses import replace

import pytest

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
