from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from hypothesis import given, settings, strategies as st

from access import (
    AccessLayer,
    RateLimitExceeded,
    RawStoreWriter,
    TemporalAdmissibilityError,
    WindowReservationBook,
    WindowReservationError,
)
from audit import AuditLog, canonicalize
from rawstore import Provenance, RawStore


BASE_T = datetime(2026, 4, 22, 12, 0, 0, tzinfo=timezone.utc)


def _prov(
    source: str = "vendor-A",
    fetch: datetime = BASE_T,
    vendor: datetime = BASE_T,
) -> Provenance:
    return Provenance(source, fetch, vendor)


@pytest.fixture
def stack(tmp_path: Path):
    store = RawStore(tmp_path / "rs")
    log = AuditLog(tmp_path / "audit")
    access = AccessLayer(
        store, log, cycle_id="cycle-1", max_reads_per_cycle=1000
    )
    try:
        yield store, log, access
    finally:
        store.close()


def _audit_records(log: AuditLog) -> list[dict]:
    records: list[dict] = []
    for path in sorted(log._root.glob("*.jsonl")):
        for line in path.read_text().splitlines():
            if line:
                records.append(json.loads(line))
    return records


def _prompt_hash(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def _params_hash(model: str, params: dict) -> str:
    return hashlib.sha256(canonicalize({"model": model, "params": params})).hexdigest()


# --- construction ----------------------------------------------------------

def test_access_does_not_expose_rawstore_reader_capability(stack):
    store, _, access = stack
    h = store.put(b"guarded", _prov())
    assert not hasattr(access, "_AccessLayer__store")
    assert not hasattr(access, "_AccessLayer__reader")
    with pytest.raises(PermissionError):
        store.get(h, reader=access)  # type: ignore[arg-type]


def test_access_hides_store_bound_reader_from_attribute_lookup(stack):
    _, _, access = stack
    with pytest.raises(AttributeError):
        _ = access._AccessLayer__store
    with pytest.raises(AttributeError):
        _ = access._AccessLayer__reader


def test_rawstore_writer_put_llm_response_returns_hash_and_indexes(tmp_path: Path) -> None:
    store = RawStore(tmp_path / "rs")
    log = AuditLog(tmp_path / "audit")
    writer = RawStoreWriter(store, log)
    model = "qwen-plus"
    p_hash = _prompt_hash("fixed prompt")
    par_hash = _params_hash(model, {"temperature": 0, "max_tokens": 16})
    body = canonicalize(
        {
            "model": model,
            "prompt_hash": p_hash,
            "params_hash": par_hash,
            "response": {"text": "hello", "input_tokens": 1, "output_tokens": 2},
        }
    )
    try:
        bytes_hash = writer.put_llm_response(
            body=body,
            model_id=model,
            prompt_hash=p_hash,
            params_hash=par_hash,
            fetch_time=BASE_T,
        )
        reader = store._issue_reader()

        assert bytes_hash == hashlib.sha256(body).hexdigest()
        assert store.get(bytes_hash, reader=reader) == body
        assert (
            store._lookup_llm(
                reader,
                model_id=model,
                prompt_hash=p_hash,
                params_hash=par_hash,
            )
            == bytes_hash
        )
        records = _audit_records(log)
        assert [r["category"] for r in records] == ["LLMWrite"]
        assert records[0]["bytes_hash"] == bytes_hash
    finally:
        store.close()


def test_llm_cache_lookup_hit_still_requires_admissible_bytes(stack) -> None:
    store, _, access = stack
    model = "qwen-plus"
    p_hash = _prompt_hash("future prompt")
    par_hash = _params_hash(model, {"temperature": 0})
    future = BASE_T + timedelta(hours=1)
    body = canonicalize(
        {
            "model": model,
            "prompt_hash": p_hash,
            "params_hash": par_hash,
            "response": {"text": "hello", "input_tokens": 1, "output_tokens": 1},
        }
    )
    bytes_hash = store.put(body, Provenance(f"llm:{model}", future, future))
    reader = store._issue_reader()
    store._insert_llm_cache(
        reader,
        model_id=model,
        prompt_hash=p_hash,
        params_hash=par_hash,
        bytes_hash=bytes_hash,
    )

    assert access.lookup_llm(model, p_hash, par_hash, BASE_T) == bytes_hash
    with pytest.raises(TemporalAdmissibilityError):
        access.get(bytes_hash, BASE_T)


def test_llm_cache_schema_is_created_on_reopen(tmp_path: Path) -> None:
    root = tmp_path / "rs"
    store = RawStore(root)
    store.put(b"preexisting", _prov())
    store.close()
    with sqlite3.connect(root / "index.sqlite") as conn:
        conn.execute("DROP TABLE llm_cache")

    store = RawStore(root)
    log = AuditLog(tmp_path / "audit")
    writer = RawStoreWriter(store, log)
    model = "qwen-plus"
    p_hash = _prompt_hash("schema prompt")
    par_hash = _params_hash(model, {"temperature": 0})
    body = canonicalize(
        {
            "model": model,
            "prompt_hash": p_hash,
            "params_hash": par_hash,
            "response": {"text": "hello", "input_tokens": 1, "output_tokens": 1},
        }
    )
    try:
        bytes_hash = writer.put_llm_response(
            body=body,
            model_id=model,
            prompt_hash=p_hash,
            params_hash=par_hash,
            fetch_time=BASE_T,
        )
        reader = store._issue_reader()
        assert (
            store._lookup_llm(
                reader,
                model_id=model,
                prompt_hash=p_hash,
                params_hash=par_hash,
            )
            == bytes_hash
        )
    finally:
        store.close()


@pytest.mark.parametrize(
    "bad_kwargs",
    [
        {"cycle_id": ""},
        {"cycle_id": 123},
        {"max_reads_per_cycle": -1},
        {"max_reads_per_cycle": "100"},
    ],
)
def test_constructor_validation(tmp_path: Path, bad_kwargs):
    store = RawStore(tmp_path / "rs")
    log = AuditLog(tmp_path / "audit")
    kwargs = dict(cycle_id="cycle-1", max_reads_per_cycle=10)
    kwargs.update(bad_kwargs)
    try:
        with pytest.raises((ValueError, TypeError)):
            AccessLayer(store, log, **kwargs)
    finally:
        store.close()


# --- temporal admissibility ------------------------------------------------

def test_get_refuses_future_vendor_timestamp(stack):
    store, _, access = stack
    future = BASE_T + timedelta(days=1)
    h = store.put(b"future-data", _prov(vendor=future))
    with pytest.raises(TemporalAdmissibilityError):
        access.get(h, query_time=BASE_T)


def test_get_serves_when_any_vendor_observation_is_admissible(stack):
    """Same bytes, vendor-A saw it early, vendor-B saw it late. A query at
    time t between the two observations should still serve — someone saw it
    before t, so returning the bytes does not constitute a peek."""
    store, _, access = stack
    early = BASE_T - timedelta(hours=1)
    late = BASE_T + timedelta(hours=1)
    h = store.put(b"multi-witness", _prov(source="vendor-A", vendor=early))
    store.put(b"multi-witness", _prov(source="vendor-B", vendor=late))
    assert access.get(h, query_time=BASE_T) == b"multi-witness"


def test_provenance_filters_future_triples(stack):
    store, _, access = stack
    early = BASE_T - timedelta(hours=1)
    late = BASE_T + timedelta(hours=1)
    h = store.put(b"x", _prov(source="vendor-A", vendor=early))
    store.put(b"x", _prov(source="vendor-B", vendor=late))
    visible = access.provenance(h, query_time=BASE_T)
    assert [p.source_id for p in visible] == ["vendor-A"]


def test_provenance_unknown_hash_returns_empty(stack):
    """Unknown-hash and not-yet-visible look identical to the caller —
    this is deliberate: polling cannot differentiate them."""
    _, _, access = stack
    assert access.provenance("0" * 64, query_time=BASE_T) == []


def test_corrections_filters_future_corrections(stack):
    store, _, access = stack
    past = BASE_T - timedelta(hours=1)
    future = BASE_T + timedelta(hours=1)
    h_orig = store.put(b"v0", _prov(vendor=past))
    h_past = store.put(b"v1", _prov(vendor=past), corrects=h_orig)
    h_future = store.put(b"v2", _prov(vendor=future), corrects=h_orig)
    visible = access.corrections(h_orig, query_time=BASE_T)
    assert visible == [h_past]
    assert h_future not in visible


def test_get_unknown_hash_raises_keyerror(stack):
    _, _, access = stack
    with pytest.raises(KeyError):
        access.get("0" * 64, query_time=BASE_T)


def test_naive_query_time_rejected(stack):
    store, _, access = stack
    h = store.put(b"x", _prov())
    naive = datetime(2026, 4, 22, 12, 0, 0)
    with pytest.raises(ValueError):
        access.get(h, query_time=naive)


@given(
    vendor_delta_hours=st.integers(min_value=-48, max_value=48),
    query_delta_hours=st.integers(min_value=-48, max_value=48),
)
@settings(max_examples=40, deadline=None)
def test_get_admission_iff_query_geq_earliest(
    tmp_path_factory: pytest.TempPathFactory,
    vendor_delta_hours: int,
    query_delta_hours: int,
) -> None:
    """Property (phase completion criterion): access.get admits iff
    query_time ≥ earliest vendor_timestamp."""
    root = tmp_path_factory.mktemp("access_prop")
    store = RawStore(root / "rs")
    log = AuditLog(root / "audit")
    access = AccessLayer(
        store, log, cycle_id="cycle-prop", max_reads_per_cycle=10_000
    )
    try:
        vendor_ts = BASE_T + timedelta(hours=vendor_delta_hours)
        query_ts = BASE_T + timedelta(hours=query_delta_hours)
        h = store.put(b"data", _prov(vendor=vendor_ts))
        should_admit = query_ts >= vendor_ts
        if should_admit:
            assert access.get(h, query_time=query_ts) == b"data"
        else:
            with pytest.raises(TemporalAdmissibilityError):
                access.get(h, query_time=query_ts)
    finally:
        store.close()


# --- rate limit ------------------------------------------------------------

def test_rate_limit_exhausts(tmp_path: Path):
    store = RawStore(tmp_path / "rs")
    log = AuditLog(tmp_path / "audit")
    access = AccessLayer(store, log, cycle_id="c1", max_reads_per_cycle=2)
    try:
        h = store.put(b"x", _prov())
        assert access.get(h, BASE_T) == b"x"
        assert access.get(h, BASE_T) == b"x"
        assert access.reads_remaining == 0
        with pytest.raises(RateLimitExceeded):
            access.get(h, BASE_T)
    finally:
        store.close()


def test_begin_cycle_resets_counter(tmp_path: Path):
    store = RawStore(tmp_path / "rs")
    log = AuditLog(tmp_path / "audit")
    access = AccessLayer(store, log, cycle_id="c1", max_reads_per_cycle=1)
    try:
        h = store.put(b"x", _prov())
        access.get(h, BASE_T)
        with pytest.raises(RateLimitExceeded):
            access.get(h, BASE_T)
        access.begin_cycle("c2")
        assert access.cycle_id == "c2"
        assert access.reads_used == 0
        assert access.get(h, BASE_T) == b"x"
    finally:
        store.close()


def test_rate_limit_counts_all_read_kinds(tmp_path: Path):
    store = RawStore(tmp_path / "rs")
    log = AuditLog(tmp_path / "audit")
    access = AccessLayer(store, log, cycle_id="c1", max_reads_per_cycle=3)
    try:
        h = store.put(b"x", _prov())
        access.get(h, BASE_T)
        access.provenance(h, BASE_T)
        access.corrections(h, BASE_T)
        assert access.reads_remaining == 0
        with pytest.raises(RateLimitExceeded):
            access.provenance(h, BASE_T)
    finally:
        store.close()


def test_llm_cache_lookup_counts_budget_and_audits_hit_and_miss(stack):
    store, log, access = stack
    model = "qwen-plus"
    p_hash = "a" * 64
    par_hash = "b" * 64
    body = canonicalize(
        {
            "model": model,
            "prompt_hash": p_hash,
            "params_hash": par_hash,
            "response": {"text": "ok", "input_tokens": 1, "output_tokens": 1},
        }
    )
    bytes_hash = store.put(body, _prov(source=f"llm:{model}"))
    reader = store._issue_reader()
    store._insert_llm_cache(
        reader,
        model_id=model,
        prompt_hash=p_hash,
        params_hash=par_hash,
        bytes_hash=bytes_hash,
    )

    assert access.lookup_llm(model, p_hash, par_hash, BASE_T) == bytes_hash
    assert access.lookup_llm(model, "c" * 64, par_hash, BASE_T) is None
    assert access.reads_used == 2
    records = [r for r in _audit_records(log) if r["kind"] == "llm_cache"]
    assert [r["outcome"] for r in records] == ["hit", "miss"]


def test_llm_cache_lookup_can_hit_before_temporal_read_is_admissible(stack):
    store, _, access = stack
    model = "qwen-plus"
    p_hash = "d" * 64
    par_hash = "e" * 64
    future = BASE_T + timedelta(hours=1)
    body = canonicalize(
        {
            "model": model,
            "prompt_hash": p_hash,
            "params_hash": par_hash,
            "response": {"text": "future", "input_tokens": 1, "output_tokens": 1},
        }
    )
    bytes_hash = store.put(body, _prov(source=f"llm:{model}", fetch=future, vendor=future))
    reader = store._issue_reader()
    store._insert_llm_cache(
        reader,
        model_id=model,
        prompt_hash=p_hash,
        params_hash=par_hash,
        bytes_hash=bytes_hash,
    )

    assert access.lookup_llm(model, p_hash, par_hash, BASE_T) == bytes_hash
    with pytest.raises(TemporalAdmissibilityError):
        access.get(bytes_hash, BASE_T)


def test_failed_reads_do_not_advance_counter(tmp_path: Path):
    """KeyError / TemporalAdmissibilityError must not consume read budget —
    otherwise an adversary could drain the budget with a stream of misses."""
    store = RawStore(tmp_path / "rs")
    log = AuditLog(tmp_path / "audit")
    access = AccessLayer(store, log, cycle_id="c1", max_reads_per_cycle=2)
    try:
        future = BASE_T + timedelta(days=1)
        h = store.put(b"x", _prov(vendor=future))
        with pytest.raises(TemporalAdmissibilityError):
            access.get(h, BASE_T)
        with pytest.raises(KeyError):
            access.get("0" * 64, BASE_T)
        assert access.reads_used == 0
    finally:
        store.close()


# --- window reservations ---------------------------------------------------

def test_window_reservations_use_pattern_id_and_block_replication_overlap(
    tmp_path: Path,
) -> None:
    store = RawStore(tmp_path / "rs")
    log = AuditLog(tmp_path / "audit")
    reservations = WindowReservationBook(tmp_path / "reservations")
    access = AccessLayer(
        store,
        log,
        cycle_id="c1",
        max_reads_per_cycle=10,
        reservation_book=reservations,
    )
    pattern_id = "a" * 64
    try:
        reservation = access.reserve_window(
            pattern_id=pattern_id,
            stage="Discover",
            t0=BASE_T,
            t1=BASE_T + timedelta(hours=1),
        )

        assert reservation.pattern_id == pattern_id
        assert reservation.as_dict()["pattern_id"] == pattern_id
        with pytest.raises(WindowReservationError, match="EmpiricalTest window overlaps"):
            access.assert_window_available(
                pattern_id=pattern_id,
                stage="EmpiricalTest",
                t0=BASE_T + timedelta(minutes=30),
                t1=BASE_T + timedelta(hours=2),
            )
        access.assert_window_available(
            pattern_id=pattern_id,
            stage="EmpiricalTest",
            t0=BASE_T + timedelta(hours=2),
            t1=BASE_T + timedelta(hours=3),
        )

        records = [r for r in _audit_records(log) if r["kind"].startswith("window_")]
        assert records[0]["envelope"] == {"cycle_id": "c1", "pattern_id": pattern_id}
        assert records[1]["outcome"] == "refused"
        assert records[2]["outcome"] == "available"
    finally:
        reservations.close()
        store.close()


# --- audit logging ---------------------------------------------------------

def test_every_read_appends_audit_record(stack):
    store, log, access = stack
    h = store.put(b"x", _prov())
    access.get(h, BASE_T)
    access.provenance(h, BASE_T)
    access.corrections(h, BASE_T)
    records = _audit_records(log)
    assert len(records) == 3
    kinds = [r["kind"] for r in records]
    assert kinds == ["bytes", "provenance", "corrections"]
    for r in records:
        assert r["category"] == "Access"
        assert r["stage"] == "access"
        assert r["envelope"] == {"cycle_id": "cycle-1"}
        assert r["hash"] == h
        assert r["outcome"] == "ok"
        # timestamp and record_hash are injected by the audit log
        assert "record_hash" in r and "prev_hash" in r


def test_audit_records_the_cycle_id(tmp_path: Path):
    store = RawStore(tmp_path / "rs")
    log = AuditLog(tmp_path / "audit")
    access = AccessLayer(store, log, cycle_id="c1", max_reads_per_cycle=10)
    try:
        h = store.put(b"x", _prov())
        access.get(h, BASE_T)
        access.begin_cycle("c2")
        access.get(h, BASE_T)
        records = _audit_records(log)
        cycles = [r["envelope"]["cycle_id"] for r in records]
        assert cycles == ["c1", "c2"]
    finally:
        store.close()


def test_future_denied_read_is_still_audited(stack):
    store, log, access = stack
    future = BASE_T + timedelta(days=1)
    h = store.put(b"x", _prov(vendor=future))
    with pytest.raises(TemporalAdmissibilityError):
        access.get(h, BASE_T)
    records = _audit_records(log)
    assert len(records) == 1
    assert records[0]["outcome"] == "future_denied"
    # earliest_vendor_timestamp round-trips as ISO string
    assert records[0]["earliest_vendor_timestamp"] == future.isoformat()


def test_rate_limited_read_is_still_audited(tmp_path: Path):
    store = RawStore(tmp_path / "rs")
    log = AuditLog(tmp_path / "audit")
    access = AccessLayer(store, log, cycle_id="c1", max_reads_per_cycle=1)
    try:
        h = store.put(b"x", _prov())
        access.get(h, BASE_T)
        with pytest.raises(RateLimitExceeded):
            access.get(h, BASE_T)
        records = _audit_records(log)
        outcomes = [r["outcome"] for r in records]
        assert outcomes == ["ok", "rate_limited"]
    finally:
        store.close()


def test_unknown_hash_read_is_audited(stack):
    _, log, access = stack
    with pytest.raises(KeyError):
        access.get("0" * 64, BASE_T)
    records = _audit_records(log)
    assert len(records) == 1
    assert records[0]["outcome"] == "unknown"


def test_audit_chain_verifies_after_access_reads(stack):
    store, log, access = stack
    h = store.put(b"x", _prov())
    for _ in range(5):
        access.get(h, BASE_T)
    day = sorted(log._root.glob("*.jsonl"))[0].stem
    # verify_chain takes a date
    from datetime import date as _date
    d = _date.fromisoformat(day)
    assert log.verify_chain(d) is True
