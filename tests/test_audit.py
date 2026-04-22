from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from hypothesis import given, settings, strategies as st

from audit import AuditLog, GENESIS_HASH, canonicalize, record_digest


BASE_T = datetime(2026, 4, 22, 10, 0, 0, tzinfo=timezone.utc)


def _rec(
    payload: dict | None = None,
    *,
    category: str = "Ingest",
    stage: str = "ingest",
    envelope: dict | None = None,
    timestamp: datetime | None = None,
) -> dict:
    out: dict = {
        "category": category,
        "stage": stage,
        "envelope": {} if envelope is None else envelope,
    }
    if timestamp is not None:
        out["timestamp"] = timestamp
    if payload:
        out.update(payload)
    return out


@pytest.fixture
def log(tmp_path: Path):
    return AuditLog(tmp_path / "audit")


# --- canonicalization + digest ---------------------------------------------

def test_canonicalize_is_sorted_and_compact():
    a = {"b": 2, "a": 1, "c": [3, 2, 1]}
    b = {"a": 1, "c": [3, 2, 1], "b": 2}
    assert canonicalize(a) == canonicalize(b)
    assert canonicalize(a) == b'{"a":1,"b":2,"c":[3,2,1]}'


def test_record_digest_rejects_hash_field():
    with pytest.raises(ValueError):
        record_digest({"record_hash": "x"})


def test_canonicalize_rejects_nan():
    with pytest.raises(ValueError):
        canonicalize({"x": float("nan")})


# --- append: common-field validation ---------------------------------------

def test_append_returns_matching_hash(log: AuditLog):
    h = log.append(_rec({"bytes_hash": "a" * 64}))
    # Read back, strip record_hash, recompute.
    day = BASE_T.date()  # may not match: record uses now(). Walk the dir.
    day_files = list((log._root).glob("*.jsonl"))
    assert len(day_files) == 1
    line = day_files[0].read_text().splitlines()[0]
    rec = json.loads(line)
    assert rec["record_hash"] == h
    check = {k: v for k, v in rec.items() if k != "record_hash"}
    assert record_digest(check) == h


def test_append_injects_uuid_record_id_and_timestamp(log: AuditLog):
    log.append(_rec())
    line = next(iter(log._root.glob("*.jsonl"))).read_text().splitlines()[0]
    rec = json.loads(line)
    # UUID4 parse must succeed.
    uuid.UUID(rec["record_id"])
    # Timestamp parses as tz-aware.
    dt = datetime.fromisoformat(rec["timestamp"])
    assert dt.tzinfo is not None


@pytest.mark.parametrize("missing", ["category", "stage", "envelope"])
def test_append_requires_common_fields(log: AuditLog, missing: str):
    record = _rec()
    del record[missing]
    with pytest.raises(ValueError):
        log.append(record)


def test_append_rejects_bad_envelope_keys(log: AuditLog):
    with pytest.raises(ValueError):
        log.append(_rec(envelope={"not_a_real_key": "x"}))


def test_append_rejects_caller_supplied_hash_fields(log: AuditLog):
    with pytest.raises(ValueError):
        log.append({**_rec(), "record_hash": "x"})
    with pytest.raises(ValueError):
        log.append({**_rec(), "prev_hash": "x"})


def test_append_rejects_naive_timestamp(log: AuditLog):
    naive = datetime(2026, 4, 22, 10, 0, 0)
    with pytest.raises(ValueError):
        log.append(_rec(timestamp=naive))


def test_append_enforces_monotonic_timestamp(log: AuditLog):
    log.append(_rec(timestamp=BASE_T))
    with pytest.raises(ValueError):
        log.append(_rec(timestamp=BASE_T - timedelta(seconds=1)))


# --- chain + verification --------------------------------------------------

