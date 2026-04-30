"""Content-addressed, append-only raw store.

Implements methodology §6.2 "Raw store": bytes keyed by sha256, provenance
triples stored separately (joined by hash, so multiple vendors contributing
identical bytes multiply provenance without duplicating storage), and
corrections represented as new entries that reference the original by hash.
No mutation of existing entries.
"""

from __future__ import annotations

import hashlib
import sqlite3
import threading
import weakref
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple, Optional


class Provenance(NamedTuple):
    source_id: str
    fetch_time: datetime
    vendor_timestamp: datetime


class _IssuedReader:
    """Opaque per-store read capability.

    The class itself is not a capability boundary; authorization is by object
    identity against the issuing ``RawStore`` instance's private registry.
    """

    __slots__ = ("__weakref__",)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS blobs (
    hash TEXT PRIMARY KEY,
    bytes_path TEXT NOT NULL,
    bytes_size INTEGER NOT NULL,
    first_seen_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS provenance (
    hash TEXT NOT NULL,
    source_id TEXT NOT NULL,
    fetch_time_utc TEXT NOT NULL,
    vendor_timestamp_utc TEXT NOT NULL,
    PRIMARY KEY (hash, source_id, fetch_time_utc, vendor_timestamp_utc),
    FOREIGN KEY (hash) REFERENCES blobs(hash)
);

CREATE TABLE IF NOT EXISTS corrections (
    correction_hash TEXT NOT NULL,
    original_hash TEXT NOT NULL,
    PRIMARY KEY (correction_hash, original_hash)
);

CREATE INDEX IF NOT EXISTS idx_corrections_original
    ON corrections(original_hash);

CREATE TABLE IF NOT EXISTS llm_cache (
    model_id TEXT NOT NULL,
    prompt_hash TEXT NOT NULL,
    params_hash TEXT NOT NULL,
    bytes_hash TEXT NOT NULL,
    first_written_utc TEXT NOT NULL,
    PRIMARY KEY (model_id, prompt_hash, params_hash),
    FOREIGN KEY (bytes_hash) REFERENCES blobs(hash)
);
"""


def _to_utc_iso(ts: datetime) -> str:
    if ts.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return ts.astimezone(timezone.utc).isoformat()


def _from_utc_iso(s: str) -> datetime:
    return datetime.fromisoformat(s)


class RawStore:
    """Append-only, content-addressed raw store.

    Storage layout:
        <root>/index.sqlite                     index (blobs, provenance, corrections)
        <root>/bytes/<YYYY-MM-DD>/<pp>/<hash>   immutable byte file; <pp> is hash[:2].
    """

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._bytes_root = self._root / "bytes"
        self._bytes_root.mkdir(exist_ok=True)
        self._db_path = self._root / "index.sqlite"
        self._lock = threading.Lock()
        self.__readers: weakref.WeakSet[_IssuedReader] = weakref.WeakSet()
        self._conn = sqlite3.connect(
            self._db_path, check_same_thread=False, isolation_level=None
        )
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self) -> "RawStore":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def _issue_reader(self) -> object:
        """Mint a store-local read capability for trusted callers.

        Package-private. AccessLayer uses this during construction, then keeps
        the resulting capability in closures rather than on its public surface.
        """
        reader = _IssuedReader()
        self.__readers.add(reader)
        return reader

    def _require_reader(self, reader: object) -> None:
        if reader not in self.__readers:
            raise PermissionError(
                "RawStore reads require a capability issued by this RawStore "
                "instance; direct access is forbidden by methodology §6.2."
            )

    def put(
        self,
        data: bytes,
        provenance: Provenance,
        *,
        corrects: Optional[str] = None,
    ) -> str:
        """Append bytes (idempotent on repeat hash) and record provenance.

        Returns the sha256 hex digest of ``data``. If ``corrects`` is supplied
        (a prior sha256 hex digest), records that these new bytes correct that
        original; the original is not mutated.
        """
        data = _coerce_data(data)
        fetch_iso, vendor_iso = _normalize_provenance(provenance)
        if corrects is not None and (not isinstance(corrects, str) or len(corrects) != 64):
            raise ValueError("corrects must be a sha256 hex digest")

        with self._lock:
            cur = self._conn.cursor()
            cur.execute("BEGIN IMMEDIATE")
            try:
                h = self._put_rows(
                    cur,
                    data=data,
                    provenance=provenance,
                    fetch_iso=fetch_iso,
                    vendor_iso=vendor_iso,
                )
                if corrects is not None:
                    cur.execute(
                        "INSERT OR IGNORE INTO corrections("
                        "correction_hash, original_hash) VALUES (?, ?)",
                        (h, corrects),
                    )
                cur.execute("COMMIT")
            except Exception:
                cur.execute("ROLLBACK")
                raise

        return h

    def _put_llm_response(
        self,
        data: bytes,
        provenance: Provenance,
        *,
        reader: object,
        model_id: str,
        prompt_hash: str,
        params_hash: str,
    ) -> str:
        self._require_reader(reader)
        data = _coerce_data(data)
        fetch_iso, vendor_iso = _normalize_provenance(provenance)
        _validate_llm_key(model_id=model_id, prompt_hash=prompt_hash, params_hash=params_hash)
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("BEGIN IMMEDIATE")
            try:
                h = self._put_rows(
                    cur,
                    data=data,
                    provenance=provenance,
                    fetch_iso=fetch_iso,
                    vendor_iso=vendor_iso,
                )
                cur.execute(
                    "INSERT OR IGNORE INTO llm_cache("
                    "model_id, prompt_hash, params_hash, bytes_hash, first_written_utc) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (model_id, prompt_hash, params_hash, h, fetch_iso),
                )
                cur.execute("COMMIT")
            except Exception:
                cur.execute("ROLLBACK")
                raise
        return h

    def get(self, hash: str, *, reader: object) -> bytes:
        self._require_reader(reader)
        with self._lock:
            row = self._conn.execute(
                "SELECT bytes_path FROM blobs WHERE hash = ?", (hash,)
            ).fetchone()
        if row is None:
            raise KeyError(hash)
        return (self._bytes_root / row[0]).read_bytes()

    def provenance(self, hash: str, *, reader: object) -> list[Provenance]:
        self._require_reader(reader)
        with self._lock:
            rows = self._conn.execute(
                "SELECT source_id, fetch_time_utc, vendor_timestamp_utc "
                "FROM provenance WHERE hash = ? "
                "ORDER BY fetch_time_utc, source_id, vendor_timestamp_utc",
                (hash,),
            ).fetchall()
        return [
            Provenance(r[0], _from_utc_iso(r[1]), _from_utc_iso(r[2]))
            for r in rows
        ]

    def corrections(self, hash: str, *, reader: object) -> list[str]:
        self._require_reader(reader)
        with self._lock:
            rows = self._conn.execute(
                "SELECT correction_hash FROM corrections "
                "WHERE original_hash = ? ORDER BY correction_hash",
                (hash,),
            ).fetchall()
        return [r[0] for r in rows]

    def has(self, hash: str, *, reader: object) -> bool:
        self._require_reader(reader)
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM blobs WHERE hash = ?", (hash,)
            ).fetchone()
        return row is not None

    def _lookup_llm(
        self,
        reader: object,
        *,
        model_id: str,
        prompt_hash: str,
        params_hash: str,
    ) -> str | None:
        self._require_reader(reader)
        _validate_llm_key(model_id=model_id, prompt_hash=prompt_hash, params_hash=params_hash)
        with self._lock:
            row = self._conn.execute(
                "SELECT bytes_hash FROM llm_cache "
                "WHERE model_id = ? AND prompt_hash = ? AND params_hash = ?",
                (model_id, prompt_hash, params_hash),
            ).fetchone()
        return None if row is None else row[0]

    def _insert_llm_cache(
        self,
        reader: object,
        *,
        model_id: str,
        prompt_hash: str,
        params_hash: str,
        bytes_hash: str,
    ) -> None:
        self._require_reader(reader)
        _validate_llm_key(model_id=model_id, prompt_hash=prompt_hash, params_hash=params_hash)
        if not isinstance(bytes_hash, str) or len(bytes_hash) != 64:
            raise ValueError("bytes_hash must be a sha256 hex digest")
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO llm_cache("
                "model_id, prompt_hash, params_hash, bytes_hash, first_written_utc) "
                "VALUES (?, ?, ?, ?, ?)",
                (model_id, prompt_hash, params_hash, bytes_hash, now),
            )

    def _put_rows(
        self,
        cur: sqlite3.Cursor,
        *,
        data: bytes,
        provenance: Provenance,
        fetch_iso: str,
        vendor_iso: str,
    ) -> str:
        source_id = provenance.source_id
        h = hashlib.sha256(data).hexdigest()
        row = cur.execute(
            "SELECT 1 FROM blobs WHERE hash = ?", (h,)
        ).fetchone()
        if row is None:
            now = datetime.now(timezone.utc)
            day_dir = self._bytes_root / now.date().isoformat() / h[:2]
            day_dir.mkdir(parents=True, exist_ok=True)
            blob_path = day_dir / h
            tmp_path = day_dir / (h + ".tmp")
            tmp_path.write_bytes(data)
            tmp_path.replace(blob_path)
            rel = blob_path.relative_to(self._bytes_root).as_posix()
            cur.execute(
                "INSERT INTO blobs(hash, bytes_path, bytes_size, first_seen_utc) "
                "VALUES (?, ?, ?, ?)",
                (h, rel, len(data), now.isoformat()),
            )
        cur.execute(
            "INSERT OR IGNORE INTO provenance("
            "hash, source_id, fetch_time_utc, vendor_timestamp_utc) "
            "VALUES (?, ?, ?, ?)",
            (h, source_id, fetch_iso, vendor_iso),
        )
        return h


def _coerce_data(data: bytes) -> bytes:
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError("data must be bytes-like")
    return bytes(data)


def _normalize_provenance(provenance: Provenance) -> tuple[str, str]:
    source_id, fetch_time, vendor_timestamp = provenance
    if not isinstance(source_id, str) or not source_id:
        raise ValueError("provenance.source_id must be a non-empty string")
    fetch_iso = _to_utc_iso(fetch_time)
    vendor_iso = _to_utc_iso(vendor_timestamp)
    return fetch_iso, vendor_iso


def _validate_llm_key(*, model_id: str, prompt_hash: str, params_hash: str) -> None:
    if not isinstance(model_id, str) or not model_id:
        raise ValueError("model_id must be a non-empty string")
    for label, value in (("prompt_hash", prompt_hash), ("params_hash", params_hash)):
        if not isinstance(value, str) or len(value) != 64:
            raise ValueError(f"{label} must be a sha256 hex digest")
