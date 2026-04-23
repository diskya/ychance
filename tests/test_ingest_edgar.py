from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from audit import AuditLog
from ingest.edgar import (
    DEFAULT_USER_AGENT,
    EDGAR_PARSE_AND_HASH_COMPUTE_USD,
    EDGAR_SOURCE_ID,
    HTTPRequest,
    HTTPResponse,
    EdgarHTTPStatusError,
    EdgarIngestInput,
    EdgarIngestOutput,
    EdgarIngestStage,
)
from pipeline import ArtifactStore, InvariantViolation
from rawstore import RawStore


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "edgar_submissions_sample.json"
LAST_MODIFIED = "Wed, 23 Apr 2026 11:59:00 GMT"
FETCH_TIME = datetime(2026, 4, 23, 12, 0, 0, tzinfo=timezone.utc)


class ScriptedHTTPClient:
    def __init__(self, scripted: list[HTTPResponse | Exception]) -> None:
        self._scripted = list(scripted)
        self.calls: list[HTTPRequest] = []

    def fetch(self, request: HTTPRequest) -> HTTPResponse:
        self.calls.append(request)
        if not self._scripted:
            raise AssertionError("unexpected extra HTTP call")
        item = self._scripted.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class ScriptedClock:
    def __init__(self, timestamps: list[datetime]) -> None:
        self._timestamps = list(timestamps)

    def __call__(self) -> datetime:
        if not self._timestamps:
            raise AssertionError("unexpected extra clock read")
        return self._timestamps.pop(0)


@pytest.fixture
def fixture_bytes() -> bytes:
    return FIXTURE_PATH.read_bytes()


@pytest.fixture
def audit(tmp_path: Path) -> AuditLog:
    return AuditLog(tmp_path / "audit")


@pytest.fixture
def rawstore(tmp_path: Path):
    store = RawStore(tmp_path / "rawstore")
    try:
        yield store
    finally:
        store.close()


@pytest.fixture
def artifacts(tmp_path: Path):
    store = ArtifactStore(tmp_path / "artifacts")
    try:
        yield store
    finally:
        store.close()


def _audit_records(log: AuditLog) -> list[dict]:
    records: list[dict] = []
    for path in sorted(log._root.glob("*.jsonl")):
        for line in path.read_text().splitlines():
            if line:
                records.append(json.loads(line))
    return records


def _reader(store: RawStore) -> object:
    return store._issue_reader()


def _response(
    body: bytes,
    *,
    status: int = 200,
    headers: dict[str, str] | None = None,
) -> HTTPResponse:
    return HTTPResponse(status=status, headers=dict(headers or {}), body=body)


def _variant_body(
    base_body: bytes,
    *,
    cik: str,
    name: str,
    filing_date: str,
) -> bytes:
    payload = json.loads(base_body.decode("utf-8"))
    payload["cik"] = cik
    payload["name"] = name
    payload["filings"]["recent"]["filingDate"][0] = filing_date
    return json.dumps(payload, indent=2).encode("utf-8")


def _raw_blob_count(store: RawStore) -> int:
    return sum(1 for path in store._bytes_root.rglob("*") if path.is_file())


def test_fixture_replay_writes_rawstore_and_full_ingest_audit_record(
    rawstore: RawStore,
    artifacts: ArtifactStore,
    audit: AuditLog,
    fixture_bytes: bytes,
) -> None:
    client = ScriptedHTTPClient(
        [_response(fixture_bytes, headers={"Last-Modified": LAST_MODIFIED})]
    )
    stage = EdgarIngestStage(
        rawstore=rawstore,
        artifacts=artifacts,
        audit=audit,
        http_client=client,
        user_agent="ychance-test/0.1 test@example.com",
        now=lambda: FETCH_TIME,
        sleep=lambda seconds: None,
    )

    result = stage.run(EdgarIngestInput(cik="0000320193"), envelope={"cycle_id": "c1"})

    expected_hash = hashlib.sha256(fixture_bytes).hexdigest()
    assert result.outputs.bytes_hash == expected_hash
    assert result.outputs.bytes_size == len(fixture_bytes)
    assert result.cost_used.data_reads == 1
    assert result.cost_used.compute_usd == pytest.approx(EDGAR_PARSE_AND_HASH_COMPUTE_USD)
    assert client.calls[0].headers["User-Agent"] == "ychance-test/0.1 test@example.com"
    assert client.calls[0].url == "https://data.sec.gov/submissions/CIK0000320193.json"

    reader = _reader(rawstore)
    assert rawstore.get(expected_hash, reader=reader) == fixture_bytes
    provenance = rawstore.provenance(expected_hash, reader=reader)
    assert provenance == [
        (
            EDGAR_SOURCE_ID,
            FETCH_TIME,
            datetime(2026, 4, 23, 11, 59, 0, tzinfo=timezone.utc),
        )
    ]

    records = _audit_records(audit)
    assert len(records) == 1
    record = records[0]
    assert record["category"] == "Ingest"
    assert record["stage"] == "Ingest"
    assert record["source_id"] == EDGAR_SOURCE_ID
    assert record["vendor_timestamp"] == "2026-04-23T11:59:00+00:00"
    assert record["fetch_time"] == FETCH_TIME.isoformat()
    assert record["bytes_hash"] == expected_hash
    assert record["bytes_size"] == len(fixture_bytes)
    assert record["provenance"] == [
        EDGAR_SOURCE_ID,
        FETCH_TIME.isoformat(),
        "2026-04-23T11:59:00+00:00",
    ]


