from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from access import AccessLayer
from audit import AuditLog
from originality import (
    MatcherDag,
    OriginalityConfig,
    OriginalityInput,
    OriginalityStage,
    ReviewFeedback,
    active_entries,
    binary,
    bound_anti_pattern_list,
    compute_grounding_stats,
    empty_seed_state,
    evaluate_matcher,
    literal,
    make_entry,
    make_state,
    review_anti_pattern_list,
    stat,
)
from pipeline import ArtifactStore
from rawstore import RawStore
from rule import finalize_rule
from tests.rule.fixtures.helpers import (
    GROUND_SPEC,
    OTHER_SPEC,
    PRICE_SPEC,
    SeriesRegistry,
    base_grounding,
    rule_body,
    tick,
)
from tests.rule.test_op_names_primitive import BLOCKLIST


def _records(log: AuditLog) -> list[dict]:
    out: list[dict] = []
    for path in sorted(log._root.glob("*.jsonl")):
        for line in path.read_text().splitlines():
            if line:
                out.append(json.loads(line))
    return out


@pytest.fixture
def artifacts(tmp_path: Path):
    store = ArtifactStore(tmp_path / "artifacts")
    try:
        yield store
    finally:
        store.close()


@pytest.fixture
def audit_log(tmp_path: Path) -> AuditLog:
    return AuditLog(tmp_path / "audit")


@pytest.fixture
def access_layer(tmp_path: Path, audit_log: AuditLog) -> AccessLayer:
    return AccessLayer(
        RawStore(tmp_path / "raw"),
        audit_log,
        cycle_id="c1",
        max_reads_per_cycle=100,
    )


def _registry() -> SeriesRegistry:
    return SeriesRegistry(
        {
            PRICE_SPEC: [100, 101, 102, 103, 104, 105],
            GROUND_SPEC: [1, 2, 3, 4, 5, 6],
            OTHER_SPEC: [0, 0, 0, 0, 0, 0],
        }
    )


def _grounding(spec_ref: str) -> dict:
    body = base_grounding("in_range")
    body["spec_ref"] = spec_ref
    body["window"] = {"t0": tick(0).isoformat(), "t1": tick(4).isoformat()}
    return body


def _rule(spec_ref: str = GROUND_SPEC):
    return finalize_rule(rule_body(grounding=_grounding(spec_ref)))


def _gt_mean_entry(
    threshold: float = 2.0,
    *,
    active: bool = True,
    created_cycle: int = 0,
    last_hit_cycle: int | None = None,
    keep_score: str = "1",
):
    dag = MatcherDag(
        nodes=(
            stat("mean", "mean"),
            literal(threshold, "threshold"),
            binary("out", "gt", "mean", "threshold"),
        ),
        output="out",
    )
    return make_entry(
        matcher=dag,
        created_cycle=created_cycle,
        active=active,
        last_hit_cycle=last_hit_cycle,
        keep_score=keep_score,
    )


def _stage(artifacts, audit_log, access_layer) -> OriginalityStage:
    return OriginalityStage(
        registry=_registry(),
        artifacts=artifacts,
        audit=audit_log,
        access=access_layer,
    )


def test_empty_seed_passes_candidates(artifacts, audit_log, access_layer):
    rule = _rule()
    stage = _stage(artifacts, audit_log, access_layer)

    result = stage.run(
        OriginalityInput(
            cycle_id="c1",
            cycle_index=1,
            candidates=(rule,),
            anti_pattern_state=empty_seed_state(),
        ),
        envelope={"cycle_id": "c1"},
    )

    assert [item.rule_id for item in result.outputs.accepted_rules] == [rule.rule_id]
    assert result.outputs.decisions[0].result == "pass"
    assert result.outputs.decisions[0].matched_anti_pattern is None


def test_pass_and_reject_decisions(artifacts, audit_log, access_layer):
    rejected_rule = _rule(GROUND_SPEC)
    passed_rule = _rule(OTHER_SPEC)
    entry = _gt_mean_entry()
    state = make_state((entry,))
    stage = _stage(artifacts, audit_log, access_layer)

    result = stage.run(
        OriginalityInput(
            cycle_id="c1",
            cycle_index=2,
            candidates=(rejected_rule, passed_rule),
            anti_pattern_state=state,
        ),
        envelope={"cycle_id": "c1"},
    )

    decisions = result.outputs.decisions
    assert decisions[0].result == "reject"
    assert decisions[0].matched_anti_pattern == entry.entry_id
    assert decisions[1].result == "pass"
    assert [item.rule_id for item in result.outputs.accepted_rules] == [passed_rule.rule_id]


