# §6.4 Validation Protocol

## Status
Initial hypothesis under M6. **The validation protocol is itself a hypothesis subject to meta-validation.** A protocol stays in force only as long as it out-predicts challengers on the meta-validation task defined below.

## What Validate must produce

For each rule `R` admitted by Screen, Validate emits:
1. An **out-of-sample utility distribution**: the empirical distribution of `U(R)` realized across held-out windows, constructed under the splitting rule below.
2. A **challenger dominance report**: per-challenger statistics comparing `R` to each challenger in the challenger set (next section). Dominance is measured in utility, not in mean return, not in risk-adjusted return alone, not in any ratio inherited from an external framework.
3. A **robustness profile**: performance of `R` across cross-validation folds, perturbations of `C`'s thresholds, and perturbations of feature definitions feeding `C`.
4. A **data-reuse audit**: a proof that no data point used in any Screen window for `R` appears in any Validate window for `R`, derived from lineage in the raw store.

No Validate output is a scalar. A rule is described by distributions; Council reads distributions, not point estimates.

## Neutral challengers, not privileged floors

Per M4, no comparison object is a privileged floor. Each rule is compared to a **challenger set** whose members must pass the same gate by the same metric. The initial challenger set (itself a hypothesis):

- **Inactive**: no position is opened. Trivial but honest.
- **Context-removed `R`**: the same `(A, H, X)` with the context predicate removed as the entry selector. Tests whether the selector adds utility beyond the rule's mechanics.
- **Context-randomized `R`**: the same `(A, H, X)` with `C` replaced by a deterministic sample matched to `R`'s realized firing count. Tests whether `C` selects informative times.
- **Input-permuted `R`**: `R` evaluated on feature tensors with the time index shuffled within each feature family feeding `C`. Tests whether the rule depends on the actual temporal structure of its inputs rather than their marginal distribution.

A rule passes Validate iff it dominates every challenger on a pre-committed majority of the split partitions — where "dominate" means the rule's utility-distribution stochastically dominates the challenger's at a pre-committed order. Stochastic dominance is used instead of a point statistic because a point statistic smuggles in assumptions about the utility functional form.

## Splitting rule

Time-respecting splits only. A window used for any input (feature fit, rule selection, threshold tuning, any decision that shaped `R`) may not reappear in any held-out window. **Gaps** between train and held-out windows are sized to the longest dependency in any feature family that `R` reads — because otherwise a feature computed at a point in the held-out window can leak training information.

Nested splits: an outer fold to estimate out-of-sample utility distribution; an inner fold inside each outer train half for any threshold or feature-weight tuning. No tuning at all happens on outer holdout.

**Validation partitions.** Held-out windows may additionally be partitioned by AI-proposed tags derived from this methodology's own observable inputs, not from external labels or named states. A rule must dominate challengers in the majority of active partition tags, not only in aggregate. Partition tags are re-derived every M2a.

## Utility functional form

`U(R)` captures risk-adjusted, post-cost, post-tax return on capital committed to `R` per §1. The exact functional form is a hypothesis:
- Initial form: expected log-growth of wealth committed to `R` net of realistic frictions (commissions, spreads, borrow cost where applicable, tax at the operator's bracket), penalized by a drawdown-sensitive term.
- The penalty, the frictions, and the tax model are parametric; each is a hypothesis revised at M2a.
- The rank-order of rules under competing utility functionals is reported alongside the primary `U`. If two functionals give consistently different rankings, Council is shown both, and the decision rule requires approval under the primary only — but the disagreement is flagged in Audit.

Utility is computed on live-realistic assumptions only. Paper frictions that don't match retail reality are a defect.

## Meta-validation (M6 implementation)

A validation protocol is a parameter. Every M2a:

1. The current protocol `P_0` and at least one challenger `P_1` (AI-produced) each score the set of rules graduated, retired, or alive since the last meta-validation.
2. Score the protocol by how well its Validate-time `U(R)` *predicted* the realized-in-live `U(R)`. Prediction is measured by calibration (do realized `U` values fall in the predicted quantile frequencies?) and by discrimination (do rules predicted to have higher `U` actually have higher realized `U`?).
3. If `P_1` strictly dominates `P_0` on both calibration and discrimination across the graduated-rule set, `P_1` replaces `P_0` at the next cycle. Partial dominance triggers a tie-break via Council.
4. Neither calibration nor discrimination is an inherited number; both are defined operationally on this methodology's own rule history.

Until enough rules have been graduated and lived long enough to populate the meta-validation set, `P_0` is frozen and this section's decision rule is a null-op.

## What Validate does not do

- **No convention-derived significance threshold.** Any threshold is pre-committed and lives in the config artifact; it can be changed at M2a with a rationale.
- **No reporting of single-number performance stats.** A rule is not summarized by a scalar. If Council asks for a scalar, the answer is "report the distribution."
- **No in-sample tuning.** Any in-sample optimization of `R`'s parameters happens within Propose's candidate-generation budget, before the rule reaches Validate.

## Revision triggers

- Scheduled: every M2a, via the meta-validation procedure above.
- Unscheduled: a systematic mismatch between Validate-predicted `U(R)` and Observe-realized `U(R)` across many rules is a falsification trigger; Council convenes out-of-cycle.
