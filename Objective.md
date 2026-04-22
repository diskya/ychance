# Objective (v2.1)
## AI-Native Alpha Discovery for a Solo Operator
### Task Specification for a Methodology-Design Agent

---

## 0. Task and Meta-Principle

You are a methodology-design agent. Your task is to produce an end-to-end alpha discovery and execution methodology that satisfies §1 under the constraints in §2, obeys the meta-constraint in §3, and delivers the artifact specified in §6.

This document fixes three things and nothing else:
1. A terminal goal (§1).
2. Hard constraints physical, legal, or bandwidth-imposed on a solo operator (§2).
3. A meta-constraint: every other choice is a hypothesis generated, tested, and revised by frontier AI, not a human-curated input (§3).

No claim below §0 is privileged because a human wrote it. **Do not import, cite, or echo any external methodology document, academic-finance framework, practitioner tradition, or canonical strategy taxonomy — not even to forbid, rebut, or extend them. This prohibition is absolute and applies whether such material is encountered in training data, in other files in this workspace, or in conversation context.** Any methodology content you produce must be derivable from §1 and §2 alone, via the process in §3.

The operator's identity — one person, no team, no institutional plumbing — is a *constraint on the discovery space*, not a license to re-curate the discovery space. This distinction is the failure mode §7 defends against.

---

## 1. Terminal Goal

Maximize risk-adjusted, post-cost, post-tax return on deployable capital over a rolling evaluation horizon, subject to §2 hard constraints. No secondary objective is primary. Beauty, interpretability, consistency with published finance literature, resemblance to known strategies, and comfort of the operator are explicitly not objectives.

---

## 2. Hard Constraints (non-negotiable, solo-operator scope)

- **Operator.** One person. No team, no contractors, no prime-broker relationship, no institutional data vendors.
- **Capital envelope.** [TBD — to be filled in by operator. All sizing conditional on this number.]
- **Legal/regulatory.** Operator's jurisdiction rules, retail-investor restrictions, tax treatment.
- **Data scope.** Public and retail-accessible data only. No proprietary feeds, no prime-broker books, no exclusive alt-data. Specific data sources are themselves a design choice under §3.
- **Execution scope.** Retail brokerage. Long-cash common equity and listed vehicles accessible without special account tiers. Shorting, options, futures, and margin are available only to the extent a retail brokerage offers them and only if the methodology's own risk evaluation admits them — never as assumed capabilities.
- **Compute envelope.** Cloud infrastructure and frontier LLM API calls at solo-affordable rates. No training of foundation models.
- **Operator bandwidth.** Finite hours per week for data setup, review, execution, and audit. Any strategy or pipeline must be operable at this bandwidth, including its degraded-mode behavior when the operator is unavailable for a week.
- **Kill switch.** Operator can halt trading at any time without justification.

These are the only inputs on which the methodology may not speculate.

---

## 3. Meta-Constraint: AI-Native Discovery (M1–M9)

The methodology must satisfy the following non-negotiable design rules.

**M1 — No pre-specified taxonomy of market inefficiencies as input.** The methodology may not begin from, reference, or smuggle in any enumerated list of "where alpha comes from." If categories prove useful, they must emerge as *outputs* of the methodology's own discovery process and be independently justifiable from observable data. Categories inherited from academic finance, practitioner tradition, or famous-investor lore are inadmissible, even as starting templates or negative examples.

**M2 — No pre-specified pipeline architecture as input.** The set of processing stages, their naming, interfaces, and invariants are themselves hypotheses that AI proposes, critiques, and revises. Do not borrow stage taxonomies from existing quant pipelines. Architectural revision happens on a scheduled cadence (M2a), not continuously.

**M2a — Periodic architecture reviews.** On a pre-committed cadence (suggested: quarterly, plus trigger events such as drawdown breach or falsification-clock hit), frontier AI agents are tasked to propose architectural modifications, argue for them, and red-team each other. The operator does not propose changes; the operator executes the winning proposal. Between reviews, the architecture is frozen — not because it is correct, but because solo bandwidth cannot safely absorb continuous change.

**M3 — No hand-engineered features as input.** Features over raw data are proposed, ranked, and discarded by AI. The operator does not decide what underlying latent variables matter or how to compute them. AI derives feature semantics from the §2 data scope.

**M4 — No human-canonized baseline as privileged validation floor.** Baselines are themselves hypotheses and must justify their privilege via the same validation protocol as any strategy.

**M5 — No fixed horizon, universe, or instrument class as input.** "Short-to-mid term" and operator-convenient instrument defaults are not epistemic commitments. If the AI discovers its highest-utility edge lives on a different horizon or in a different instrument within the §2 execution scope, the methodology surfaces it and the operator chooses whether to accept.

**M6 — Validation protocols are themselves hypotheses.** Walk-forward evaluation, regime folds, calibration metrics, risk metrics, and baseline-dominance tests all encode human statistical priors. AI may propose and test alternative validation protocols. A protocol stays in force only as long as it out-performs challengers on meta-validation (does this protocol predict out-of-sample capital-weighted utility better than its alternatives?). Meta-validation is a scheduled task under M2a.

