> **Status (as of 2026-04-21): Demoted to seed hypothesis under [Objective.md](Objective.md) v2.**
>
> This document is no longer authoritative architecture. It is preserved as one human-curated hypothesis about what a multi-node alpha pipeline could look like — useful as prior art for the AI-native discovery process described in Objective.md §3 (M1, M2, M4), not as a specification to implement. Its 14 nodes, specialist baselines, invariants, and tiered-data protocols encode academic-finance ontology and institutional-scale assumptions that the AI-native system must be free to re-derive, refine, or reject. Additionally, portions of this document presume institutional resources (Tier-C data, compensation-isolated teams) that are outside the Section 2 solo-operator scope of Objective.md v2. Read as history, not as instructions.

---

# Final Methodology
## Non-Anthropomorphic Quantitative Reasoning Engine for Short-to-Mid-Term Alpha

*Converged artifact. Historical debate is not retained here; implementation should work from this document.*

---

## 0. Scope

This is the operational specification for an LLM-driven quantitative reasoning engine targeting short-to-mid-term alpha (3-day to 3-month horizon) via high-dimensional causal synthesis and market belief-and-flow modeling. It was forged through three adversarial rounds among three independent AI contributors and represents the converged state.

---

## 1. Core Thesis

The engine extracts alpha by modeling the **expected positioning-change trajectory** of the market population, decomposed into attributable mechanisms, propagated through a typed exposure graph, validated against natural-experiment direction priors and regime-conditional statistical dependence, adjudicated against a council of cross-model-family adversarial agents, and continuously tested against same-tier specialist baselines.

Three non-negotiables:
- LLM semantic plausibility is never admitted as evidence — only as hypothesis.
- No human-persona mimicry anywhere in the reasoning graph.
- No capital moves without a pre-committed falsification clock.

---

## 2. First-Principles Axioms

- **A1 — Objectivity Primacy.** Output is derivable from observable causal physics (flows, balance-sheet constraints, documented diffusion lags, reaction-function rule sets). LLM semantic plausibility is hypothesis-generation only; never evidence. Bounded measured inference from observable proxies is permitted when proxy quality is explicitly tracked.
- **A2 — Target Variable.** The target is the expected **positioning-change trajectory**, decomposed into a five-component **mechanism-attribution vector**: {belief-sensitive, rule-based, forced-flow, dealer-hedging, residual}. Every trade hypothesis must specify the dominant component and carry a confidence score on that specification.
- **A3 — No Persona Mimicry.** Agents are defined by epistemic function ("policy-transmission reasoner," "statistical-validator," "forced-flow accountant"). Never by human archetype.
- **A4 — Falsifiability Clock.** Every hypothesis carries an explicit time horizon and pre-committed invalidation condition. Unfalsifiable ideas are exposure, not ideas.
- **A5 — Decision-Quality Testing.** Validation is measured on post-cost, point-in-time, walk-forward decision utility. MSE is not a proxy for alpha.

---

## 3. Architecture (14 Nodes)

