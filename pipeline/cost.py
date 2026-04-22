"""Per-invocation cost accounting for a :class:`Stage`.

Methodology §6.1: each stage declares a cost ceiling (LLM, compute, data)
that it must not exceed per unit of work. This module holds the
dataclasses and the exception that ``Stage.run`` raises when the ceiling
is breached. Enforcement lives in :class:`pipeline.stage.StageContext`.
"""

from __future__ import annotations

from dataclasses import dataclass


class CostCeilingExceeded(RuntimeError):
    """Raised when a Stage invocation exceeds one of its declared ceilings."""


@dataclass(frozen=True)
class CostCeiling:
    """Per-invocation upper bounds. A ceiling of 0 means the stage must not
    incur that cost type at all. ``compute_usd`` and ``llm_usd`` are dollar
    estimates charged by the stage; ``data_reads`` is a raw count of reads
    the stage issues against its AccessLayer (AccessLayer owns the
    per-cycle budget; this is the per-invocation bound).
    """

    compute_usd: float = 0.0
    llm_usd: float = 0.0
    data_reads: int = 0


@dataclass
class CostUsage:
    compute_usd: float = 0.0
    llm_usd: float = 0.0
    data_reads: int = 0