def test_reducibility_matcher_uses_stats(access_layer):
    rule = _rule(GROUND_SPEC)
    stats_obj = compute_grounding_stats(rule, access_layer, _registry())
    dag = MatcherDag(
        nodes=(
            stat("mean", "mean"),
            literal(1.5, "half"),
            binary("twice", "mul", "mean", "half"),
            literal(4.0, "limit"),
            binary("out", "gt", "twice", "limit"),
        ),
        output="out",
    )

    did_match, trace = evaluate_matcher(dag, stats_obj)

    assert did_match is True
    assert trace.trace_hash


def test_bounded_list_behavior():
    entries = tuple(
        _gt_mean_entry(
            threshold=float(i),
            created_cycle=i,
            keep_score=str(i),
        )
        for i in range(12)
    )
    state = make_state(entries)
    config = OriginalityConfig(target_size=3, max_size=5, stale_after_cycles=10)

    bounded = bound_anti_pattern_list(state, config)

    assert len(bounded.entries) <= 5
    assert len(active_entries(bounded)) <= 3
    assert {entry.keep_score for entry in active_entries(bounded)} == {"9", "10", "11"}


def test_stale_retirement():
    state = make_state(
        (
            _gt_mean_entry(created_cycle=0, last_hit_cycle=1),
        )
    )
    entry = state.entries[0]
    config = OriginalityConfig(target_size=10, max_size=10, stale_after_cycles=3)

    reviewed = review_anti_pattern_list(
        state,
        ReviewFeedback(
            m2a_id="m1",
            current_cycle=4,
            meta_validation_passed=True,
        ),
        config,
    )

    assert reviewed.retired_entry_ids == (entry.entry_id,)
    assert active_entries(reviewed.state) == ()


def test_m2a_rejection_empties_active_list():
    entry_a = _gt_mean_entry(threshold=2.0, created_cycle=0)
    entry_b = _gt_mean_entry(threshold=3.0, created_cycle=1)
    state = make_state((entry_a, entry_b))
    config = OriginalityConfig()

    reviewed = review_anti_pattern_list(
        state,
        ReviewFeedback(
            m2a_id="m1",
            current_cycle=7,
            meta_validation_passed=False,
        ),
        config,
    )

    assert reviewed.state.entries == ()
    assert set(reviewed.retired_entry_ids) == {entry_a.entry_id, entry_b.entry_id}


def test_audit_payload_shape(artifacts, audit_log, access_layer):
    rule = _rule(GROUND_SPEC)
    entry = _gt_mean_entry()
    state = make_state((entry,))
    stage = _stage(artifacts, audit_log, access_layer)

    stage.run(
        OriginalityInput(
            cycle_id="c1",
            cycle_index=3,
            candidates=(rule,),
            anti_pattern_state=state,
        ),
        envelope={"cycle_id": "c1"},
    )

    records = [record for record in _records(audit_log) if record["category"] == "Originality-filter"]
    assert len(records) == 1
    record = records[0]
    assert record["stage"] == "Propose"
    assert record["anti_pattern_list_version"] == state.version
    assert record["state_hash_before"]
    assert record["state_hash_after"]
    assert record["config_hash"]
    decision = record["decisions"][0]
    assert decision["rule_id"] == rule.rule_id
    assert decision["result"] == "reject"
    assert decision["matched_anti_pattern"] == entry.entry_id
    assert decision["anti_pattern_list_version"] == state.version
    assert decision["stats_hash"]
    assert decision["trace_hash"]


def test_originality_source_guardrail():
    root = Path(__file__).resolve().parents[2] / "originality"
    token_re = re.compile(r"\b(" + "|".join(sorted(BLOCKLIST)) + r")\b", re.IGNORECASE)

    for path in sorted(root.glob("*.py")):
        text = path.read_text()
        match = token_re.search(text)
        assert match is None, f"{path.name} contains blocked token {match.group(0)!r}"


def test_originality_has_no_direct_rawstore_import():
    root = Path(__file__).resolve().parents[2] / "originality"

    for path in sorted(root.glob("*.py")):
        text = path.read_text()
        assert "from rawstore" not in text
        assert "import rawstore" not in text
