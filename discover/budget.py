from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


CostKind = Literal["compute", "llm", "data_read"]


class BudgetKill(RuntimeError):
    """Raised before an action that cannot fit under the cycle cap."""

    def __init__(self, *, attempted_action: str, requested_usd: float, remaining_usd: float) -> None:
        self.attempted_action = attempted_action
        self.requested_usd = float(requested_usd)
        self.remaining_usd = float(remaining_usd)
        super().__init__(
            f"cycle budget exhausted before {attempted_action}: "
            f"requested {requested_usd:.12f}, remaining {remaining_usd:.12f}"
        )


@dataclass(frozen=True)
class BudgetReservation:
    kind: CostKind
    action: str
    usd: float


@dataclass(frozen=True)
class DiscoverCostUsed:
    compute_usd: float
    llm_usd: float
    data_reads: int
    data_read_usd: float
    reserved_usd: float
    realized_usd: float
    cap_usd: float

    def as_dict(self) -> dict[str, float | int]:
        return {
            "compute_usd": self.compute_usd,
            "llm_usd": self.llm_usd,
            "data_reads": self.data_reads,
            "data_read_usd": self.data_read_usd,
            "reserved_usd": self.reserved_usd,
            "realized_usd": self.realized_usd,
            "cap_usd": self.cap_usd,
        }


class CycleBudget:
    """Reserve-before-dispatch budget for one Discover cycle."""

    def __init__(self, *, cap_usd: float, data_read_usd: float = 0.0) -> None:
        if not isinstance(cap_usd, (int, float)) or float(cap_usd) < 0.0:
            raise ValueError("cap_usd must be a non-negative number")
        if not isinstance(data_read_usd, (int, float)) or float(data_read_usd) < 0.0:
            raise ValueError("data_read_usd must be a non-negative number")
        self._cap_usd = float(cap_usd)
        self._data_read_usd = float(data_read_usd)
        self._reserved_usd = 0.0
        self._compute_usd = 0.0
        self._llm_usd = 0.0
        self._data_reads = 0

    @property
    def cap_usd(self) -> float:
        return self._cap_usd

    @property
    def data_read_usd(self) -> float:
        return self._data_read_usd

    @property
    def reserved_usd(self) -> float:
        return self._reserved_usd

    @property
    def realized_usd(self) -> float:
        return self._compute_usd + self._llm_usd + self.data_read_usd_total

    @property
    def data_read_usd_total(self) -> float:
        return self._data_reads * self._data_read_usd

    @property
    def remaining_usd(self) -> float:
        return self._cap_usd - self.realized_usd - self._reserved_usd

    @property
    def compute_usd(self) -> float:
        return self._compute_usd

    @property
    def llm_usd(self) -> float:
        return self._llm_usd

    @property
    def data_reads(self) -> int:
        return self._data_reads

    def snapshot(self) -> dict[str, float | int]:
        return self.used().as_dict() | {"remaining_usd": self.remaining_usd}

    def used(self) -> DiscoverCostUsed:
        return DiscoverCostUsed(
            compute_usd=self._compute_usd,
            llm_usd=self._llm_usd,
            data_reads=self._data_reads,
            data_read_usd=self.data_read_usd_total,
            reserved_usd=self._reserved_usd,
            realized_usd=self.realized_usd,
            cap_usd=self._cap_usd,
        )

    def reserve(self, *, kind: CostKind, action: str, usd: float) -> BudgetReservation:
        amount = _non_negative(usd, "usd")
        if amount > self.remaining_usd:
            raise BudgetKill(
                attempted_action=action,
                requested_usd=amount,
                remaining_usd=self.remaining_usd,
            )
        self._reserved_usd += amount
        return BudgetReservation(kind=kind, action=action, usd=amount)

    def charge(self, reservation: BudgetReservation, *, realized_usd: float, data_reads: int = 0) -> None:
        if not isinstance(reservation, BudgetReservation):
            raise TypeError("reservation must be a BudgetReservation")
        realized = _non_negative(realized_usd, "realized_usd")
        reads = _non_negative_int(data_reads, "data_reads")
        self._reserved_usd -= reservation.usd
        extra = max(0.0, realized - reservation.usd)
        if extra > self.remaining_usd:
            self._reserved_usd += reservation.usd
            raise BudgetKill(
                attempted_action=reservation.action,
                requested_usd=realized,
                remaining_usd=self.remaining_usd + reservation.usd,
            )
        if reservation.kind == "compute":
            self._compute_usd += realized
        elif reservation.kind == "llm":
            self._llm_usd += realized
        elif reservation.kind == "data_read":
            self._data_reads += reads
            self._compute_usd += realized
        else:  # pragma: no cover - Literal guard for type checkers.
            raise ValueError(f"unknown cost kind {reservation.kind!r}")

    def charge_usage(
        self,
        reservation: BudgetReservation,
        *,
        compute_usd: float,
        llm_usd: float,
        data_reads: int,
    ) -> None:
        if not isinstance(reservation, BudgetReservation):
            raise TypeError("reservation must be a BudgetReservation")
        compute = _non_negative(compute_usd, "compute_usd")
        llm = _non_negative(llm_usd, "llm_usd")
        reads = _non_negative_int(data_reads, "data_reads")
        realized = compute + llm + reads * self._data_read_usd
        self._reserved_usd -= reservation.usd
        extra = max(0.0, realized - reservation.usd)
        if extra > self.remaining_usd:
            self._reserved_usd += reservation.usd
            raise BudgetKill(
                attempted_action=reservation.action,
                requested_usd=realized,
                remaining_usd=self.remaining_usd + reservation.usd,
            )
        self._compute_usd += compute
        self._llm_usd += llm
        self._data_reads += reads

    def charge_direct(
        self,
        *,
        kind: CostKind,
        action: str,
        realized_usd: float,
        data_reads: int = 0,
    ) -> None:
        reservation = self.reserve(kind=kind, action=action, usd=realized_usd)
        self.charge(reservation, realized_usd=realized_usd, data_reads=data_reads)


def _non_negative(value: float, label: str) -> float:
    if not isinstance(value, (int, float)):
        raise TypeError(f"{label} must be numeric")
    result = float(value)
    if result < 0.0:
        raise ValueError(f"{label} must be non-negative")
    return result


def _non_negative_int(value: int, label: str) -> int:
    if not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} must be a non-negative int")
    return value
