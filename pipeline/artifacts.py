"""Content-addressed store for Stage output artifacts.

Methodology §6.2 reserves ``rawstore/`` for vendor observations
(append-only, provenance-tagged). Stage outputs are computational
derivatives: a feature tensor, a screen report, a Council rationale.
They live here, keyed by the sha256 of their canonical bytes, alongside
a fingerprint table that maps ``(stage_name, stage_version,
inputs_hash)`` to the output hash produced by the most recent
successful invocation. That table is what lets ``PipelineDAG`` skip a
stage whose inputs are unchanged.

The store is deliberately thinner than ``RawStore``:

- No provenance, no corrections, no authorized-reader gate — artifacts
  are reproducible from their inputs, so the integrity story is
  "recompute and compare hashes" rather than "audit every read".
- No per-day directory layout. Artifacts dedup aggressively, so a flat
  prefix-tree keeps the hot path short.
"""

from __future__ import annotations

import hashlib
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


_SCHEMA = """
CREATE TABLE IF NOT EXISTS artifacts (
    hash TEXT PRIMARY KEY,
    bytes_path TEXT NOT NULL,
    bytes_size INTEGER NOT NULL,
    created_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fingerprints (
    fingerprint TEXT PRIMARY KEY,
    stage_name TEXT NOT NULL,
    stage_version TEXT NOT NULL,
    inputs_hash TEXT NOT NULL,
    output_hash TEXT NOT NULL,
    created_utc TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_fingerprints_stage
    ON fingerprints(stage_name, stage_version);
"""


class ArtifactStore:
    """Content-addressed artifact blob store + fingerprint manifest.

    Layout:
        <root>/objects/<pp>/<hash>   immutable artifact bytes (pp = hash[:2]).
        <root>/index.sqlite          artifacts table + fingerprints table.
    """

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._objects_root = self._root / "objects"
        self._objects_root.mkdir(exist_ok=True)
        self._db_path = self._root / "index.sqlite"
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(
            self._db_path, check_same_thread=False, isolation_level=None
        )
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self) -> "ArtifactStore":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    # --- blobs ------------------------------------------------------------

    def put(self, data: bytes) -> str:
        """Append ``data`` idempotently; return its sha256 hex digest."""
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError("data must be bytes-like")
        data = bytes(data)
        h = hashlib.sha256(data).hexdigest()
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("BEGIN IMMEDIATE")
            try:
                row = cur.execute(
                    "SELECT bytes_path FROM artifacts WHERE hash = ?", (h,)
                ).fetchone()
                if row is None:
                    prefix_dir = self._objects_root / h[:2]
                    prefix_dir.mkdir(parents=True, exist_ok=True)
                    blob_path = prefix_dir / h
                    rel = blob_path.relative_to(self._objects_root).as_posix()
                    tmp_path = prefix_dir / (h + ".tmp")
                    tmp_path.write_bytes(data)
                    tmp_path.replace(blob_path)
                    cur.execute(
                        "INSERT INTO artifacts(hash, bytes_path, bytes_size, created_utc) "
                        "VALUES (?, ?, ?, ?)",
                        (h, rel, len(data), datetime.now(timezone.utc).isoformat()),
                    )
                else:
                    blob_path = self._objects_root / row[0]
                    if not blob_path.exists():
                        blob_path.parent.mkdir(parents=True, exist_ok=True)
                        tmp_path = blob_path.parent / (h + ".tmp")
                        tmp_path.write_bytes(data)
                        tmp_path.replace(blob_path)
                cur.execute("COMMIT")
            except Exception:
                cur.execute("ROLLBACK")
                raise
        return h

    def get(self, hash: str) -> bytes:
        with self._lock:
            row = self._conn.execute(
                "SELECT bytes_path FROM artifacts WHERE hash = ?", (hash,)
            ).fetchone()
        if row is None:
            raise KeyError(hash)
        path = self._objects_root / row[0]
        if not path.exists():
            raise KeyError(hash)
        return path.read_bytes()

    def has(self, hash: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT bytes_path FROM artifacts WHERE hash = ?", (hash,)
            ).fetchone()
        if row is None:
            return False
        return (self._objects_root / row[0]).exists()

    # --- fingerprints -----------------------------------------------------

    def record_fingerprint(
        self,
        fingerprint: str,
        *,
        stage_name: str,
        stage_version: str,
        inputs_hash: str,
        output_hash: str,
    ) -> None:
        """Persist ``(stage, version, inputs_hash) -> output_hash``.

        A repeat write of the same ``output_hash`` is a no-op. A conflicting
        ``output_hash`` for the same fingerprint is rejected: unchanged inputs
        and unchanged stage version must not silently diverge.
        """
        if not self.has(output_hash):
            raise KeyError(
                f"cannot record fingerprint for missing artifact {output_hash}"
            )
        with self._lock:
            row = self._conn.execute(
                "SELECT output_hash FROM fingerprints WHERE fingerprint = ?",
                (fingerprint,),
            ).fetchone()
            if row is not None:
                existing = row[0]
                if existing != output_hash:
                    raise ValueError(
                        "fingerprint conflict: unchanged inputs/version produced "
                        f"{output_hash}, existing cache points to {existing}"
                    )
                return
            self._conn.execute(
                "INSERT INTO fingerprints("
                "fingerprint, stage_name, stage_version, inputs_hash, "
                "output_hash, created_utc) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    fingerprint,
                    stage_name,
                    stage_version,
                    inputs_hash,
                    output_hash,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    def lookup_fingerprint(self, fingerprint: str) -> Optional[str]:
        """Return the cached output_hash for this fingerprint, or None."""
        with self._lock:
            row = self._conn.execute(
                "SELECT output_hash FROM fingerprints WHERE fingerprint = ?",
                (fingerprint,),
            ).fetchone()
        return row[0] if row else None
