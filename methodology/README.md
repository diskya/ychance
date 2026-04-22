# Methodology — Index

This tree is the §6 deliverable mandated by [../Objective.md](../Objective.md). Read the Objective first; it is the constitution, and nothing here overrides it.

## Status

Every artifact here is an **initial hypothesis**. Nothing in this directory is a truth claim about markets, about how edges work, or about the "right" way to do anything. The methodology operates on the premise that its own configuration is wrong in specific, measurable ways and must be revised under the M2a cadence.

## Files

| File | §6 item |
|---|---|
| [01-architecture.md](01-architecture.md) | Pipeline stages, interfaces, invariants |
| [02-data-and-representation.md](02-data-and-representation.md) | What gets ingested and how it becomes features |
| [03-discovery-loop.md](03-discovery-loop.md) | How candidate rules are proposed, tested, retired — **core** |
| [04-validation.md](04-validation.md) | Statistical + out-of-sample testing regime |
| [05-council.md](05-council.md) | Cross-family adversarial review protocol |
| [06-sizing-risk-portfolio.md](06-sizing-risk-portfolio.md) | How capital is allocated across live rules |
| [07-operator-workflow.md](07-operator-workflow.md) | Daily / weekly / quarterly routine; degraded mode |
| [08-falsification-clock.md](08-falsification-clock.md) | M8 budget, success criterion, relax path, abandon path |
| [09-audit.md](09-audit.md) | Append-only log schema and retention |

## §0 discipline — re-stated here because it is load-bearing

- No design choice in this tree is imported from an external finance framework, textbook, practitioner tradition, or named strategy. Any such content that appears is a defect and should be removed on sight during review.
- Names in this tree refer to **functions** (Ingest, Propose, Screen, Retire, etc.), not to inherited category schemas.
- "Classical categories" of edge are neither embraced nor forbidden; they are simply not the vocabulary the methodology uses. A rule that coincidentally resembles a classical category survives or dies on its grounding and its out-of-sample utility, not on the resemblance.
- The operator's job is to execute the loop, not to seed it with preferred edges. See [../Objective.md §7](../Objective.md).

## Envelope

Total operator envelope `E` = **$50K–$100K**, covering capital deployed *plus* all operating cost (LLM inference, data feeds, compute, broker fees, tax, and friction). Every subsystem is budgeted against `E`, not against a separate infrastructure pool. The falsification-clock budget `$B` in [08-falsification-clock.md](08-falsification-clock.md) is a subset of `E`.

## Notation used across files

- `R = (C, A, H, X)` — a **rule**: context predicate `C`, action `A`, horizon `H`, exit condition `X`.
- `G(R)` — **grounding**: the empirical signature in the data that `R` claims to exploit.
- `U(R)` — **utility**: risk-adjusted, post-cost, post-tax return on capital committed to `R`, per §1. The functional form of `U` is itself a hypothesis under M6 (see [04-validation.md](04-validation.md)).
- `E` — total envelope, above.
- `$B` — M8 clock spend budget, subset of `E`.
- `T` — M8 clock duration in months (12–24 initially).

## What you should do as operator on day one

Read [07-operator-workflow.md](07-operator-workflow.md). It is the only file required to run a daily cycle. The other files exist so you can audit, not so you can re-engineer.
