from __future__ import annotations

import json
from datetime import timedelta, timezone
from pathlib import Path

import pytest

from access import AccessLayer, TemporalAdmissibilityError
from audit import AuditLog
from rawstore import Provenance, RawStore
from represent import SpecRegistry, finalize_spec
from rule.grounding import load_grounding

from .fixtures.helpers import BASE_T, GROUND_SPEC, SeriesRegistry, tick


def _grounding(assertion: dict) -> dict:
    return {
        "spec_ref": GROUND_SPEC,
        "assertion": assertion,
        "window": {"t0": tick(0).isoformat(), "t1": tick(2).isoformat()},
    }


def test_in_range_grounding_passes_and_fails() -> None:
    registry = SeriesRegistry({GROUND_SPEC: [1, 2, 3]})
    assert load_grounding(_grounding({"kind": "in_range", "lo": 1.0, "hi": 3.0})).evaluate(
        object(), registry
    )
    assert not load_grounding(_grounding({"kind": "in_range", "lo": 3.1, "hi": 4.0})).evaluate(
        object(), registry
    )


def test_quantile_ge_grounding_passes_and_fails() -> None:
    registry = SeriesRegistry({GROUND_SPEC: [1, 2, 3]})
    assert load_grounding(
        _grounding({"kind": "quantile_ge", "p": 0.5, "threshold": 2.0})
    ).evaluate(object(), registry)
    assert not load_grounding(
        _grounding({"kind": "quantile_ge", "p": 0.5, "threshold": 2.5})
    ).evaluate(object(), registry)


def test_sign_grounding_passes_and_fails() -> None:
    registry = SeriesRegistry({GROUND_SPEC: [1, 2, -1]})
    assert load_grounding(_grounding({"kind": "sign", "expected_sign": 1})).evaluate(
        object(), registry
    )
    assert not load_grounding(_grounding({"kind": "sign", "expected_sign": -1})).evaluate(
        object(), registry
    )


def test_grounding_future_window_is_caught_by_access_layer(tmp_path: Path) -> None:
    store = RawStore(tmp_path / "rs")
    audit = AuditLog(tmp_path / "audit")
    access = AccessLayer(store, audit, cycle_id="c1", max_reads_per_cycle=10)
    try:
        raw = json.dumps({"items": [1.0, 2.0, 3.0]}).encode("utf-8")
        raw_hash = store.put(
            raw,
            Provenance(
                "vendor",
                BASE_T.replace(tzinfo=timezone.utc),
                BASE_T.replace(tzinfo=timezone.utc) + timedelta(hours=1),
            ),
        )
        body = {
            "schema_version": 1,
            "name": "grounding_items",
            "graph": {
                "nodes": [
                    {"id": "read", "op": "raw_get", "args": {"hash": raw_hash}, "inputs": []},
                    {"id": "json", "op": "decode_json", "args": {}, "inputs": ["read"]},
                    {
                        "id": "items",
                        "op": "json_get",
                        "args": {"path": ["items"]},
                        "inputs": ["json"],
                    },
                    {"id": "out", "op": "cast_float64", "args": {}, "inputs": ["items"]},
                ],
                "output": "out",
            },
            "deps": [raw_hash],
            "cost": {"compute_usd": 0.0, "llm_usd": 0.0, "storage_bytes": 24},
            "output_schema": {"dtype": "float64", "shape": ["n"]},
        }
        spec_id = finalize_spec(body)["spec_id"]
        registry = SpecRegistry()
        registry.register(finalize_spec(body))
        grounding = load_grounding(
            {
                "spec_ref": spec_id,
                "assertion": {"kind": "in_range", "lo": 0.0, "hi": 10.0},
                "window": {
                    "t0": BASE_T.isoformat(),
                    "t1": (BASE_T + timedelta(minutes=1)).isoformat(),
                },
            }
        )

        with pytest.raises(TemporalAdmissibilityError):
            grounding.evaluate(access, registry)
    finally:
        store.close()
