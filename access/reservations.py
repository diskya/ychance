from __future__ import annotations

import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


class WindowReservationError(PermissionError):
    """Raised when a stage requests a rule window that is unavailable."""


@dataclass(frozen=True)
class WindowReservation:
    reservation_id: str
    rule_id: str
    stage: str
    t0: str
    t1: str
    cycle_id: str

    def as_dict(self) -> dict[str, str]:
        return {
            "reservation_id": self.reservation_id,
            "rule_id": self.rule_id,
            "stage": self.stage,
            "t0": self.t0,
            "t1": self.t1,
            "cycle_id": self.cycle_id,
        }


_SCHEMA = """
CREATE TABLE IF NOT EXISTS window_reservations (
    reservation_id TEXT PRIMARY KEY,
    rule_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    t0_utc TEXT NOT NULL,
    t1_utc TEXT NOT NULL,
    cycle_id TEXT NOT NULL,
    created_utc TEXT NOT NULL,
    UNIQUE(rule_id, stage, t0_utc, t1_utc)
);

CREATE INDEX IF NOT EXISTS idx_window_reservations_rule_stage
    ON window_reservations(rule_id, stage, t0_utc, t1_utc);
"""


class WindowReservationBook:
    """Persistent rule-window reservation ledger used by the access layer."""

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._db_path = self._root / "window_reservations.sqlite"
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(
            self._db_path,
            check_same_thread=False,
            isolation_level=None,
        )
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self) -> "WindowReservationBook":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def reserve(
        self,
        *,
        rule_id: str,
        stage: str,
        t0: datetime,
        t1: datetime,
        cycle_id: str,
    ) -> tuple[WindowReservation, bool]:
        rule_id = _rule_id(rule_id)
        stage = _stage(stage)
        cycle_id = _cycle_id(cycle_id)
        t0_iso, t1_iso = _window_iso(t0, t1)
        with self._lock:
            existing = self._lookup_exact(
                rule_id=rule_id,
                stage=stage,
                t0_iso=t0_iso,
                t1_iso=t1_iso,
            )
            if existing is not None:
                return existing, False

            reservation = WindowReservation(
                reservation_id=str(uuid.uuid4()),
                rule_id=rule_id,
                stage=stage,
                t0=t0_iso,
                t1=t1_iso,
                cycle_id=cycle_id,
            )
            self._conn.execute(
                "INSERT INTO window_reservations("
                "reservation_id, rule_id, stage, t0_utc, t1_utc, cycle_id, created_utc"
                ") VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    reservation.reservation_id,
                    reservation.rule_id,
                    reservation.stage,
                    reservation.t0,
                    reservation.t1,
                    reservation.cycle_id,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            return reservation, True

    def exact(
        self,
        *,
        rule_id: str,
        stage: str,
        t0: datetime,
        t1: datetime,
    ) -> WindowReservation | None:
        rule_id = _rule_id(rule_id)
        stage = _stage(stage)
        t0_iso, t1_iso = _window_iso(t0, t1)
        with self._lock:
            return self._lookup_exact(
                rule_id=rule_id,
                stage=stage,
                t0_iso=t0_iso,
                t1_iso=t1_iso,
            )

    def overlapping(
        self,
        *,
        rule_id: str,
        t0: datetime,
        t1: datetime,
        stage: str | None = None,
    ) -> list[WindowReservation]:
        rule_id = _rule_id(rule_id)
        stage = None if stage is None else _stage(stage)
        t0_iso, t1_iso = _window_iso(t0, t1)
        with self._lock:
            if stage is None:
                rows = self._conn.execute(
                    "SELECT reservation_id, rule_id, stage, t0_utc, t1_utc, cycle_id "
                    "FROM window_reservations "
                    "WHERE rule_id = ? AND t0_utc <= ? AND t1_utc >= ? "
                    "ORDER BY t0_utc, t1_utc, stage",
                    (rule_id, t1_iso, t0_iso),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT reservation_id, rule_id, stage, t0_utc, t1_utc, cycle_id "
                    "FROM window_reservations "
                    "WHERE rule_id = ? AND stage = ? AND t0_utc <= ? AND t1_utc >= ? "
                    "ORDER BY t0_utc, t1_utc",
                    (rule_id, stage, t1_iso, t0_iso),
                ).fetchall()
        return [_reservation_from_row(row) for row in rows]

    def _lookup_exact(
        self,
        *,
        rule_id: str,
        stage: str,
        t0_iso: str,
        t1_iso: str,
    ) -> WindowReservation | None:
        row = self._conn.execute(
            "SELECT reservation_id, rule_id, stage, t0_utc, t1_utc, cycle_id "
            "FROM window_reservations "
            "WHERE rule_id = ? AND stage = ? AND t0_utc = ? AND t1_utc = ?",
            (rule_id, stage, t0_iso, t1_iso),
        ).fetchone()
        return None if row is None else _reservation_from_row(row)


def _reservation_from_row(row: tuple[str, str, str, str, str, str]) -> WindowReservation:
    return WindowReservation(
        reservation_id=row[0],
        rule_id=row[1],
        stage=row[2],
        t0=row[3],
        t1=row[4],
        cycle_id=row[5],
    )


def _window_iso(t0: datetime, t1: datetime) -> tuple[str, str]:
    start = _ensure_utc(t0, "t0")
    end = _ensure_utc(t1, "t1")
    if end < start:
        raise ValueError("window t1 must be >= t0")
    return start.isoformat(), end.isoformat()


def _ensure_utc(ts: datetime, field: str) -> datetime:
    if not isinstance(ts, datetime):
        raise TypeError(f"{field} must be a datetime")
    if ts.tzinfo is None:
        raise ValueError(f"{field} must be timezone-aware")
    return ts.astimezone(timezone.utc)


def _rule_id(value: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError("rule_id must be a 64-character string")
    return value


def _stage(value: str) -> str:
    if value not in {"Screen", "Validate"}:
        raise ValueError("reservation stage must be Screen or Validate")
    return value


def _cycle_id(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("cycle_id must be a non-empty string")
    return value
