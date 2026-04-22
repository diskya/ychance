# §6.6 Sizing, Risk, Portfolio Construction

## Status
Initial hypothesis derived from §1 and §2. Nothing here is inherited from external risk frameworks. If a number below matches a number that appears in such a framework, it is coincidence; the number here is justified by the envelope and by the Validate distributions, not by convention.

## Envelope accounting

Let `E` = total operator envelope, $50K–$100K (see [README.md](README.md)). `E` is partitioned into:
- `E_cap` — capital available for live position-taking.
- `E_ops` — running operational cost (LLM inference, data feeds, compute, broker fees).
- `E_res` — reserve for tax accrual, drawdown cushion, and friction.

Partition ratios are pre-committed at methodology start and reviewed at M2a. Initial hypothesis (revisable): `E_cap ≈ 0.6·E`, `E_ops ≈ 0.25·E`, `E_res ≈ 0.15·E`. These numbers are not inherited; they are chosen to let the falsification clock ([08-falsification-clock.md](08-falsification-clock.md)) run for `T` months at the proposed Propose/Screen/Validate/Council frequency without exhausting `E`.

`E_ops` is tracked live. Overruns throttle Propose before they eat `E_cap`.

## Per-rule sizing

For a rule `R` with Validate output (a distribution of out-of-sample `U(R)`):

- Sizing is a function of the **full distribution**, not a point estimate. Initial functional form (hypothesis, revisable at M2a): the fraction of `E_cap` allocated to `R` is proportional to a lower-bound quantile of the predicted `U(R)` distribution, clamped by:
  - A per-rule **drawdown ceiling** `D_R` pre-committed before Graduate.
  - A **capital-at-risk cap** `C_R` derived from the predicted worst-case loss-per-unit-committed at a pre-committed quantile.
- The sizing function takes no input from the operator's judgment of the rule's type, horizon, or intuition of risk.

If the predicted distribution has excessive tail weight below zero (any quantile below a pre-committed level), size is zero regardless of mean — the rule paper-deploys instead of graduating.

## Portfolio construction

### Live-book correlation clamp

Let `ρ_ij` be the realized correlation between rule `i`'s and rule `j`'s live P&L over a rolling window.
- **Effective-independence** of the live book is measured, not asserted. Compute the correlation matrix across live rules, extract eigenvalues, and define `N_eff` as a monotone function of the eigenvalue spectrum (initial form: `(Σ λ_k)² / Σ λ_k²`).
- Pre-committed cap: `N_eff ≥ N_min`. If accepting a new Graduate would push `N_eff` below `N_min`, the new rule is queued, not rejected; the younger of any correlated live pair is the first to Retire when a correlation event triggers.

`N_min` is set from the `E_cap`/`D_R` relationship so that a drawdown in one effectively-independent cluster does not breach `E_cap`'s total drawdown ceiling. It is not set from convention.

### Total capital-at-risk cap

Sum of per-rule `C_R` across all live rules must not exceed a pre-committed fraction of `E_cap`. Initial hypothesis (revisable at M2a): `Σ C_R ≤ 0.5 · E_cap`. This caps the worst-case single-period loss from the whole live book.

### Cash as default

When the loop produces zero Graduate events, the default is cash. Cash is a first-class allocation, not a residual. No "something must be deployed" rule exists.

## Risk events and reactions

- **Per-rule drawdown breach**: rule is Retired per [03-discovery-loop.md](03-discovery-loop.md); its capital returns to `E_cap` after a cool-off period during which it is held as cash, not re-deployed.
- **Book-wide drawdown breach**: a pre-committed ceiling on total live book drawdown (initial hypothesis, revisable: 15% of `E_cap`). Breach triggers an automatic reduction of all live sizes by a pre-committed factor and a forced Council re-review of every live rule within `W` days. It does not trigger operator override — this is §7.
- **Correlation event**: when the correlation clamp is violated, the Retire rule in [03-discovery-loop.md](03-discovery-loop.md) applies. Operator does not choose which to keep.
- **Envelope overrun**: if `E_ops` is exhausted before the end of a cycle, Propose halts new candidate generation; Council cache-hits still execute. No live rule is touched on a pure `E_ops` event.

## Tax

Tax liability is estimated per realized gain using the operator's jurisdictional bracket (§2). Estimated tax is accrued into `E_res`. A rule's `U(R)` is computed **after** expected tax; this is a §1 requirement, not a post-hoc adjustment.

The tax model is a parametric hypothesis. At M2a, the realized-vs-estimated tax on closed positions is compared, and the model is recalibrated.

## Position mechanics

- Long equity, ETFs, and retail-accessible listed vehicles are assumed available.
- Short, options, futures, and margin are available **only if** the operator's broker account tier admits them **and** the methodology's own Validate+Council gate has cleared a rule that uses them. No capability is assumed without both conditions. A rule that requires an unavailable capability is Retired as infeasible — not "parked for later."
- Execution latency is modeled from Paper-deploy's realized latency, not assumed to be zero.

## What the operator does here

- Sets `E` and re-declares its sub-partition ratios at methodology start and at each M2a.
- Approves operational spend commitments (new data vendor, model-tier change) when they affect `E_ops`.
- Holds the kill switch (see [07-operator-workflow.md](07-operator-workflow.md)).

Operator does **not** size individual rules, does not override the correlation clamp, does not reshuffle capital across rules between Retire/Graduate events, does not increase a rule's size because it "looks right," does not decrease a rule's size because it "looks scary."

## Revision triggers

- Scheduled: every M2a — partition ratios, sizing function, drawdown ceilings, correlation clamp, total capital-at-risk cap.
- Unscheduled: book-wide drawdown breach; envelope-ratio realized deviation from planned exceeds a pre-committed threshold; tax-model calibration error exceeds pre-committed bound.