def test_stage_cache_hit_avoids_second_http_call_and_audit_record(
    rawstore: RawStore,
    artifacts: ArtifactStore,
    audit: AuditLog,
    fixture_bytes: bytes,
) -> None:
    client = ScriptedHTTPClient(
        [_response(fixture_bytes, headers={"Last-Modified": LAST_MODIFIED})]
    )
    stage = EdgarIngestStage(
        rawstore=rawstore,
        artifacts=artifacts,
        audit=audit,
        http_client=client,
        now=lambda: FETCH_TIME,
        sleep=lambda seconds: None,
    )

    first = stage.run(EdgarIngestInput(cik="0000320193"))
    second = stage.run(EdgarIngestInput(cik="0000320193"))

    assert first.cache_hit is False
    assert second.cache_hit is True
    assert len(client.calls) == 1
    assert len(_audit_records(audit)) == 1


def test_rawstore_put_dedups_blob_when_same_bytes_are_ingested_twice(
    rawstore: RawStore,
    audit: AuditLog,
    fixture_bytes: bytes,
    tmp_path: Path,
) -> None:
    client_one = ScriptedHTTPClient(
        [_response(fixture_bytes, headers={"Last-Modified": LAST_MODIFIED})]
    )
    client_two = ScriptedHTTPClient(
        [_response(fixture_bytes, headers={"Last-Modified": LAST_MODIFIED})]
    )
    artifacts_one = ArtifactStore(tmp_path / "artifacts-one")
    artifacts_two = ArtifactStore(tmp_path / "artifacts-two")
    try:
        stage_one = EdgarIngestStage(
            rawstore=rawstore,
            artifacts=artifacts_one,
            audit=audit,
            http_client=client_one,
            now=lambda: FETCH_TIME,
            sleep=lambda seconds: None,
        )
        stage_two = EdgarIngestStage(
            rawstore=rawstore,
            artifacts=artifacts_two,
            audit=audit,
            http_client=client_two,
            now=lambda: FETCH_TIME,
            sleep=lambda seconds: None,
        )

        stage_one.run(EdgarIngestInput(cik="0000320193"))
        stage_two.run(EdgarIngestInput(cik="0000320193"))

        assert _raw_blob_count(rawstore) == 1
    finally:
        artifacts_one.close()
        artifacts_two.close()


def test_different_ciks_produce_distinct_hashes_and_provenance_rows(
    rawstore: RawStore,
    artifacts: ArtifactStore,
    audit: AuditLog,
    fixture_bytes: bytes,
) -> None:
    other_body = _variant_body(
        fixture_bytes,
        cik="0000789019",
        name="MICROSOFT CORP",
        filing_date="2026-04-18",
    )
    client = ScriptedHTTPClient(
        [
            _response(fixture_bytes, headers={"Last-Modified": LAST_MODIFIED}),
            _response(other_body),
        ]
    )
    stage = EdgarIngestStage(
        rawstore=rawstore,
        artifacts=artifacts,
        audit=audit,
        http_client=client,
        now=ScriptedClock(
            [
                FETCH_TIME,
                datetime(2026, 4, 23, 12, 1, 0, tzinfo=timezone.utc),
            ]
        ),
        sleep=lambda seconds: None,
    )

    first = stage.run(EdgarIngestInput(cik="0000320193"))
    second = stage.run(EdgarIngestInput(cik="0000789019"))

    assert first.outputs.bytes_hash != second.outputs.bytes_hash
    reader = _reader(rawstore)
    first_provenance = rawstore.provenance(first.outputs.bytes_hash, reader=reader)
    second_provenance = rawstore.provenance(second.outputs.bytes_hash, reader=reader)
    assert len(first_provenance) == 1
    assert len(second_provenance) == 1
    assert first_provenance != second_provenance