def test_single_day_chain_links_and_verifies(log: AuditLog):
    h0 = log.append(_rec({"n": 0}, timestamp=BASE_T))
    h1 = log.append(_rec({"n": 1}, timestamp=BASE_T + timedelta(seconds=1)))
    h2 = log.append(_rec({"n": 2}, timestamp=BASE_T + timedelta(seconds=2)))
    lines = (log._root / f"{BASE_T.date().isoformat()}.jsonl").read_text().splitlines()
    recs = [json.loads(l) for l in lines]
    assert [r["record_hash"] for r in recs] == [h0, h1, h2]
    assert recs[0]["prev_hash"] == GENESIS_HASH
    assert recs[1]["prev_hash"] == h0
    assert recs[2]["prev_hash"] == h1
    assert log.verify_chain(BASE_T.date()) is True


def test_verify_chain_missing_day_is_vacuously_true(log: AuditLog):
    # No records written.
    assert log.verify_chain(BASE_T.date()) is True


def test_cross_day_rotation_and_continuity(log: AuditLog):
    d0 = BASE_T
    d1 = BASE_T + timedelta(days=1)
    d2 = BASE_T + timedelta(days=2)

    h0 = log.append(_rec({"n": 0}, timestamp=d0))
    h1 = log.append(_rec({"n": 1}, timestamp=d1))
    h2 = log.append(_rec({"n": 2}, timestamp=d2))

    # Three distinct files.
    files = sorted(p.name for p in log._root.glob("*.jsonl"))
    assert files == [
        f"{d0.date().isoformat()}.jsonl",
        f"{d1.date().isoformat()}.jsonl",
        f"{d2.date().isoformat()}.jsonl",
    ]

    # Per-day chains verify.
    for d in (d0.date(), d1.date(), d2.date()):
        assert log.verify_chain(d) is True

    # First record of each later day references the previous day's tail.
    rec1 = json.loads((log._root / files[1]).read_text().splitlines()[0])
    rec2 = json.loads((log._root / files[2]).read_text().splitlines()[0])
    assert rec1["prev_hash"] == h0
    assert rec2["prev_hash"] == h1
    assert rec2["record_hash"] == h2

    assert log.verify_cross_day((d0.date(), d2.date())) is True


def test_cross_day_range_with_gap(log: AuditLog):
    d0 = BASE_T
    d_skip = BASE_T + timedelta(days=1)  # no records
    d2 = BASE_T + timedelta(days=2)
    log.append(_rec({"n": 0}, timestamp=d0))
    log.append(_rec({"n": 2}, timestamp=d2))
    # Gap day has no file; cross-day should still verify.
    assert log.verify_cross_day((d0.date(), d2.date())) is True
    assert not (log._root / f"{d_skip.date().isoformat()}.jsonl").exists()


def test_persists_across_reopen(tmp_path: Path):
    root = tmp_path / "audit"
    a = AuditLog(root)
    h0 = a.append(_rec({"n": 0}, timestamp=BASE_T))

    b = AuditLog(root)  # reopen: state recovered from disk
    h1 = b.append(_rec({"n": 1}, timestamp=BASE_T + timedelta(seconds=1)))
    line = (root / f"{BASE_T.date().isoformat()}.jsonl").read_text().splitlines()[1]
    assert json.loads(line)["prev_hash"] == h0
    assert json.loads(line)["record_hash"] == h1
    assert b.verify_chain(BASE_T.date()) is True


# --- tampering -------------------------------------------------------------

def _rewrite_line(path: Path, index: int, new_line: str) -> None:
    lines = path.read_text().splitlines()
    lines[index] = new_line
    path.write_text("\n".join(lines) + "\n")


@given(n=st.integers(min_value=2, max_value=6), tamper_idx=st.integers(min_value=0))
@settings(max_examples=25, deadline=None)
def test_tampering_any_record_breaks_chain(
    tmp_path_factory: pytest.TempPathFactory, n: int, tamper_idx: int
):
    """Per §6.9: mutating any line in a day-file must break verify_chain."""
    tamper_idx = tamper_idx % n
    root = tmp_path_factory.mktemp("audit_tamper")
    a = AuditLog(root)
    for i in range(n):
        a.append(_rec({"i": i}, timestamp=BASE_T + timedelta(seconds=i)))
    day = BASE_T.date()
    assert a.verify_chain(day) is True  # clean baseline

    path = root / f"{day.isoformat()}.jsonl"
    lines = path.read_text().splitlines()
    rec = json.loads(lines[tamper_idx])
    # Mutate a payload field without updating record_hash — this is the
    # definition of tampering.
    rec["i"] = rec["i"] + 10_000
    _rewrite_line(path, tamper_idx, json.dumps(rec, sort_keys=True, separators=(",", ":")))

    fresh = AuditLog(root)  # fresh instance; no in-memory trust
    assert fresh.verify_chain(day) is False


