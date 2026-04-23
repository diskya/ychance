"""SEC EDGAR submissions Ingest adapter.

Vendor timestamp resolution is strict and ordered:
1. Use the HTTP ``Last-Modified`` header when present.
2. Otherwise use ``filings.recent.filingDate[0]`` from the JSON body, as
   UTC midnight for that filing date.
3. If neither source is available, fail loudly. The adapter never falls
   back to the local clock for vendor timestamps.

Compute cost is tracked as a fixed conservative constant per successful
response, covering SHA-256 over the raw bytes plus the lightweight JSON
parse needed when ``Last-Modified`` is absent.
"""

from __future__ import annotations

import hashlib
import json
import random
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, time as dt_time, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Protocol

from audit import AuditLog
from pipeline import ArtifactStore, CostCeiling, InvariantViolation, Stage, StageContext
from rawstore import Provenance, RawStore


EDGAR_SOURCE_ID = "SEC_EDGAR_submissions"
DEFAULT_USER_AGENT = "ychance-edgar-ingest/0.0 test@example.com"
EDGAR_PARSE_AND_HASH_COMPUTE_USD = 0.0001
_DEFAULT_MAX_RETRIES = 3
_INITIAL_BACKOFF_SECONDS = 0.2
_MAX_BACKOFF_SECONDS = 2.0


@dataclass(frozen=True)
class EdgarIngestInput:
    cik: str


@dataclass(frozen=True)
class EdgarIngestOutput:
    cik: str
    url: str
    source_id: str
    vendor_timestamp: str
    fetch_time: str
    bytes_hash: str
    bytes_size: int
    provenance: tuple[str, str, str]


@dataclass(frozen=True)
class HTTPRequest:
    method: str
    url: str
    headers: dict[str, str]


@dataclass(frozen=True)
class HTTPResponse:
    status: int
    headers: dict[str, str]
    body: bytes


class EdgarHTTPClient(Protocol):
    def fetch(self, request: HTTPRequest) -> HTTPResponse:
        """Return one HTTP response or raise a transport/status error."""


class EdgarHTTPStatusError(RuntimeError):
    def __init__(
        self,
        status: int,
        message: str,
        headers: Mapping[str, str] | None = None,
        body: bytes = b"",
    ) -> None:
        self.status = status
        self.headers = dict(headers or {})
        self.body = body
        super().__init__(f"HTTP {status}: {message}")


class EdgarNetworkError(RuntimeError):
    """Raised when the HTTP request fails before a response is returned."""


class EdgarVendorTimestampError(RuntimeError):
    """Raised when the vendor timestamp cannot be resolved."""


class UrllibEdgarHTTPClient:
    def fetch(self, request: HTTPRequest) -> HTTPResponse:
        req = urllib.request.Request(
            request.url,
            headers=request.headers,
            method=request.method,
        )
        try:
            with urllib.request.urlopen(req) as response:
                return HTTPResponse(
                    status=response.status,
                    headers=dict(response.headers.items()),
                    body=response.read(),
                )
        except urllib.error.HTTPError as exc:
            body = exc.read()
            raise EdgarHTTPStatusError(
                exc.code,
                exc.reason or "EDGAR request failed",
                headers=dict(exc.headers.items()),
                body=body,
            ) from exc
        except urllib.error.URLError as exc:
            raise EdgarNetworkError(str(exc.reason)) from exc


def _ensure_utc(ts: datetime) -> datetime:
    if not isinstance(ts, datetime):
        raise TypeError("timestamps must be datetime instances")
    if ts.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return ts.astimezone(timezone.utc)


def _normalize_cik(cik: str) -> str:
    if not isinstance(cik, str):
        raise TypeError("cik must be a string")
    digits = cik.strip()
    if not digits.isdigit():
        raise ValueError("cik must contain only digits")
    if len(digits) > 10:
        raise ValueError("cik must be at most 10 digits")
    return digits.zfill(10)


def _edgar_url(cik: str) -> str:
    return f"https://data.sec.gov/submissions/CIK{cik}.json"


