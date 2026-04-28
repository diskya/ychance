# Implementation Plan — Index

Pre-clock build sequence for the system in [../methodology/](../methodology/). One-time: M2a kicks in once the system is live.

**Scope (v3.0):** build a frontier-AI pattern-discovery system: Ingest → Represent → Discover → EmpiricalTest → Council → Archive. No trading, sizing, or execution. Corpus is the artifact.

**Scope ladder.** Build the **Pattern Catalog** first. Mechanism hypotheses and open-ended research surfacing are downstream extensions, deliberately deferred.

## Files

| File | Scope |
|---|---|
| [00-operator-decisions.md](00-operator-decisions.md) | Phase 0 — config decisions before any code |
| [02-discovery-loop.md](02-discovery-loop.md) | Phase 3 — Pattern object, Discover (tool-using agent), EmpiricalTest, Originality |
| [03-council.md](03-council.md) | Phase 4 — Council with measured independence |
| [06-operator-ux.md](06-operator-ux.md) | Phase 5 — weekly pane, M2a pane, bias log, archive browser |

(Phases 1–2 foundation work is complete. See [../STATUS.md](../STATUS.md) for current module state. Numbering preserves continuity with what was built; deleted phases are gone, not renumbered.)

Task labels: **[S]** small (paste prompt as-is), **[M]** medium (one or two sessions), **[L]** large (research thread first, then code).

## Sequencing

Serial spine: [00](00-operator-decisions.md) → [02](02-discovery-loop.md) → [03](03-council.md) → [06](06-operator-ux.md). The clock starts only when the loop produces an end-to-end archived Pattern from real data with full audit chain intact.

## Rough effort estimates (solo, part-time)

| Phase | Estimate |
|---|---|
| 0 | already complete (1 trim of `config/envelope.yaml` pending) |
| 3 (Discover redesign) | 4–6 weeks — research thread on the agent loop concentrates the time |
| 4 (Council rebuild) | 2–3 weeks |
| 5 (UX) | 1–2 weeks |

**~6–10 weeks** from current state to the clock-start gate.