def test_tampering_breaks_chain_from_that_point_forward(tmp_path: Path):
    """Mutating record k makes records <k remain self-consistent while record
    k's stated ``record_hash`` no longer matches its canonical digest. That
    divergence is what verify_chain catches — and once detected, the chain
    cannot recover for any record at k or beyond."""
    root = tmp_path / "audit"
    a = AuditLog(root)
    for i in range(5):
        a.append(_rec({"i": i}, timestamp=BASE_T + timedelta(seconds=i)))
    day = BASE_T.date()
    path = root / f"{day.isoformat()}.jsonl"
    k = 2

    lines = path.read_text().splitlines()
    rec = json.loads(lines[k])
    rec["i"] = 999  # payload tamper; record_hash field left as-is → now lies
    _rewrite_line(path, k, json.dumps(rec, sort_keys=True, separators=(",", ":")))

    lines = path.read_text().splitlines()
    # Records before k remain self-consistent (stated hash matches digest).
    for j in range(k):
        r = json.loads(lines[j])
        check = {kk: vv for kk, vv in r.items() if kk != "record_hash"}
        assert record_digest(check) == r["record_hash"]
    # Record k is the first record where stated hash diverges from digest.
    r_k = json.loads(lines[k])
    check_k = {kk: vv for kk, vv in r_k.items() if kk != "record_hash"}
    assert record_digest(check_k) != r_k["record_hash"]
    # End-to-end: verify_chain sees the break and reports False.
    assert AuditLog(root).verify_chain(day) is False


def test_cross_day_tamper_detected(tmp_path: Path):
    root = tmp_path / "audit"
    a = AuditLog(root)
    d0 = BASE_T
    d1 = BASE_T + timedelta(days=1)
    a.append(_rec({"n": 0}, timestamp=d0))
    a.append(_rec({"n": 1}, timestamp=d1))

    # Tamper with day-0's only record.
    p0 = root / f"{d0.date().isoformat()}.jsonl"
    rec = json.loads(p0.read_text().splitlines()[0])
    rec["n"] = 999
    _rewrite_line(p0, 0, json.dumps(rec, sort_keys=True, separators=(",", ":")))

    fresh = AuditLog(root)
    assert fresh.verify_cross_day((d0.date(), d1.date())) is False


# --- property: round-trip canonical form ----------------------------------

@given(
    payloads=st.lists(
        st.dictionaries(
            keys=st.text(
                alphabet=st.characters(min_codepoint=97, max_codepoint=122),
                min_size=1,
                max_size=6,
            ),
            values=st.one_of(
                st.integers(min_value=-1000, max_value=1000),
                st.text(max_size=20),
                st.booleans(),
                st.none(),
            ),
            max_size=4,
        ),
        min_size=1,
        max_size=6,
    ),
)
@settings(max_examples=20, deadline=None)
def test_append_then_verify_chain_round_trip(
    tmp_path_factory: pytest.TempPathFactory, payloads: list[dict]
):
    root = tmp_path_factory.mktemp("audit_rt")
    a = AuditLog(root)
    for i, p in enumerate(payloads):
        # Strip reserved keys so we don't collide with common fields.
        safe = {k: v for k, v in p.items() if k not in {
            "record_hash", "prev_hash", "record_id", "category", "stage",
            "envelope", "timestamp",
        }}
        a.append(_rec(safe, timestamp=BASE_T + timedelta(seconds=i)))
    assert a.verify_chain(BASE_T.date()) is True
    assert AuditLog(root).verify_chain(BASE_T.date()) is True
