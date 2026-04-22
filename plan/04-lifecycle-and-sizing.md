# Phases 6–7 — Rule Lifecycle + Sizing + Portfolio

**Goal**: Paper-deploy, Observe, Graduate/Retire state machine ([../methodology/03-discovery-loop.md](../methodology/03-discovery-loop.md)), and sizing + portfolio construction ([../methodology/06-sizing-risk-portfolio.md](../methodology/06-sizing-risk-portfolio.md)).

## Dependencies
- [03-council.md](03-council.md) is complete. Approved rules need a place to go.
- Phase 0 ([00-operator-decisions.md](00-operator-decisions.md)) envelope pools (`clock.ops_budget_usd`, `cutover.ops_budget_usd`, `real_capital.target_E_cap_usd`, `sim_notional.E_cap_usd`) and drawdown ceilings are fixed.

## Parallelism within this phase
- 6.1 must come first (Paper-deploy is the target of Council approvals).
- 6.2 and 6.3 can run in parallel after 6.1.
- 6.4 independent; can be slotted anywhere.
- 7.1, 7.2, 7.3 are independent and can parallelize.

---

## 6.1 Paper-deploy executor — **[M]**

> Implement `paper/` that runs a rule in paper-trading mode against the live data feed with realistic friction: commissions, bid/ask spreads, borrow cost (if short), tax accrual. **Must use the same data feed and latency profile as Execute** (from [05-execution.md](05-execution.md)) — reuse the access layer, the market-data adapter, and (critically) the same `friction/` module. Emits per-tick and per-firing records to audit per [../methodology/09-audit.md](../methodology/09-audit.md) §"Paper-deploy records".
>
> Paper-deploy duration per rule is pre-committed (config-driven), sized so Observe's distribution-match test has statistical power. Spend attributable to this rule (LLM cost, data reads, compute) is tracked against the per-rule clock (6.4).
>
> During the sim clock (every rule at `live_fraction = 0`; see [README.md](README.md) "Operating mode: Routing, not modes"), both Paper-deploy and Execute route exclusively through the sim route and share the same `friction/` module — the difference between them is **role**, not realism: Paper-deploy runs at fractional notional size post-Council to test Observe's distribution match; Execute runs at full notional size post-Graduate as the committed tier. During Phase 11, Execute additionally routes a `live_fraction` share to the real broker; Paper-deploy remains sim-only regardless of phase (Paper-deploy's purpose is pre-commitment testing, which must be free of real-money exposure).

## 6.2 Observe stage — **[M]**

> Implement `observe/` per [../methodology/03-discovery-loop.md](../methodology/03-discovery-loop.md) step 7 and [../methodology/09-audit.md](../methodology/09-audit.md) §"Observe records". Compares realized paper/live P&L distribution to the predicted `U(R)` distribution from Validate. Computes:
>
> - Distribution-match statistic at a pre-committed level.
> - Correlation of this rule's P&L with every other live rule over a rolling window.
> - Regime-tag-partitioned performance using regime tags from [02-discovery-loop.md](02-discovery-loop.md) §4.2.
>
> Observe never edits predictions. Append-only. When correlation or regime-tag stats cross pre-committed thresholds, Observe emits a regime-change flag consumed by Council's cache invalidation (see [03-council.md](03-council.md) failure notes).

## 6.3 Graduate + Retire state machine — **[M]**

> Implement `lifecycle/` that tracks every rule through states:
>
> ```
> proposed → screened → validated → council_approved
>          → paper_deployed → graduated → retired
> ```
>
> Transitions are triggered by the outputs of other stages. All Retire triggers from [../methodology/03-discovery-loop.md](../methodology/03-discovery-loop.md) §8 must fire **automatically** without operator action:
>
> - Live drawdown breach of per-rule ceiling.
> - Observe distribution-match rejection over a rolling window.
> - Per-rule clock expiry (see 6.4).
> - Correlation-clamp breach against another live rule (younger retires).
> - Council re-review failure.
>
> Graduate requires an **operator ack** — but the ack is a gate check (see [../methodology/07-operator-workflow.md](../methodology/07-operator-workflow.md)), not a re-evaluation. Implement as a queue the operator pane (Phase 9) reads; operator approves or the rule stays queued. No override path for Retire — that is a §7 discipline requirement.

## 6.4 Per-rule clock — **[S]**

> Each rule is born with `T_R` (testing-budget duration) and `$B_R` (testing-budget spend) budgets at Propose time. Implement `rule_clock/` that:
>
> - Accrues spend per rule (compute, LLM, data reads attributable to that rule) from stage cost annotations.
> - Fires Retire when either budget is exhausted without a Graduate event — regardless of near-misses.
> - Emits per-rule clock records so the operator quarterly pane (Phase 9) can show remaining budget per live rule.
>
> Default `T_R` and `$B_R` are config-driven and proportional to `T` and `$B`. Initial guess (revisable): `T_R = T/10`, `$B_R = $B / (expected live-rule headcount × 2)`. Document these as hypotheses.

---

## 7.1 Sizing function — **[M]**

> Implement `sizing/` per [../methodology/06-sizing-risk-portfolio.md](../methodology/06-sizing-risk-portfolio.md). Input: rule's Validate `U(R)` distribution, per-rule drawdown ceiling `D_R`, current `E_cap` value, correlation with live rules. Output: fractional size allocation or zero.
>
> `E_cap` resolves at execution time from config: during the sim clock it reads `sim_notional.E_cap_usd`; post-cutover it reads `real_capital.target_E_cap_usd` (or its realized running balance after drawdowns). Sizing is agnostic to which pool it reads — it just consumes a scalar. The routing layer in [05-execution.md](05-execution.md) §8.2 is what translates a sized intent into per-route sub-intents via `live_fraction`.
>
> - Sizing is a function of the **full distribution**, not a point estimate.
> - Initial functional form (revisable at M2a): fraction ∝ lower-bound quantile of predicted `U(R)` distribution, clamped by `D_R` and by the capital-at-risk cap `C_R`.
> - If any quantile below a pre-committed level is negative, size = 0 — rule paper-deploys instead of graduating.
> - Sizing function takes **no operator input** about rule type, horizon feel, or intuition.

## 7.2 Correlation clamp + effective independence — **[M]**

> Implement `portfolio/` that:
>
> - Computes `N_eff = (Σ λ_k)² / Σ λ_k²` over the live-rule P&L correlation matrix eigenvalue spectrum.
> - Enforces `N_eff ≥ N_min` (config-driven, with `N_min` set from `E_cap` and drawdown ceilings, not from convention).
> - On correlation event (pairwise correlation exceeds clamp over a rolling window), emits a Retire trigger for the younger of the correlated pair — consumed by `lifecycle/` (6.3).
> - On new Graduate candidate that would push `N_eff` below `N_min`, queues the candidate rather than rejecting it; queued candidate retries each Retire event.

## 7.3 Book-wide drawdown monitor — **[S]**

> Implement `book_monitor/`:
>
> - Tracks book-wide drawdown in live-book realized P&L.
> - On breach of pre-committed ceiling (initial hypothesis: 15% of `E_cap`, revisable at M2a), triggers:
>   1. Automatic size reduction of every live rule by a pre-committed factor.
>   2. Forced Council re-review of every live rule within `W` days.
> - **No operator intervention**. This is §7 discipline — a drawdown breach is a pipeline-level event, not a human-judgment event.
