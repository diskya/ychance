# §6.1 Architecture

## Status
Initial hypothesis under M2. Subject to scheduled revision at M2a. The names below are chosen for function. Where a name collides with an inherited term, the collision is coincidental; the invariants are what bind.

## Shape
A directed acyclic graph of **stages**. Each stage is a typed, versioned node with exactly:
- A set of input artifacts (content-addressed).
- A set of output artifacts (content-addressed).
- An invariant — a measurable property its outputs must satisfy.
- A cost ceiling (LLM, compute, data) that the stage must not exceed per unit of work.

A stage must not read any un-logged input. Every input is either the output of another stage or an artifact in the append-only raw store (see [02-data-and-representation.md](02-data-and-representation.md)).

## Stages

### Ingest
- **In**: raw data from §2-admissible sources (retail-accessible).
- **Out**: append-only, provenance-tagged, content-addressed raw store entries.
- **Invariant**: an entry's hash equals the hash of its bytes; provenance (source, fetch time, vendor-supplied timestamp) is present; no overwrite.

### Represent
- **In**: raw store entries; a **feature-family spec** emitted by Propose (features are AI proposals under M3).
- **Out**: feature tensors keyed by entity and time, lineage-tracked back to specific raw entries and the spec version.
- **Invariant**: recomputing from lineage reproduces byte-identical outputs.

### Propose
- **In**: (a) structured slices of recent feature tensors and raw store entries; (b) the current **anti-pattern list** (see [03-discovery-loop.md](03-discovery-loop.md)); (c) the current live-rule book.
- **Out**: candidate rules `R = (C, A, H, X)` each with an explicit **grounding** `G(R)` — an empirical signature claimed to be exploited.
- **Invariant**: every proposed rule has executable `C`, `A`, `X`; `G(R)` is reducible to a computable statistic over the raw store.

### Screen
- **In**: candidate rules from Propose.
- **Out**: candidates that pass a cheap held-out evaluation (pass/fail + statistics).
- **Invariant**: Screen uses a disjoint time window from any window used by Validate; Screen spend per candidate is bounded to a hard dollar cap.

### Validate
- **In**: Screen survivors.
- **Out**: per-rule validation report (per [04-validation.md](04-validation.md)) with a distribution of out-of-sample utility, competitor comparison, and robustness checks.
- **Invariant**: no data point used in any Screen window for this rule appears in any Validate window.

### Council
- **In**: Validate outputs + grounding + sampled raw-data slices.
- **Out**: votes and written rationales from ≥2 independent vendor families per [05-council.md](05-council.md); a **deploy decision** iff ≥2 independent approvals.
- **Invariant**: a Council decision is reproducible from the logged inputs and the decision rule; rationales are stored verbatim.

### Paper-deploy
- **In**: Council-approved rules.
- **Out**: a live paper-trading instance with fractional sizing per [06-sizing-risk-portfolio.md](06-sizing-risk-portfolio.md), emitting a time-series of realized outcomes.
- **Invariant**: paper-trading reads the same data feed as Execute, including the same latency characteristics, so realized paper outcomes are comparable to live outcomes.

### Observe
- **In**: realized outcomes from Paper-deploy and Execute.
- **Out**: distribution-match statistics (realized vs. predicted), correlation of this rule's P&L with other live rules, drawdown metrics.
- **Invariant**: Observe never edits predictions; it only compares realized to the frozen Validate distribution.

### Graduate
- **In**: Paper-deploy outcomes that pass the match criterion.
- **Out**: a live-capital deployment instance sized per [06-sizing-risk-portfolio.md](06-sizing-risk-portfolio.md).
- **Invariant**: graduation requires that Observe reports distribution-match above a pre-committed threshold over a pre-committed paper-trading duration.

### Execute
- **In**: graduated rules.
- **Out**: broker orders and fills.
- **Invariant**: every order references exactly one rule's current `A` under `C` evaluated at order time; every fill is logged; no order bypasses the rule.

### Retire
- **In**: any live or paper-deploy rule that breaches a retirement trigger (drawdown, Observe distribution mismatch, per-rule clock expiry, Council re-review failure).
- **Out**: a final Retire record; open positions closed per `X` or an explicit retirement exit policy.
- **Invariant**: retirement is monotone — once retired, a rule cannot re-enter live without new Propose/Screen/Validate/Council passage.

### Audit
- Spans all other stages. Writes append-only JSON records per [09-audit.md](09-audit.md).
- **Invariant**: for every state transition in every other stage, exactly one Audit record exists.

### Review (M2a)
- **In**: Audit records since last Review; Observe statistics; the current architecture.
- **Out**: a proposed architecture diff, red-teamed by a disjoint Council instance, executed or rejected with rationale.
- **Invariant**: architecture is frozen between Reviews; out-of-cycle changes require a documented trigger event (drawdown breach, M8 relax path, or kill-switch restart).

## Hard cross-stage invariants

1. **Cost gating.** Frontier-model calls are gated behind cheaper-model or purely-statistical filters whenever such a filter exists. This is enforced by per-stage cost ceilings, not by operator discretion. Rationale: `$B` envelope pressure (see [08-falsification-clock.md](08-falsification-clock.md)).
2. **No retroactive reads.** A stage's output at time `t` must be reproducible from inputs available at `t`. Backfilling a feature spec invalidates all downstream outputs and forces re-run.
3. **Single kill switch.** Execute obeys an external operator kill signal; when set, Execute refuses new orders and calls `X` on live positions. Paper-deploy and upstream stages continue so Retire still resolves gracefully.
4. **Degraded mode.** If the operator heartbeat is absent for N days (see [07-operator-workflow.md](07-operator-workflow.md)), Execute auto-closes and Paper-deploy/Graduate halt until operator returns and acknowledges the audit gap.

## Non-stages (deliberately absent)

- No "model zoo" or "factor library." Persisting such an object across M2a cycles would become a taxonomy (M1).
- No separate "research" stage distinct from Propose. A distinction between "research" and "discovery" would reintroduce a human-curated intermediate category.
- No fixed universe definition. The universe a rule operates on is part of `C`.

## Revision triggers
- Scheduled: every M2a.
- Unscheduled: drawdown breach, M8 relax path invocation, council failure to reach independence threshold ([05-council.md](05-council.md)), or per-rule clock systematically under-predicting retirements.
