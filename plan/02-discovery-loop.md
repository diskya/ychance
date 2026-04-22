# Phases 3–4 — Discovery Loop + Validation

**Goal**: the front half of the loop ([../methodology/03-discovery-loop.md](../methodology/03-discovery-loop.md)) — Propose, Originality filter, Screen — and the statistical core ([../methodology/04-validation.md](../methodology/04-validation.md)) — Validate + meta-validation. This is where build time concentrates; research threads matter here.

## Dependencies
- [01-foundation.md](01-foundation.md) is complete. Raw store, audit log, access layer, stage shell, feature runner are all live and tested.

## Parallelism within this phase
- 3.1 must come first.
- 3.2 and 3.3 each need a research thread; those threads can run in parallel.
- 3.4 depends on 3.1.
- 4.1 needs a research thread; it can run in parallel with 3.2/3.3.
- 4.2 is independent; can be slotted anywhere after 3.1.
- 4.3 (meta-validation) is deferred until rules exist — Phase 11+.

---

## 3.1 Rule object + executable `(C, A, H, X)` + grounding `G(R)` — **[M]**

> Read [../methodology/03-discovery-loop.md](../methodology/03-discovery-loop.md). Define `Rule` as `(context_predicate, action, horizon, exit_condition, grounding)` where each component is serializable, hash-addressable, and executable over feature tensors. Build:
>
> - **Predicate DSL**: boolean combinations of feature comparisons and windowed statistics. No free-text predicates.
> - **Action DSL**: long / short / cash + size multiplier. Size multiplier is a relative figure; absolute sizing is owned by [04-lifecycle-and-sizing.md](04-lifecycle-and-sizing.md).
> - **Exit DSL**: predicate over time-since-entry, PnL, or `C` no longer holding.
> - **Grounding schema**: a computable statistic over the raw store, expressible as a feature-spec reference plus an assertion about its distribution.
>
> Provide `Rule.evaluate(t)` and `Rule.simulate(window)`. The simulate method is what Screen and Validate will call. Hash-address every rule object canonically so council caches (Phase 5) can work.

---

## 3.2 Propose stage (two-phase LLM) — **[L]**

### Research thread prompt

> I am building the Propose stage of a discovery loop described in [../methodology/03-discovery-loop.md](../methodology/03-discovery-loop.md). The stage receives structured data slices, the current anti-pattern list, and live-rule groundings, and emits candidate rules `(C, A, H, X, G(R))`.
>
> Constraints:
> 1. Rules must be machine-executable at generation time — a candidate whose `Rule.evaluate(...)` raises must be rejected before emission.
> 2. Groundings must be computable from data, not just plausible-sounding.
> 3. The stage must stay within a tight per-cycle LLM budget. This forces a **cheap-model-first, frontier-model-adjudicate** pattern: cheap model drafts, frontier model adjudicates only those whose cheap score exceeds a threshold.
> 4. Do not seed the prompt with named strategies, factor categories, or practitioner vocabulary — that is a §0 taxonomy leak.
>
> Research and recommend: (a) how to serialize data slices for LLM input without leaking future information; (b) how to structure the output schema so rule executability is enforced at generation; (c) the cheap-model vs. frontier-model handoff criterion; (d) prompt templates that avoid §0 taxonomy leaks while still orienting the model. Return a concrete design with prompt templates and output schemas. Do not propose rules yourself; propose the machinery that will propose rules.

### Coding prompt (after design)

> Implement `propose/` per the attached design. Use structured output (JSON schema) for candidate rules. Enforce executability: any candidate whose `Rule.evaluate(...)` raises at generation time is rejected before emission. Log every LLM call to the audit module with full prompt+response hashes. The stage is a `Stage` subclass and emits Propose records per [../methodology/09-audit.md](../methodology/09-audit.md) §"Propose records", including the free-text rationale (logged but withheld from Council downstream).

---

## 3.3 Originality filter + anti-pattern list — **[L]**

### Research thread prompt

> Read [../methodology/03-discovery-loop.md](../methodology/03-discovery-loop.md) §"Originality filter" and §"Rules about rules". Design the originality filter. Cover:
>
> (a) How to represent an anti-pattern entry so a candidate rule's grounding can be tested for reducibility mechanically, not by LLM judgment alone. Entries should be computable matchers against grounding statistics, not English labels.
>
> (b) How to seed the list before any cycles have run. Seeding from named strategy categories violates M1 ([../Objective.md](../Objective.md)). The list must seed from an empty or near-empty state and let itself populate from measured out-of-sample statistics on this methodology's own rule history.
>
> (c) How to bound the list size (target ≤ 50) and retire stale entries. Mutable each M2a; self-empties if meta-validation rejects its usefulness.
>
> (d) The acknowledged M1 paradox: an anti-taxonomy is still a taxonomy. What property of the filter makes it acceptable despite the paradox? (Hint: data-derived, subtractive-only, bounded, mutable.)
>
> Return a design doc with data structures, seeding procedure, reducibility test, and the M2a revision procedure.

