# §6.3 Discovery Loop — Core Deliverable

## Status
Initial hypothesis under M1–M2. Every decision rule in this file is an initial setting with a named revision trigger. The goal of the loop is to generate candidate rules `R = (C, A, H, X)` and let empirical evidence — not inherited category schemas — decide which survive.

## Object of the loop

A **rule** is:
- `C` — **context predicate**: a computable boolean over current feature values and raw-store state.
- `A` — **action**: an order or position intent (long, short-if-available, cash, sized by [06-sizing-risk-portfolio.md](06-sizing-risk-portfolio.md)).
- `H` — **horizon**: maximum holding period, discovered per rule — not a global parameter. `H` is part of the rule, not a pipeline setting (M5).
- `X` — **exit condition**: any computable predicate whose truth closes the position before `H` elapses.

Every rule has a **grounding** `G(R)` — a concrete, computable empirical signature in the data the rule claims to exploit. A rule without a grounding is rejected by Propose before emission.

## The loop

```
Propose → Originality filter → Screen → Validate → Council
      → Paper-deploy → Observe → Graduate → Execute → Observe
                                      ↘ Retire (at any stage)
```

Each step is a stage in [01-architecture.md](01-architecture.md). This file specifies the decision rules *between* stages.

### 1. Propose

A frontier model receives:
- The current anti-pattern list (below).
- A structured slice of recent feature tensors and raw entries served via the access layer ([02-data-and-representation.md](02-data-and-representation.md)).
- A compact summary of currently live rules' groundings, so the model is biased away from proposing duplicates.

The model emits up to `N_max` candidate rules per Propose invocation. `N_max` is set to exhaust ≤ a pre-committed fraction of the weekly `$B` allocation, never more.

Each candidate includes `(C, A, H, X, G(R))` in an executable, typed form. Free-text rationale is allowed but never used as a gate — gates operate on `G(R)` and the Validate statistics only.

### 2. Originality filter

The filter rejects a candidate if `G(R)` is reducible to an entry in the **anti-pattern list**. The anti-pattern list is:
- An AI-produced vocabulary of **lazy primitives** — groundings so small, so common, and so well-explored that any candidate reducing to one of them carries negligible expected surprise value.
- Revised at every M2a. An entry earns a slot iff it empirically predicts that rules reducing to it have ≤ baseline out-of-sample utility after Screen/Validate across the last `K` cycles.
- Bounded in size (target ≤ 50 entries) to prevent it from growing into a full taxonomy.

**Acknowledged tension (M1 paradox).** The anti-pattern list is itself a category system, and §0 forbids pre-specified category systems. The defense: this list is (a) derived from measured out-of-sample statistics in *this* methodology's history, not inherited from external tradition; (b) mutable each cycle; (c) purely subtractive — it never suggests what to propose, only what is too stale to bother testing. If meta-validation finds the list does not improve expected utility per `$B` spent, it is emptied.

### 3. Screen

A cheap held-out evaluation with a hard per-candidate dollar cap (compute + data reads). Passes iff:
- Out-of-sample signal-to-noise exceeds a pre-committed threshold on a Screen-only window.
- Turnover implied by `C`-firings is consistent with retail execution cost (estimated, then confirmed in Paper-deploy).
- `G(R)` is reproducible on the Screen window — the signature the rule claims to exploit is actually present.

Screen thresholds are themselves parameters set by meta-validation ([04-validation.md](04-validation.md)), not by human intuition about "reasonable" numbers.

### 4. Validate

Full protocol per [04-validation.md](04-validation.md). Outputs a distribution of out-of-sample `U(R)` and dominance statistics vs. competitors.

### 5. Council

Per [05-council.md](05-council.md). Requires ≥2 independent approvals. Council sees the rule, grounding, Validate outputs, and sampled raw-data windows — not the free-text rationale from Propose, which is deliberately withheld to prevent rationale contagion across stages.

### 6. Paper-deploy

Fractional-size live paper trading on the same data feed and latency profile as Execute. Duration is pre-committed per rule, sized so Observe's distribution-match test has adequate statistical power. Paper-deploy cost (LLM calls, data) is billed against `$B`.

### 7. Observe → Graduate

Observe compares realized Paper-deploy P&L to the distribution Validate predicted. Graduate iff:
- The realized distribution is not rejected at a pre-committed level against the predicted distribution.
- Drawdown during Paper-deploy stayed below the rule's pre-committed drawdown ceiling.
- Correlation of Paper-deploy P&L with every live rule is below the portfolio correlation clamp ([06-sizing-risk-portfolio.md](06-sizing-risk-portfolio.md)).

### 8. Retire

A rule is retired on **any** of:
- Live drawdown breach of its pre-committed ceiling.
- Observe distribution-match rejected at the pre-committed level over a rolling window.
- Per-rule clock expiry: each rule is born with a testing-budget `T_R` and a spend-budget `$B_R`; when either is exhausted without the rule generating positive cumulative `U(R)` at the pre-committed level, it is retired regardless of near-misses.
- Live-P&L correlation with another live rule exceeds the correlation clamp for a sustained window — the younger rule is retired.
- Council re-review (scheduled or triggered) fails to achieve independent re-approval.

Retire is **monotone** per [01-architecture.md](01-architecture.md). A retired rule is not re-tested casually; re-entry requires a new Propose with materially different grounding.

## Rules about rules

### No pre-ranked edge list
The operator must not maintain, and the Propose context must not include, any ranked list of "edges we are looking for." See §4 and §7 of [../Objective.md](../Objective.md). This includes lists formulated as "things to avoid" if those lists are positively correlated with a class of groundings the operator wants to avoid. The anti-pattern list defends against this by being (a) data-derived and (b) emptied whenever meta-validation rejects it.

### No-trade is a valid output
A Propose cycle may produce zero candidates. Screen may reject all candidates. Council may refuse to approve any survivor. On all such outcomes, **no human fallback runs**. The operator does not substitute "their own view" for an empty pipeline. Empty-pipeline cycles are logged and Audit-reviewed; their frequency is itself a meta-validation signal.

### Unfamiliarity is not a gate
If a Validate-and-Council-approved rule has a grounding the operator does not understand, this is expected. Vetoing on unfamiliarity is bias re-insertion (§7). The operator's approval of a Graduate event is a **gate check** — "were the pipeline's gates actually fired correctly?" — not a re-evaluation of the edge.

## Cost discipline

The loop is budget-bounded. Frontier-model calls are gated behind cheap filters at every opportunity:
- Propose may be two-stage: a cheaper model drafts candidates; a frontier model adjudicates only those whose cheap-model score exceeds a threshold.
- Screen precedes Validate, Validate precedes Council. Each successive stage is more expensive and sees fewer survivors.
- Council cache: identical `(rule, Validate output)` pairs are cached; re-query only on rule update, regime change flag, or scheduled re-review.

If realized cost per Graduate event trends above its budget, Propose throttles before the operator is asked for more money — the loop slows, it does not silently eat the envelope.

## Per-cycle decision summary (what the operator sees)

At the end of each cycle, the log contains, for each candidate:
- The stage it reached.
- The gate it failed (if any), with the statistic that failed.
- The audit record hash chain back to its inputs.

No rule "almost passed." Either it passed every gate or it was rejected at a named gate. "Almost" is not a category.

## Revision triggers

- Scheduled: M2a reviews the originality filter, per-stage thresholds, per-rule clocks, and the no-trade frequency. Each can be changed as a unit; ad-hoc mid-cycle tuning is not allowed.
- Unscheduled: if the loop produces zero Graduate events over a pre-committed window (itself a falsification signal), the operator invokes M8 rather than editing this file.