def test_falls_back_to_recent_filing_date_when_last_modified_missing(
    rawstore: RawStore,
    artifacts: ArtifactStore,
    audit: AuditLog,
    fixture_bytes: bytes,
) -> None:
    client = ScriptedHTTPClient([_response(fixture_bytes)])
    stage = EdgarIngestStage(
        rawstore=rawstore,
        artifacts=artifacts,
        audit=audit,
        http_client=client,
        now=lambda: FETCH_TIME,
        sleep=lambda seconds: None,
    )

    result = stage.run(EdgarIngestInput(cik="0000320193"))

    assert result.outputs.vendor_timestamp == "2026-04-20T00:00:00+00:00"
    reader = _reader(rawstore)
    provenance = rawstore.provenance(result.outputs.bytes_hash, reader=reader)
    assert provenance[0].vendor_timestamp == datetime(
        2026, 4, 20, 0, 0, 0, tzinfo=timezone.utc
    )


def test_missing_vendor_timestamp_raises(
    rawstore: RawStore,
    artifacts: ArtifactStore,
    audit: AuditLog,
) -> None:
    body = json.dumps({"filings": {"recent": {"filingDate": []}}}).encode("utf-8")
    client = ScriptedHTTPClient([_response(body)])
    stage = EdgarIngestStage(
        rawstore=rawstore,
        artifacts=artifacts,
        audit=audit,
        http_client=client,
        now=lambda: FETCH_TIME,
        sleep=lambda seconds: None,
    )

    with pytest.raises(RuntimeError, match="vendor timestamp unavailable"):
        stage.run(EdgarIngestInput(cik="0000320193"))
    assert _audit_records(audit) == []
    assert _raw_blob_count(rawstore) == 0


def test_retries_on_transient_failure_and_charges_cost(
    rawstore: RawStore,
    artifacts: ArtifactStore,
    audit: AuditLog,
    fixture_bytes: bytes,
) -> None:
    sleeps: list[float] = []
    client = ScriptedHTTPClient(
        [
            EdgarHTTPStatusError(503, "temporary outage"),
            EdgarHTTPStatusError(429, "slow down"),
            _response(fixture_bytes, headers={"Last-Modified": LAST_MODIFIED}),
        ]
    )
    stage = EdgarIngestStage(
        rawstore=rawstore,
        artifacts=artifacts,
        audit=audit,
        http_client=client,
        now=lambda: FETCH_TIME,
        sleep=sleeps.append,
    )

    result = stage.run(EdgarIngestInput(cik="0000320193"))

    assert result.outputs.bytes_hash == hashlib.sha256(fixture_bytes).hexdigest()
    assert result.cost_used.data_reads == 3
    assert result.cost_used.compute_usd == pytest.approx(EDGAR_PARSE_AND_HASH_COMPUTE_USD)
    assert len(client.calls) == 3
    assert len(sleeps) == 2
    assert all(delay > 0 for delay in sleeps)


def test_non_retryable_4xx_is_not_retried(
    rawstore: RawStore,
    artifacts: ArtifactStore,
    audit: AuditLog,
) -> None:
    client = ScriptedHTTPClient([EdgarHTTPStatusError(404, "not found")])
    stage = EdgarIngestStage(
        rawstore=rawstore,
        artifacts=artifacts,
        audit=audit,
        http_client=client,
        now=lambda: FETCH_TIME,
        sleep=lambda seconds: None,
    )

    with pytest.raises(EdgarHTTPStatusError, match="HTTP 404"):
        stage.run(EdgarIngestInput(cik="0000320193"))
    assert len(client.calls) == 1
    assert _audit_records(audit) == []


def test_invariant_rejects_vendor_timestamp_after_fetch_time(
    rawstore: RawStore,
    artifacts: ArtifactStore,
    audit: AuditLog,
    fixture_bytes: bytes,
) -> None:
    client = ScriptedHTTPClient(
        [_response(fixture_bytes, headers={"Last-Modified": LAST_MODIFIED})]
    )
    stage = EdgarIngestStage(
        rawstore=rawstore,
        artifacts=artifacts,
        audit=audit,
        http_client=client,
        now=lambda: FETCH_TIME,
        sleep=lambda seconds: None,
    )
    stage.run(EdgarIngestInput(cik="0000320193"))
    bytes_hash = hashlib.sha256(fixture_bytes).hexdigest()

    with pytest.raises(InvariantViolation, match="vendor_timestamp"):
        stage.invariant(
            EdgarIngestInput(cik="0000320193"),
            EdgarIngestOutput(
                cik="0000320193",
                url="https://data.sec.gov/submissions/CIK0000320193.json",
                source_id=EDGAR_SOURCE_ID,
                vendor_timestamp="2026-04-23T12:01:00+00:00",
                fetch_time="2026-04-23T12:00:00+00:00",
                bytes_hash=bytes_hash,
                bytes_size=len(fixture_bytes),
                provenance=(
                    EDGAR_SOURCE_ID,
                    "2026-04-23T12:00:00+00:00",
                    "2026-04-23T12:01:00+00:00",
                ),
            ),
        )


def test_default_user_agent_is_non_empty() -> None:
    assert DEFAULT_USER_AGENT
