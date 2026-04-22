"""Access layer — the sole read path into the raw store.

Implements methodology §6.2 "Representation for Propose". Every read of the
raw store passes through ``AccessLayer``, which:

1. Refuses to serve entries whose earliest known ``vendor_timestamp`` is
   strictly greater than the caller's explicit ``query_time`` (no peek).
2. Enforces a per-cycle ceiling on read volume so a single discovery-loop
   cycle cannot exhaust the operations budget on raw reads alone.
3. Appends an audit record (via the 1.2 audit log) for every read attempt
   — admitted, denied for peek, or denied by rate limit.

The raw store refuses reads from any caller that is not an
``AuthorizedReader``; ``AccessLayer`` is the only production subclass.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from audit import AuditLog
from rawstore import AuthorizedReader, Provenance, RawStore


class RateLimitExceeded(RuntimeError):
    """Raised when an access call would exceed the current cycle's read budget."""


class TemporalAdmissibilityError(PermissionError):
    """Raised when a read would reveal data with ``vendor_timestamp > query_time``."""


def _ensure_utc(ts: datetime) -> datetime:
    if not isinstance(ts, datetime):
        raise TypeError("query_time must be a datetime")
    if ts.tzinfo is None:
        raise ValueError("query_time must be timezone-aware")
    return ts.astimezone(timezone.utc)


class AccessLayer(AuthorizedReader):
    """Thin wrapper over ``RawStore`` enforcing temporal admissibility,
    per-cycle read rate limit, and audit logging.

    One instance corresponds to one read budget. ``begin_cycle`` rolls the
    cycle id and resets the counter.
    """

    def __init__(
        self,
        store: RawStore,
        audit: AuditLog,
        *,
        cycle_id: str,
        max_reads_per_cycle: int,
    ) -> None:
        if not isinstance(store, RawStore):
            raise TypeError("store must be a RawStore")
        if not isinstance(audit, AuditLog):
            raise TypeError("audit must be an AuditLog")
        if not isinstance(cycle_id, str) or not cycle_id:
            raise ValueError("cycle_id must be a non-empty string")
        if not isinstance(max_reads_per_cycle, int) or max_reads_per_cycle < 0:
            raise ValueError("max_reads_per_cycle must be a non-negative int")
        self._store = store
        self._audit = audit
        self._cycle_id = cycle_id
        self._max_reads = max_reads_per_cycle
        self._count = 0

    # --- cycle control ---------------------------------------------------

    @property
    def cycle_id(self) -> str:
        return self._cycle_id

    @property
    def max_reads_per_cycle(self) -> int:
        return self._max_reads

    @property
    def reads_used(self) -> int:
        return self._count

    @property
    def reads_remaining(self) -> int:
        return self._max_reads - self._count

    def begin_cycle(self, cycle_id: str) -> None:
        """Roll over to ``cycle_id`` and reset the read counter."""
        if not isinstance(cycle_id, str) or not cycle_id:
            raise ValueError("cycle_id must be a non-empty string")
        self._cycle_id = cycle_id
        self._count = 0

    # --- read surface ----------------------------------------------------

    def get(self, hash: str, query_time: datetime) -> bytes:
        """Return raw bytes iff an admissible provenance exists at ``query_time``.

        Raises ``KeyError`` for unknown hashes, ``TemporalAdmissibilityError``
        when no provenance has ``vendor_timestamp ≤ query_time``, and
        ``RateLimitExceeded`` once the cycle budget is exhausted.
        """
        qt = _ensure_utc(query_time)
        self._enforce_budget(hash=hash, qt=qt, kind="bytes")
        provs = self._store.provenance(hash, reader=self)
        if not provs:
            self._log_read(hash, qt, kind="bytes", outcome="unknown")
            raise KeyError(hash)
        earliest = min(p.vendor_timestamp for p in provs)
        if earliest > qt:
            self._log_read(
                hash,
                qt,
                kind="bytes",
                outcome="future_denied",
                earliest_vendor_timestamp=earliest.isoformat(),
            )
            raise TemporalAdmissibilityError(
                f"hash {hash}: earliest vendor_timestamp "
                f"{earliest.isoformat()} > query_time {qt.isoformat()}"
            )
        data = self._store.get(hash, reader=self)
        self._count += 1
        self._log_read(
            hash,
            qt,
            kind="bytes",
            outcome="ok",
            bytes_size=len(data),
        )
        return data

    def provenance(self, hash: str, query_time: datetime) -> list[Provenance]:
        """Return provenance triples whose ``vendor_timestamp ≤ query_time``.

        Triples from the future are filtered out; an unknown hash or an
        entry with no admissible provenance both yield an empty list. An
        empty return is therefore indistinguishable between "not known" and
        "not yet visible" — Propose cannot peek by polling.
        """
        qt = _ensure_utc(query_time)
        self._enforce_budget(hash=hash, qt=qt, kind="provenance")
        triples = self._store.provenance(hash, reader=self)
        visible = [p for p in triples if p.vendor_timestamp <= qt]
        self._count += 1
        self._log_read(
            hash,
            qt,
            kind="provenance",
            outcome="ok",
            returned=len(visible),
            suppressed=len(triples) - len(visible),
        )
        return visible

    def corrections(self, hash: str, query_time: datetime) -> list[str]:
        """Return correction-hashes whose own earliest vendor_timestamp ≤ ``query_time``."""
        qt = _ensure_utc(query_time)
        self._enforce_budget(hash=hash, qt=qt, kind="corrections")
        all_links = self._store.corrections(hash, reader=self)
        visible: list[str] = []
        suppressed = 0
        for ch in all_links:
            c_provs = self._store.provenance(ch, reader=self)
            if c_provs and min(p.vendor_timestamp for p in c_provs) <= qt:
                visible.append(ch)
            else:
                suppressed += 1
        self._count += 1
        self._log_read(
            hash,
            qt,
            kind="corrections",
            outcome="ok",
            returned=len(visible),
            suppressed=suppressed,
        )
        return visible

    # --- internals -------------------------------------------------------

    def _enforce_budget(self, *, hash: str, qt: datetime, kind: str) -> None:
        if self._count >= self._max_reads:
            self._log_read(hash, qt, kind=kind, outcome="rate_limited")
            raise RateLimitExceeded(
                f"cycle {self._cycle_id!r}: read budget "
                f"{self._max_reads} exhausted"
            )

    def _log_read(
        self,
        hash: str,
        query_time: datetime,
        *,
        kind: str,
        outcome: str,
        **extra: Any,
    ) -> None:
        record: dict[str, Any] = {
            "category": "Access",
            "stage": "access",
            "envelope": {"cycle_id": self._cycle_id},
            "hash": hash,
            "query_time": query_time.isoformat(),
            "kind": kind,
            "outcome": outcome,
            "reads_used_after": self._count,
            "reads_max": self._max_reads,
        }
        record.update(extra)
        self._audit.append(record)