### Coding prompt (after design)

> Implement `originality/` per the attached design. Include: the seeding procedure, the reducibility test, the retire-when-stale logic, and the meta-validation feedback loop (when M2a rejects the list's utility, it empties). The filter is a `Stage` subclass. Every decision logs `rule_id`, `result`, `matched_anti_pattern` (if rejected), and `anti_pattern_list_version` per [../methodology/09-audit.md](../methodology/09-audit.md) §"Originality-filter records".

---

## 3.4 Screen stage — **[M]**

> Implement `screen/` per [../methodology/03-discovery-loop.md](../methodology/03-discovery-loop.md) step 3. Cheap held-out evaluation with a hard per-candidate dollar cap. Checks: signal-to-noise threshold, turnover consistency with retail friction, grounding reproducibility on the held-out window. Thresholds are config-driven, not hardcoded.
>
> The window used for Screen must be tagged and made unavailable to Validate for the same rule — implement this as a **reservation system** in the access layer (from [01-foundation.md](01-foundation.md) §1.3): when Screen reads window `[t0, t1]` for rule `R`, `access` records the reservation; subsequent Validate reads for `R` that would overlap the reservation are refused.

---

## 4.1 Validate stage — **[L]**

### Research thread prompt

> Read [../methodology/04-validation.md](../methodology/04-validation.md). Design the Validate implementation. Cover:
>
> (a) Time-series splitting with purged gaps sized to the longest feature dependency. How do I compute the gap automatically from the feature-spec dependency graph in [01-foundation.md](01-foundation.md) §2.2?
>
> (b) Nested inner/outer folds with no-tuning-on-outer. Any tuning happens inside outer-train, never on outer-holdout.
>
> (c) Regime-tag partitioning with AI-derived tags (see 4.2). A rule must dominate competitors in a majority of regime tags, not only in aggregate.
>
> (d) The four-competitor set (cash, buy-and-hold on `R`'s realized universe, randomized-`C`, permuted-feature). Implementation for each.
>
> (e) Stochastic-dominance testing at a pre-committed order. Dominance is the gate; a point statistic is not.
>
> (f) Utility functional form: "expected log-growth net of friction, drawdown-penalized" as the initial parametric form, with parameters config-driven and revisable at M2a. The rank-order under competing utility forms is reported alongside.
>
> Return a design with algorithms, parameter defaults, and an API spec.

### Coding prompt (after design)

> Implement `validate/` per the attached design. All four competitor generators are testable modules. The output is a `ValidationReport` with distributions (never scalars). Include property tests on split disjointness (no data point in any Screen window for `R` appears in any Validate window for `R` — proof derived from lineage). Emit Validate records per [../methodology/09-audit.md](../methodology/09-audit.md) §"Validate records".

---

## 4.2 Regime-tag derivation — **[M]**

> Implement `regimes/` that derives regime tags from raw-store state per [../methodology/04-validation.md](../methodology/04-validation.md): clusters over volatility percentiles, cross-sectional dispersion percentiles, event-density percentiles — all computed from the raw store, never from externally-labeled regimes. Tags are named `regime_0`, `regime_1`, … with statistical fingerprints attached. Re-derived every M2a.
>
> No regime tag inherits a name from an external regime taxonomy. If a future reader looks at a regime fingerprint and says "that's a well-known regime" — fine, that is coincidence, not design.

---

## 4.3 Meta-validation (deferred) — **[M, Phase 11+]**

Don't build until you have graduated/retired rules to score. When you do:

> Read [../methodology/04-validation.md](../methodology/04-validation.md) §"Meta-validation". Implement `meta_validate/` that scores a validation protocol `P` by its calibration (predicted-quantile frequencies vs. realized) and discrimination (predicted-rank vs. realized-rank correlation) on the methodology's own live-rule history. The function takes a rule-history set and a protocol, returns calibration + discrimination scores. Challenger-generation can be manual at first: run meta-validation on `P_0` vs. a hand-specified `P_1` at each M2a.

---

## Exit criteria for this phase

- A synthetic rule passes through Propose → Originality → Screen → Validate end-to-end on test data, producing a `ValidationReport` with competitor-dominance output.
- LLM spend during a full cycle is within budget (cheap-model-first discipline verified).
- Propose prompt templates have been grep-reviewed for named strategies, factor labels, or inherited taxonomies — zero matches.
- Screen and Validate windows for a rule are provably disjoint (lineage-based test passes).