def _parse_http_datetime(value: str) -> datetime:
    parsed = parsedate_to_datetime(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class EdgarIngestStage(Stage):
    name = "edgar_submissions_ingest"
    version = "1"
    audit_stage = "Ingest"
    cost_ceiling = CostCeiling(
        compute_usd=0.001,
        data_reads=_DEFAULT_MAX_RETRIES + 1,
    )
    InputType = EdgarIngestInput
    OutputType = EdgarIngestOutput

    def __init__(
        self,
        *,
        rawstore: RawStore,
        artifacts: ArtifactStore,
        audit: AuditLog,
        http_client: EdgarHTTPClient | None = None,
        user_agent: str = DEFAULT_USER_AGENT,
        now: Callable[[], datetime] | None = None,
        sleep: Callable[[float], None] | None = None,
        rng: random.Random | None = None,
        max_retries: int = _DEFAULT_MAX_RETRIES,
    ) -> None:
        if not isinstance(rawstore, RawStore):
            raise TypeError("rawstore must be a RawStore")
        if not isinstance(user_agent, str) or not user_agent.strip():
            raise ValueError("user_agent must be a non-empty string")
        if not isinstance(max_retries, int) or max_retries < 0:
            raise ValueError("max_retries must be a non-negative int")
        super().__init__(artifacts=artifacts, audit=audit)
        self._rawstore = rawstore
        self._rawstore_reader = rawstore._issue_reader()
        self._http_client = http_client or UrllibEdgarHTTPClient()
        self._user_agent = user_agent.strip()
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._sleep = sleep or time.sleep
        self._rng = rng or random.Random()
        self._max_retries = max_retries

    def compute(self, inputs: EdgarIngestInput, ctx: StageContext) -> EdgarIngestOutput:
        cik = _normalize_cik(inputs.cik)
        url = _edgar_url(cik)
        request = HTTPRequest(
            method="GET",
            url=url,
            headers={
                "Accept": "application/json",
                "User-Agent": self._user_agent,
            },
        )
        response = self._fetch_with_retry(request, ctx)
        fetch_time = _ensure_utc(self._now())
        vendor_timestamp = self._resolve_vendor_timestamp(response)
        body = bytes(response.body)
        bytes_hash = hashlib.sha256(body).hexdigest()
        ctx.charge_compute(EDGAR_PARSE_AND_HASH_COMPUTE_USD)
        stored_hash = self._rawstore.put(
            body,
            Provenance(EDGAR_SOURCE_ID, fetch_time, vendor_timestamp),
        )
        if stored_hash != bytes_hash:
            raise RuntimeError("rawstore returned an unexpected content hash")
        return EdgarIngestOutput(
            cik=cik,
            url=url,
            source_id=EDGAR_SOURCE_ID,
            vendor_timestamp=vendor_timestamp.isoformat(),
            fetch_time=fetch_time.isoformat(),
            bytes_hash=bytes_hash,
            bytes_size=len(body),
            provenance=(
                EDGAR_SOURCE_ID,
                fetch_time.isoformat(),
                vendor_timestamp.isoformat(),
            ),
        )

    def invariant(self, inputs: EdgarIngestInput, outputs: EdgarIngestOutput) -> None:
        fetch_time = _ensure_utc(datetime.fromisoformat(outputs.fetch_time))
        vendor_timestamp = _ensure_utc(datetime.fromisoformat(outputs.vendor_timestamp))
        if outputs.bytes_size <= 0:
            raise InvariantViolation("bytes_size must be positive")
        if vendor_timestamp > fetch_time:
            raise InvariantViolation("vendor_timestamp must be <= fetch_time")
        if not self._rawstore.has(outputs.bytes_hash, reader=self._rawstore_reader):
            raise InvariantViolation("bytes_hash must exist in rawstore")

    def audit_extra_payload(
        self,
        inputs: EdgarIngestInput,
        outputs: EdgarIngestOutput,
        ctx: StageContext,
        *,
        inputs_hash: str,
        output_hash: str,
    ) -> dict[str, Any]:
        return {
            "source_id": outputs.source_id,
            "vendor_timestamp": outputs.vendor_timestamp,
            "fetch_time": outputs.fetch_time,
            "bytes_hash": outputs.bytes_hash,
            "bytes_size": outputs.bytes_size,
            "provenance": list(outputs.provenance),
        }

    def _fetch_with_retry(self, request: HTTPRequest, ctx: StageContext) -> HTTPResponse:
        attempt = 0
        while True:
            try:
                response = self._http_client.fetch(request)
            except EdgarNetworkError:
                ctx.charge_data_read(1)
                if attempt >= self._max_retries:
                    raise
            except EdgarHTTPStatusError as exc:
                ctx.charge_data_read(1)
                if not self._is_retryable_status(exc.status) or attempt >= self._max_retries:
                    raise
            else:
                ctx.charge_data_read(1)
                if 200 <= response.status < 300:
                    return response
                if not self._is_retryable_status(response.status) or attempt >= self._max_retries:
                    raise EdgarHTTPStatusError(
                        response.status,
                        "EDGAR returned a non-success status",
                        headers=response.headers,
                        body=response.body,
                    )

            self._sleep(self._backoff_seconds(attempt))
            attempt += 1

    def _backoff_seconds(self, attempt: int) -> float:
        base = min(_INITIAL_BACKOFF_SECONDS * (2**attempt), _MAX_BACKOFF_SECONDS)
        return base + self._rng.uniform(0.0, base / 2.0)

    @staticmethod
    def _is_retryable_status(status: int) -> bool:
        return status == 429 or 500 <= status <= 599

    def _resolve_vendor_timestamp(self, response: HTTPResponse) -> datetime:
        header_map = {key.lower(): value for key, value in response.headers.items()}
        last_modified = header_map.get("last-modified")
        if last_modified:
            try:
                return _parse_http_datetime(last_modified)
            except (TypeError, ValueError) as exc:
                raise EdgarVendorTimestampError(
                    f"invalid Last-Modified header: {last_modified!r}"
                ) from exc

        try:
            payload = json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise EdgarVendorTimestampError(
                "missing Last-Modified and response body did not contain valid JSON"
            ) from exc

        filing_dates = (
            payload.get("filings", {})
            .get("recent", {})
            .get("filingDate", [])
        )
        if filing_dates and filing_dates[0]:
            filing_day = datetime.fromisoformat(filing_dates[0]).date()
            return datetime.combine(filing_day, dt_time.min, tzinfo=timezone.utc)

        raise EdgarVendorTimestampError(
            "vendor timestamp unavailable: no Last-Modified header and no "
            "filings.recent.filingDate[0]"
        )
