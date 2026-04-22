"""Append-only, hash-chained audit log.

Implements methodology §6.9. One JSONL file per UTC calendar day. Each record
carries ``record_hash`` (sha256 of the canonicalized record without the hash
field) and ``prev_hash`` (the previous record's ``record_hash``). The chain
spans day files — the first record of a new day references the last record of
the most recent prior day, or the genesis sentinel if none exists.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Optional


GENESIS_HASH = "0" * 64

# Allowed keys inside the ``envelope`` subset per §6.9 "Record categories".
_ENVELOPE_KEYS = frozenset({"rule_id", "cycle_id", "m2a_id"})

# Day-file naming: <YYYY-MM-DD>.jsonl
_DAY_FILE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})\.jsonl$")


def canonicalize(record: dict[str, Any]) -> bytes:
    """Deterministic JSON encoding: sort keys, compact separators, UTF-8.

    This produces a single line with no trailing whitespace. It is the exact
    byte sequence that gets hashed (when ``record_hash`` is absent) and the
    exact byte sequence written to disk (with ``record_hash`` present).
    """
    return json.dumps(
        record,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def record_digest(record_without_hash: dict[str, Any]) -> str:
    """sha256 hex of the canonicalized record (must not contain record_hash)."""
    if "record_hash" in record_without_hash:
        raise ValueError("record_digest input must not contain record_hash")
    return hashlib.sha256(canonicalize(record_without_hash)).hexdigest()


def _ensure_utc(ts: Any) -> datetime:
    if isinstance(ts, datetime):
        if ts.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware")
        return ts.astimezone(timezone.utc)
    if isinstance(ts, str):
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            raise ValueError("timestamp string must include a UTC offset")
        return dt.astimezone(timezone.utc)
    raise TypeError("timestamp must be a datetime or an ISO-8601 string")


def _utc_day(ts: datetime) -> date:
    return ts.astimezone(timezone.utc).date()


def _iter_jsonl_lines(path: Path) -> Iterable[str]:
    with path.open("r", encoding="utf-8") as f:
        for raw in f:
            line = raw.rstrip("\n")
            if line:
                yield line


class AuditLog:
    """Append-only, hash-chained JSONL audit log rooted at ``root``.

    Instances are safe to share across threads in a single process (internal
    lock). Process-level coordination is the caller's responsibility — only
    one writer per log directory at a time.
    """

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._last_hash, self._last_timestamp_iso = self._recover_state()

    # --- public API -------------------------------------------------------

    def validate_record(self, record: dict[str, Any]) -> None:
        """Validate caller-supplied fields without appending.

        This checks the same shape and JSON-serializability constraints as
        :meth:`append`, but it does not inject defaults, compute hashes, or
        consult the current chain tail. Callers that need to stage side effects
        can use this to fail early before mutating other stores.
        """
        self._prepare_record(record, assign_defaults=False)

    def append(self, record: dict[str, Any]) -> str:
        """Append ``record`` to the current day's file, return its record_hash.

        Caller supplies: ``category``, ``stage``, ``envelope`` (subset of
        rule_id/cycle_id/m2a_id), plus category-specific payload keys.
        Optional: ``timestamp`` (datetime or ISO string; defaults to now UTC),
        ``record_id`` (string; defaults to a fresh UUID4).
        ``record_hash`` and ``prev_hash`` are computed — supplying them is an
        error.
        """
        rec = self._prepare_record(record, assign_defaults=True)
        ts = _ensure_utc(rec["timestamp"])

        with self._lock:
            if self._last_timestamp_iso is not None:
                prev_ts = _ensure_utc(self._last_timestamp_iso)
                if ts < prev_ts:
                    raise ValueError(
                        "timestamp must be monotonically non-decreasing: "
                        f"{ts.isoformat()} precedes last {self._last_timestamp_iso}"
                    )

            rec["prev_hash"] = self._last_hash
            rec["record_hash"] = record_digest({k: v for k, v in rec.items() if k != "record_hash"})

            line_bytes = canonicalize(rec)
            day = _utc_day(ts)
            path = self._day_file(day)
            # O_APPEND keeps concurrent in-process writers safe under the lock;
            # trailing '\n' separates JSONL records.
            with path.open("ab") as f:
                f.write(line_bytes + b"\n")

            self._last_hash = rec["record_hash"]
            self._last_timestamp_iso = rec["timestamp"]
            return rec["record_hash"]

    def verify_chain(self, day: date) -> bool:
        """Verify the hash chain of a single day-file.

        Checks: (a) every record's ``record_hash`` matches its canonical
        digest; (b) every record's ``prev_hash`` equals the immediate
        predecessor's ``record_hash``; (c) the first record's ``prev_hash``
        equals the prior day's tail (or ``GENESIS_HASH``); (d) each record's
        UTC-day matches the filename.
        """
        path = self._day_file(day)
        if not path.exists():
            return True  # nothing to verify

        expected_prev = self._tail_hash_before(day)
        for line in _iter_jsonl_lines(path):
            if not self._verify_line(line, expected_prev, expected_day=day):
                return False
            expected_prev = json.loads(line)["record_hash"]
        return True

    def verify_cross_day(self, day_range: tuple[date, date]) -> bool:
        """Verify chain continuity across an inclusive ``(start, end)`` range.

        Days with no file are skipped — the chain simply links the last
        existing record before the gap to the first existing record after it.
        The starting expected-prev is seeded from any file prior to ``start``
        so that a partial-range verification still catches tampering at the
        boundary.
        """
        if not (isinstance(day_range, tuple) and len(day_range) == 2):
            raise TypeError("day_range must be a (start_date, end_date) tuple")
        start, end = day_range
        if not isinstance(start, date) or not isinstance(end, date):
            raise TypeError("day_range elements must be date objects")
        if end < start:
            raise ValueError("end must be >= start")

        expected_prev = self._tail_hash_before(start)
        d = start
        while d <= end:
            path = self._day_file(d)
            if path.exists():
                for line in _iter_jsonl_lines(path):
                    if not self._verify_line(line, expected_prev, expected_day=d):
                        return False
                    expected_prev = json.loads(line)["record_hash"]
            d += timedelta(days=1)
        return True

    # --- internals --------------------------------------------------------

    def _day_file(self, day: date) -> Path:
        return self._root / f"{day.isoformat()}.jsonl"

    def _day_files_sorted(self) -> list[Path]:
        files = [p for p in self._root.iterdir() if p.is_file() and _DAY_FILE_RE.match(p.name)]
        files.sort(key=lambda p: p.name)
        return files

    def _tail_hash_before(self, day: date) -> str:
        """Return the record_hash of the last record strictly before ``day``."""
        target = f"{day.isoformat()}.jsonl"
        prior = [p for p in self._day_files_sorted() if p.name < target]
        for p in reversed(prior):
            last_line: Optional[str] = None
            for line in _iter_jsonl_lines(p):
                last_line = line
            if last_line is not None:
                return json.loads(last_line)["record_hash"]
        return GENESIS_HASH

    def _recover_state(self) -> tuple[str, Optional[str]]:
        """Walk back through existing day-files to find the chain tail."""
        for p in reversed(self._day_files_sorted()):
            last_line: Optional[str] = None
            for line in _iter_jsonl_lines(p):
                last_line = line
            if last_line is not None:
                rec = json.loads(last_line)
                return rec["record_hash"], rec["timestamp"]
        return GENESIS_HASH, None

    @staticmethod
    def _prepare_record(
        record: dict[str, Any],
        *,
        assign_defaults: bool,
    ) -> dict[str, Any]:
        if not isinstance(record, dict):
            raise TypeError("record must be a dict")
        rec: dict[str, Any] = dict(record)

        if "record_hash" in rec:
            raise ValueError("record_hash is computed; do not supply it")
        if "prev_hash" in rec:
            raise ValueError("prev_hash is computed; do not supply it")

        if "timestamp" in rec:
            rec["timestamp"] = _ensure_utc(rec["timestamp"]).isoformat()
        elif assign_defaults:
            rec["timestamp"] = datetime.now(timezone.utc).isoformat()

        if "record_id" in rec:
            if not isinstance(rec["record_id"], str) or not rec["record_id"]:
                raise ValueError("record_id must be a non-empty string")
        elif assign_defaults:
            rec["record_id"] = str(uuid.uuid4())

        for field in ("category", "stage"):
            val = rec.get(field)
            if not isinstance(val, str) or not val:
                raise ValueError(f"{field} is required and must be a non-empty string")

        env = rec.get("envelope")
        if not isinstance(env, dict):
            raise ValueError("envelope is required and must be a dict")
        extra = set(env.keys()) - _ENVELOPE_KEYS
        if extra:
            raise ValueError(
                f"envelope keys must be subset of {sorted(_ENVELOPE_KEYS)}; "
                f"unexpected: {sorted(extra)}"
            )

        canonicalize(rec)
        return rec

    @staticmethod
    def _verify_line(line: str, expected_prev: str, *, expected_day: date) -> bool:
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            return False
        if not isinstance(rec, dict):
            return False
        stated_hash = rec.get("record_hash")
        stated_prev = rec.get("prev_hash")
        if not isinstance(stated_hash, str) or not isinstance(stated_prev, str):
            return False
        if stated_prev != expected_prev:
            return False
        ts_str = rec.get("timestamp")
        if not isinstance(ts_str, str):
            return False
        try:
            ts = _ensure_utc(ts_str)
        except (ValueError, TypeError):
            return False
        if _utc_day(ts) != expected_day:
            return False
        check = {k: v for k, v in rec.items() if k != "record_hash"}
        if record_digest(check) != stated_hash:
            return False
        return True
