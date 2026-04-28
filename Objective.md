# Objective (v3.0)
## A Frontier-AI Pattern-Discovery System for a Solo Operator

## 0. Operator targeting prohibition

Earlier framings forbade *any* import from external traditions. That was self-undermining and unenforceable. This version keeps the enforceable rule.

**§0a — Operator does not target.** The operator does not maintain, write down, or communicate to the system a list of patterns, mechanisms, factors, or strategies they want the system to find. The operator does not seed any stage with content-shaped suggestions ("have you checked X?", "what about Y?"). Every prompt the operator sends is logged; deviations are auditable at M2a.

**§0b — Admissible priors.** Empirically-established structural facts about the data domain (the kind of thing every working researcher would assume exists in some form) are admissible as priors in cost models, capacity gates, and friction estimators. They may not be used as *targets* of discovery.

**§0c — Substrate imports acknowledged.** Statistics, content-addressing, hashing, and council protocols are tools, not violations. The bet is on operator-discipline, not import-purity.

**§0d — Falsification clock.** This framing is a research bet, not faith. M8 governs its termination.

## 1. Terminal Goal

Produce a continuously-growing corpus of **council-approved, replication-tested Patterns** observed in the §2 data scope, where:

- A **Pattern** is a computable, falsifiable claim about data — a specific statistical signature observable in a specific scope, with a frozen empirical fingerprint and a pre-committed test for replication on held-out windows.
- **Council-approved** means ≥ 2 frontier-AI vendor families from measurably-distinct training pipelines have independently approved (per §3.M7).
- **Replication-tested** means the fingerprint, frozen at observation time, reappears at a pre-committed level on data the Pattern was not derived from.

The success metric is the **rate** at which the system produces such Patterns per dollar of LLM and data spend, not P&L. Trading deployment is out of scope; the corpus is the artifact.

Beauty, interpretability, literature agreement or disagreement, and operator comfort are not objectives. Novelty is incidental, not pursued.

## 2. Hard Constraints

- **Operator.** One person. No team, no contractors, no institutional data vendors.
- **Capital envelope.** A single `E` covering LLM inference, data feeds, compute, storage. There is no trading capital — `E` is a research budget.
- **Data scope.** Public and retail-accessible data only.
- **Compute envelope.** Cloud + frontier LLM API at solo-affordable rates. No training of foundation models.
- **Operator bandwidth.** Finite hours per week; the system must be operable and reviewable at this bandwidth, including a degraded mode when the operator is unavailable for a week.

## 3. Meta-Constraints (M1–M9)

- **M1.** No operator-supplied target taxonomy. The LLM brings its training distribution either way; the operator does not amplify a particular slice.
- **M2.** No pre-specified pipeline architecture as input. Stages and invariants are themselves hypotheses.
- **M2a.** Architecture is revised on a pre-committed cadence (suggested: quarterly, plus trigger events). Frozen between cycles.
- **M3.** No hand-engineered features. AI proposes, ranks, retires.
- **M4.** No human-canonized baseline as privileged validation floor.
- **M5.** No fixed scope as input. The §2-admissible scope a Pattern operates on is part of the Pattern.
- **M6.** Validation protocols are themselves hypotheses, revised at M2a if a challenger predicts replication better.
- **M7.** Independence is measured, not asserted. The adversarial council uses frontier models from demonstrably distinct training corpora; agreement between same-family instances counts as one voice. ≥ 2 distinct families must approve before archive entry.
- **M8.** Discovery is evaluated on a pre-committed clock. If, after a pre-committed budget, the system has not produced a pre-committed minimum number of council-approved, replication-tested Patterns, the framing is falsified. The operator either relaxes one M-clause with documented rationale or abandons. AI-native is not faith; it terminates.
- **M9.** Operator-feasibility is a design obligation. Every architecture and protocol must be reviewable by one person within §2 bandwidth. The correct response to "this is too dense to review" is to ask AI for a less dense protocol; the incorrect response is for the operator to start hand-curating.

## 4. Operator Role

The operator **does**: set §2 constraints; pick the data scope `E` covers; review archived Patterns at their own discretion as a *reader*, not a gate; maintain the bias log; run M2a on cadence; invoke M8 when due; co-research with Discover only within the input-shape discipline below.

The operator **does not**: choose patterns, features, scopes, or assertions; veto a council-approved Pattern on grounds of unfamiliarity *or* familiarity; pre-commit a ranked list; override council decisions.

### Co-research input-shape discipline (load-bearing)

Permitted inputs to Discover, only these two shapes:

1. **Tool requests.** "Compute that on a different window." "Show me the distribution stratified by partition." Move the system's exploration without supplying content.
2. **Red-team requests.** "What's the simplest non-pattern explanation?" "Reproduce on shuffled data." "What would falsify this?" Tighten claims without supplying new ones.

Forbidden: naming a phenomenon, factor, category, or pattern; suggesting "what about X"; pointing at a specific time or instrument because of outside knowledge. The urge goes into the bias log, not into the system.

## 5. Honest Tradeoffs

- **A.** Output is Patterns, not P&L. Whether any Pattern is worth trading on is a separate decision not made here.
- **B.** Solo-scale council depth is weaker than institutional. M7 forces independence to be measured at the scale actually available.
- **C.** Operator discipline is the single point of failure. The system cannot enforce §0a against an operator who quietly types content-shaped suggestions. The bias log and M2a review are the only defense.

## 6. Deliverable

A methodology document (the [methodology/](methodology/) tree) containing: architecture; data ingestion and representation; discovery loop with co-research interface; empirical-test protocol; adversarial council protocol with measured independence; operator-facing workflow; falsification clock; audit trail.

## 7. Operator's Obligation

Honor §0a and the §4 input-shape discipline.

- No content-shaped suggestions enter the system. Tool requests and red-team requests only.
- No Pattern is accepted into the archive that did not pass council and replication.
- No Pattern is rejected from the archive on grounds of unfamiliarity, familiarity, or operator priors.
- The bias log is filled in every week, even when "nothing to note" — `none` is required, empty is not. `none` and missed weeks are different.
- When the methodology appears to be failing, invoke M8. Do not substitute curation.

The temptation to violate §0a is strongest in two moments: when the system produces nothing for several cycles, and when the system produces something the operator finds intuitively interesting. Both are predictable; both are the failure mode this document exists to name.
