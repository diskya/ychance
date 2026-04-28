# Methodology — Index

Read [../Objective.md](../Objective.md) first; §0 overrides anything here. Every artifact in this directory is an initial hypothesis subject to M2a revision.

**Scope (v3.0):** corpus of council-approved, replication-tested Patterns. No trading.

| File | Scope |
|---|---|
| [01-architecture.md](01-architecture.md) | Stages and invariants |
| [02-data-and-representation.md](02-data-and-representation.md) | Ingest + raw store + feature contract |
| [03-discovery-loop.md](03-discovery-loop.md) | Discover stage — the core |
| [04-empirical-test.md](04-empirical-test.md) | Replication on held-out windows |
| [05-council.md](05-council.md) | Cross-family review with measured independence |
| [07-operator-workflow.md](07-operator-workflow.md) | Weekly + M2a routines |
| [08-falsification-clock.md](08-falsification-clock.md) | M8 budget, success, relax, abandon |
| [09-audit.md](09-audit.md) | Audit trail schema |

## Notation

- **Pattern** `P = (spec_ref, assertion, scope, observation_window, replication_protocol)` — a falsifiable claim. Hash-addressed by `pattern_id`.
- **Spec** — feature-family definition, content-addressed by `spec_id`.
- **Assertion** — computable predicate over a spec's output (e.g., `quantile_ge(p=0.9, threshold=X)`).
- **Replication** — recomputing the assertion on a window the Pattern was not derived from.
- `E` — total envelope. `$B` — clock spend budget, subset of `E`. `T` — clock duration.

To run a weekly cycle: read [07-operator-workflow.md](07-operator-workflow.md). The other files exist so you can audit, not re-engineer.