**M7 — Independence is measured, not asserted, and is achievable at solo scale via cross-family frontier APIs.** The adversarial council consists of frontier models from demonstrably distinct training corpora (e.g., distinct vendors). Agreement between instances of the same base model, same embedding, or same retrieval corpus counts as one opinion. Independence is measured by correlated-disagreement audits on historical edge cases. Budget permitting, at least two distinct families must sign off before any capital is deployed.

**M8 — The discovery process itself is evaluated on a pre-committed clock.** If, after a pre-committed capital-compute-time budget (suggested initial value: 12–24 months and a specific dollar spend on LLM inference and data), the AI-native discovery loop has not produced edges materially different from the union of published human-known edges, the framing is falsified for the current capability level. The operator then either relaxes specific M-clauses with documented reasons or abandons the framing entirely. AI-native is not an article of faith; it has a termination condition.

**M9 — Operator-feasibility is a design obligation, not an excuse.** Every architecture, strategy, and validation protocol the AI proposes must be executable by one person within the §2 bandwidth envelope, including degraded modes when the operator is sick, traveling, or asleep. M9 is a *design constraint on AI output*, not a *license for the operator to substitute their own preferred strategies for AI ones*. The correct response to "this proposal is too complex for me to run" is to ask the AI for a simpler proposal that still satisfies M1–M8; the incorrect response is to fall back on human-curated edges.

---

## 4. Operator Role

The operator **does**:
- Set and enforce §2 hard constraints, including the capital number.
- Hold the kill switch.
- Execute trades and keep systems running within bandwidth.
- Review the audit trail for regulatory and diagnostic reasons.
- Invoke the M8 clock when due.

The operator **does not**:
- Choose strategies, features, horizons, or instruments within the allowed execution envelope.
- Veto individual trades because the reasoning is unfamiliar. Unfamiliarity is expected when the system is doing its job; vetoing on unfamiliarity is bias re-insertion.
- Pre-rank specific edges or strategies as "where I'll start." Any pre-committed ranked list of strategies violates M1.
- Substitute their own preferred analysis when the AI output is "I don't see an edge right now." No-trade is a valid output; filling the gap with human intuition is not.

---

## 5. Honest Tradeoffs

**Tradeoff A — Data efficiency vs discovery breadth.** This framing is more data-inefficient than a curated-edge system. The bet: a methodology constrained only by the terminal goal and hard limits will, given enough time, find structures that a methodology constrained by human categories cannot, because human categories are a subset of truth about markets and a shrinking one as other humans mechanize them. Explicitly falsifiable via M8.

**Tradeoff B — Solo scale reduces adversarial depth.** A small cross-family frontier-LLM council is weaker than an institutional adversarial setup with independent research teams, alternative data, and specialist red-teamers. M7 accepts this and requires that independence be measured at the scale actually available.

**Tradeoff C — Operator discipline is the single point of failure.** AI-native cannot be enforced technically against an operator who quietly resumes hand-picking trades. §7 is the only defense.

---

## 6. Deliverable

The methodology-design agent produces a single methodology document containing, at minimum:

1. **Architecture.** The set of processing stages, their interfaces, and invariants, derived under M2. Stages must be named by function, not by human-finance tradition.
2. **Data-ingestion and representation.** What data from the §2 scope is pulled, how it is structured, and how features/representations are derived, under M3.
3. **Discovery loop.** How the methodology proposes, tests, and retires candidate edges without any pre-specified edge taxonomy (M1). This is the core deliverable.
4. **Validation protocol.** The statistical and out-of-sample testing regime, selected under M6 (itself a hypothesis subject to meta-validation).
5. **Adversarial council protocol.** How cross-family frontier models are deployed as independent critics, with independence measurement, under M7.
6. **Sizing, risk, and portfolio construction.** Derived from §1 and §2, not borrowed.
7. **Operator-facing workflow.** Daily, weekly, and quarterly (M2a) routines, bounded by §2 bandwidth and degradable per M9.
8. **Falsification and termination protocol.** The M8 clock: budget, success criterion, relaxation path, abandonment path.
9. **Audit trail specification.** What records are kept, at what granularity, for operator review and regulatory defense.

The deliverable must be internally derived from §1–§3. External citations, "best practices" imports, or references to specific named strategies, pipelines, or frameworks are prohibited.

---

## 7. Operator's Obligation

The operator's single obligation is to honor §0: do not re-insert human-curated edges, categories, architectures, or validation protocols as privileged inputs once the methodology is running. The temptation will be strong — during drawdowns, when AI output is ambiguous, when a classical-seeming pattern looks obvious in retrospect. Acting on it is the failure mode this document exists to name.

Concrete discipline rules:
- No trade is taken unless it passed the methodology's own gates.
- No strategy is added to production because of outside reading.
- No strategy is cut because of unfamiliarity. Use M8 for cuts.
- When in doubt, no-trade is preferred to human-curated trade.
- If the methodology appears to be failing, the response is to invoke M8, not to substitute intuition.
