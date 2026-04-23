from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from hypothesis import given, settings, strategies as st

from access import (
    AccessLayer,
    RateLimitExceeded,
    TemporalAdmissibilityError,
)
from audit import AuditLog
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
    """Property (phase-exit criterion): access.get admits iff
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