| # | Node | Function | Outputs | Epistemic Role |
|---|------|----------|---------|----------------|
| N1 | **Structured Semantic Extraction with Confidence** | Convert unstructured sources into typed economic primitives with per-primitive extraction-confidence scores; uncertainty propagates forward. | {actor, exposure, cashflow, constraint, timestamp, source-tier, extraction_confidence} | Semantic extraction with propagated uncertainty. |
| N2 | **Exposure Graph Builder** | Maintain a live typed graph of actors and their economic links (supply chain, analyst coverage, bellwether→follower, balance-sheet dependency, regulatory dependency). | Typed multigraph G | State management. |
| N3 | **Consensus Reconstructor** | Prior distribution over priced state with per-dimension variance; proxy-staleness vector; cross-proxy correlation matrix; effective-proxy count = nominal / dominant-eigenvalue share. **Publishes Mechanism-Identifiability Map (C2):** regions of {ticker × regime × time} where A2's attribution vector is not separably estimable from Tier-A/B observables are flagged; candidates in flagged regions cannot clear N10's dominant-mechanism gate and route to N10.V. | **c**, variance, staleness, correlation, effective count, UNRELIABLE flag, Mechanism-Identifiability Map | Measurement with explicit proxy-quality and identifiability monitoring. UNRELIABLE or unidentifiable blocks causal-track N10. |
| N4 | **Hypothesis Generator (LLM)** | Given event e, propose candidate causal chains across G with explicit transmission mechanisms and time lags. | Hypothesis DAG H | Hypothesis only. No trade authority. |
| N5 | **Statistical Validator** | Direction-weighted regime-conditional dependence via PC / GES / NOTEARS + Granger. Causal-direction claims require identifiable natural experiments. **Shock Coverage Map is seeded from non-text sources first (C3):** structured event DBs, microstructure break detection, policy calendars, regulatory-action registries. LLM-sourced shocks enrich but cannot define coverage; text-only shocks without non-text corroboration are flagged and down-weighted. **Publishes causal-identified fraction (C1)** of edges in H' per edge family per tier. | Dependence-validated DAG H'; Markov-equivalence annotations; Shock Coverage Map; causal-identified fraction per edge family / tier | Dependency + direction-prior gate. Edges without priors route to N10.V. Causal fraction is itself a monitored quantity. |
| N6 | **Attention-Cost Estimator** | Measure processing cost for human market to re-price along each surviving edge (cross-entity reasoning depth, release timing, narrative contradiction, coverage sparsity). | Per-edge attention-lag distribution | Quantifies slow-diffusion alpha. |
| N7 | **Forced-Flow Accountant** | Maintain structural-flow calendar: index rebalances, quarter-end trades, lockup expirations, margin thresholds, tax-loss windows, bond-index drift, SOFR shifts, dividend reinvestment, options-expiry gamma flips. | Per-edge non-discretionary flow vector + timing | Quantifies mechanical alpha. |
| N8 | **Liquidity Regime Monitor** | Dealer balance-sheet capacity, intermediation elasticity, holder mix, cross-market spillover. | Regime label + elasticity coefficient | Gates amplitude. |
| N9 | **Reaction-Function Library** | Parameterized rulebooks per tribe; **each rulebook tagged by which A2 mechanism component(s) it maps to**. | f_tribe(state, Δinfo) with mechanism tag | Second-order updater; feeds A2 attribution vector. |
| N10 | **Idea Gate (Split-Tier Filter)** | **Necessary gates (all green required):** causal materiality (validated OR dependence-status), consensus gap (N3 delta above threshold AND not UNRELIABLE), propagation asymmetry, **dominant-mechanism confidence** (A2 vector has one component above threshold), falsification clock defined. **Amplifier gates (scale sizing, don't gate entry):** forced-flow (N7), liquidity support (N8). **N10.V — Dependence-trade track:** edges lacking direction priors; sizing capped; no causal language permitted. | Track label + sizing multiplier + audit trail | Split-tier pre-commitment filter. |
| N11 | **Adversarial Council** | Three epistemically disjoint agents spanning **distinct base-model families, embedding models, chunkers, retrieval corpora**. Truth-Last synthesis by agent with highest historical consistency. Correlation measured via **task-manifold audits** (adversarial historical cases, missing-data cases, regime-break cases, identical-input blind-spot tests). Dissent correlation-adjusted. | Kill / proceed + correlation-adjusted dissent vector | A3-compliant red team with measured independence. |
| N12 | **Bayesian Aggregator & Sizer** | Confidence-Weighted Bayesian Aggregation across N4+N5+N9+N11 with discrimination-adjusted weights. Sizing = f(edge magnitude, validation score, regime elasticity, crowding-tail coefficient). Tighter stops on crowded reversal setups. | Position vector, stop, falsification clock | Final authority. |
| N13 | **Crowding / Calibration / Discrimination Tracker** | Factor-specific crowding tensor (mechanical vs reversal); rolling Brier; rolling discrimination (accuracy by conviction decile); agent-level calibration drift. | Coefficient vectors | Closes the loop. |
| N14 | **Data Tiering and Alpha Accounting** | Classify feeds Tier-A (public point-in-time), Tier-B (public lagged), Tier-C (proprietary). Annotate edges in H' with minimum tier. Maintain **two separate alpha ledgers**: architecture alpha (Tier-A/B only) and data-asymmetry alpha (requires Tier-C). Publish per-edge capacity estimates **with pre-committed minimum-capacity threshold (C10)** below which the edge is research-only and not production-capital-eligible. Architecture-alpha claims require both I8 pass and aggregate edge-family capacity above the threshold. | Tier annotations, dual ledger, capacity estimates with threshold, production-eligibility flag | Honest alpha accounting. Tier-C returns may not be reported as architecture alpha. Sub-threshold capacity cannot anchor architecture-alpha claims. |

---

## 4. Invariants

- **I1.** No tradable signal originates from a node upstream of N5 without passing N5.
- **I2.** No position opens without all N10 **necessary gates** green AND N11 proceed. **Amplifier gates** (N7, N8) affect sizing, not entry. Dependence-track trades (N10.V) open only under capped sizing with falsification clock.
- **I3.** Every position carries a written falsification condition timestamped at entry; violation forces immediate exit regardless of P&L.
- **I4.** N9 rulebooks are updated only on public-rule change or pre-committed out-of-sample degradation threshold.
- **I5.** Relative-value expressions preferred by default; outright directional expressions require a dominant-term argument in H' with validation score above a higher threshold.
- **I6 — Edge Half-Life Priors (not rules).** Each edge type carries a pre-committed half-life prior with uncertainty interval. Forced-flow: 1–10 trading days (central 5). Attention-lag: 30–120 calendar days (central 60). Structural balance-sheet: 120–360 calendar days (central 180). Decay estimates update via conservative Bayesian posteriors. Capital rotation between decay classes requires a **second-order crowding check at the destination class**.
- **I7 — Hyperparameter Meta-Optimization with Regime-Sample Discipline.** All thresholds, windows, priors, coefficients selected by out-of-sample decision-utility optimization under: (a) nested walk-forward with outer fold = regime; (b) DOF cap — jointly-optimized hyperparameters ≤ one-third of independent regime count; (c) hyperparameter families frozen for pre-committed windows, re-optimized at most once per window per year; (d) mandatory ablation and specialist-baseline tests before promotion. Effective sample size is computed in regimes, never in trades.
- **I8 — Specialist Baseline Dominance Test.** Within each data tier (A, B, C reported separately), the full architecture must walk-forward, post-cost, post-slippage, post-borrow, capacity-adjusted, beat the best single-edge-family specialist baseline: (a) forced-flow specialist, (b) attention-lag diffusion specialist, (c) structural balance-sheet propagation specialist, (d) policy-shock propagation specialist. **Extended per C1: the causal-only edge subset must separately beat a dependence-only specialist baseline; if the causal-identified fraction from N5 falls below a pre-committed floor, architecture-alpha claims tagged "causal" are revoked until the fraction recovers.** Failure in a tier routes capital within that tier to the winning specialist; the integration layer is demoted within that tier until it re-qualifies. Re-tested quarterly on rolling panels. **No architecture-alpha claim is permitted in a tier where this test has not been passed in the latest evaluation.**

---

## 5. Data Tiering Specification

| Tier | Definition | Examples | Alpha Ledger |
|------|------------|----------|--------------|
| **A** | Public, point-in-time, no meaningful lag, no revision contamination | Options chain, exchange microstructure, index-rebalance schedules, Fed statement timestamps, earnings release timestamps, published tribe rulebooks (CTA thresholds, risk-parity vol targets) | Architecture alpha |
| **B** | Public but lagged, revised, or aggregated | 13F filings (quarterly + 45-day lag), CFTC commitments, EDGAR filings, sell-side estimate histories, macro releases with revisions | Architecture alpha (with lag-adjusted point-in-time reconstruction) |
| **C** | Proprietary, paid-asymmetry, prime-broker / custodian / vendor-exclusive | Broker-level dealer books, intraperiod 13F turnover, firm-specific flow feeds, exclusive alt-data feeds | Data-asymmetry alpha — reported separately, never conflated with architecture alpha |

Edge annotation is strict: an edge claims architecture alpha only if every input to its pipeline is Tier-A or Tier-B. Any Tier-C dependency moves the edge to the data-asymmetry ledger.

---

## 6. Test Hygiene Protocol

Five controls, all pre-registered before any I8 evaluation.

1. **Pre-registration (extended per C4).** Specialist baselines, cost model, capacity model, data-tier classification, promotion/demotion thresholds, I8 pass/fail criteria, **and the tradable asset universe (tickers, instruments, sectors, regions)** are frozen in writing before evaluation runs. Post-hoc changes — including universe modification — invalidate the run.
2. **Leakage containment (extended per C5).** Tier-C data may not enter Tier-A/B experiments through features, labels, capacity estimates, benchmark construction, post-hoc filtering, or any hyperparameter choice. **Tier-C-exposed researchers are walled off from the Tier-A/B architecture team** for modeling and hyperparameter design; Tier-C-aware researchers work only on the data-asymmetry ledger. Cross-pollination of N9 rulebooks, N5 shock selection, or N12 coefficients by Tier-C-exposed personnel invalidates the architecture-alpha claim. Leakage audits are run on every evaluation cycle.
3. **DOF enforcement.** I7's one-third-of-regimes cap applies **per jointly-optimized hyperparameter batch**, with hyperparameters factorized across nodes. Regime granularity is multi-axial (liquidity × vol × curve × correlation). Optimizer DOF exceeding the per-batch ceiling voids the evaluation regardless of performance.
4. **Language discipline (extended per C6).** Every trade thesis must carry **either** a Markov-equivalence-class annotation (identifying which causal direction is assumed and why it cannot be ruled out) **or** a natural-experiment citation (pointing at the specific identifying event in the Shock Coverage Map). Absence of either routes the trade to N10.V regardless of the language used. Synonym abuse of causal verbs is immaterial because the annotation, not the prose, determines track status.
5. **Capital routing enforcement (extended per C7).** I8 failure in a tier triggers **mandatory minimum specialist allocation** within that tier for a pre-committed lock-up period (minimum one evaluation cycle, minimum floor ≥ a pre-committed fraction of the tier's prior allocation). **Zeroing the tier counts as tier-exit** and requires full re-qualification to re-enter — equivalent consequence to I8 failure plus a cooldown. Reporting I8 results without capital consequences voids the architecture-alpha claim.

---

## 7. Operational Loop

**Daily.** Consensus refresh (N3); overnight event ingestion (N1); graph update (N2); calendar scan (N7); liquidity regime label (N8); hypothesis generation on new events (N4); statistical validation of new edges (N5); gate evaluation (N10); council adjudication (N11); sizing (N12); position entry with falsification clock (I3).

**Weekly.** Crowding tensor refresh (N13); reaction-function fit diagnostics (N9 vs I4 thresholds); task-manifold audit sample (N11).

**Quarterly.** I8 specialist-baseline dominance re-evaluation per tier; I7 hyperparameter re-optimization window check; I6 half-life posterior updates; capital routing decisions per I8 outcome; N14 dual-ledger reporting.

---

## 8. Anti-Patterns

The architecture refuses to:
- Produce OHLCV-only forecasts.
- Emit generic sentiment scores.
- Issue a single-LLM "buy/sell" terminal output.
- Deploy human-persona agents ("Soros", "Buffett", "Munger", "Druckenmiller").
- Accept backtest results that are not point-in-time, survivorship-clean, cost-inclusive, and decision-utility framed.
- Accept any narrative claim not quantified via a measured media-velocity function (N6).
- Treat Tier-C returns as architecture alpha.
- Re-optimize hyperparameters more often than I7 permits.
- Open a position without a falsification clock.
- Report I8 results without routing capital accordingly.

---

## 9. Implementation Roadmap

**Phase 0 — Baseline Construction (extended per C8).** Implement the four specialist baselines first (forced-flow, attention-lag, structural balance-sheet, policy-shock). Specialists are built by **a structurally independent group un-incentivized by integration-layer success** — an external red-team, an academic replication, or a compensation-isolated internal group. The strongest credible specialist per edge family is used. Self-reported specialist performance that cannot be independently reproduced is inadmissible as an I8 baseline. Phase 0 is complete when each specialist produces walk-forward, post-cost returns on Tier-A/B data alone, independently verified.

**Phase 1 — Single-Edge-Family Integration.** Build N1–N14 for one edge family at a time, starting with forced-flow (highest signal-to-noise, shortest feedback loop). Run I8 against the forced-flow specialist. Proceed to next edge family only on I8 pass.

**Phase 2 — Cross-Edge Integration (rewritten per C9).** Add edge families by their **marginal contribution to the joint N2/N12 decision-utility function**. An edge that fails standalone I8 but raises joint utility passes; an edge that passes standalone but does not raise joint utility fails. **Sequential-isolation testing is prohibited** because it destroys the graph-interaction value that is the core justification for the integration layer. Re-run joint I8 after each addition. Any addition that fails to raise joint utility is removed.

**Phase 3 — Meta-Rotation Layer.** Only after I8 has passed across at least two edge families may the meta-rotation layer (I6 decay-class rotation) be activated. The meta-layer is itself subject to I8.

**Phase 4 — Tier-C Expansion.** Only after Tier-A/B architecture alpha is established per I8 may Tier-C data be introduced. Tier-C returns are reported on the data-asymmetry ledger and never conflated with architecture alpha.

---

## 10. Provenance

This methodology was converged through three adversarial rounds among three independent AI contributors:

- **Structural spine** (statistical causal discovery with PC/GES/NOTEARS, Truth-Last multi-agent aggregation, factor-specific crowding / tail-risk treatment, discrimination-weighted Bayesian aggregation): contributed by Gemini.
- **Target-variable framing and validation discipline** (market-update function, six-gate filter, decision-utility testing, relative-value preference, data-tier separation, specialist-baseline dominance as terminator): contributed by ChatGPT.
- **Variant-perception target and operational loop** (consensus delta, n-order causal chains, adversarial self-challenge pattern): contributed by Claude, retained as operational framing but demoted from standalone signal source.

Convergence is conditional, not absolute. I8 is the termination condition. If I8 fails in a tier, the integration layer is demoted in that tier until it re-qualifies. If I8 fails in every tier persistently, the architecture is falsified and capital flows permanently to specialists.

That is the correct place to stop arguing architecture and start testing.

**Convergence status.** After a Gemini-led independent verification round (10 credible hits, 1 partial, 1 concession), the ten resulting controls C1–C10 have been incorporated above. Gemini issued Option A — GO Unconditional. The methodology is frozen. Phase 0 begins.
