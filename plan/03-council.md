# Phase 5 — Council + Independence

**Goal**: the adversarial critic protocol ([../methodology/05-council.md](../methodology/05-council.md)). The weight-bearing part is measured independence; a council of "two frontier models" without an independence measurement is one voice wearing two masks.

## Dependencies
- [02-discovery-loop.md](02-discovery-loop.md) is complete through Validate — Council consumes `ValidationReport` objects.
- Phase 0 ([00-operator-decisions.md](00-operator-decisions.md)) has identified ≥2 distinct vendor families.

## Parallelism within this phase
- 5.1 and 5.3's research thread can run in parallel.
- 5.2 depends on 5.1 + the 5.3 design.
- 5.4 can run in parallel with everything after 5.1.

---

## 5.1 Multi-vendor LLM wrapper — **[M]**

> Implement `council_llm/` that abstracts over ≥2 distinct vendor families with a common interface:
>
> ```python
> def vote(rule, validate_report, raw_slice) -> (vote, rationale, citations)
> ```
>
> Enforce:
> - No vendor sees another vendor's rationale or vote.
> - No vendor sees the Propose-stage free-text rationale (prevents rationale contagion — see [../methodology/05-council.md](../methodology/05-council.md) §"Inputs to each member").
> - No vendor sees the identity of the proposing model.
>
> Cache by content hash of `(rule_hash, validate_report_hash, member_version)`. Implement a **two-phase query**: a short "screening query" returns `approve` / `reject` / `need full review`. Only `need full review` triggers full rationale generation. Screening responses are also cached.
>
> Each voter is a `Stage` subclass; vote records go to audit per [../methodology/09-audit.md](../methodology/09-audit.md) §"Council records".

## 5.2 Decision rule — **[S]**

> Implement `council_decide/` that reads the current independence classification (from 5.3) and applies the decision rule in [../methodology/05-council.md](../methodology/05-council.md): ≥2 `approve` votes from mutually independent members required; any independent `reject` blocks. Emit the aggregate decision record to audit. A rule with a council-block is routed back to Propose with blocking rationales attached; Propose may revise and resubmit (creating a new `rule_id`) or Retire.

---

## 5.3 Independence audit — **[L]**

This is the research-heavy part. It is also the weight-bearing piece of M7 — getting it wrong reduces Council to a single-voice rubber stamp.

### Research thread prompt

> Read [../methodology/05-council.md](../methodology/05-council.md) §"Independence audit". Design the pairwise rationale-similarity procedure for measuring council-member independence.
>
> Cover:
>
> (a) **Defensive-diversity embedder.** What embedding model should compute rationale similarity? It must not be a model from any council family (otherwise we are measuring similarity through a biased lens). Recommend a specific open-weights or alternative-vendor embedder given the council families shortlisted in [00-operator-decisions.md](00-operator-decisions.md).
>
> (b) **Similarity metric.** Cosine on embeddings is the obvious starting point but may not capture "reasoning" similarity (two rationales can differ in surface form but agree in reasoning, or vice versa). Consider: clustering over short rationale summaries, agreement-trajectory across many rules, MMR-style diversity scoring. Defend a choice.
>
> (c) **`θ_indep` threshold.** The methodology calls for a pre-committed independence threshold. What is a defensible starting value given no prior data? Include a sensitivity analysis: how does the threshold affect the collapse decision on simulated scenarios?
>
> (d) **Simulated validation.** Before shipping, simulate at least three scenarios: two identical models (should collapse), two different models from demonstrably different training lineages (should not collapse), two models with correlated blind spots (edge case — the metric should collapse them even if surface rationales differ). Show the metric discriminates these.
>
> (e) **Sparse-data regime.** Early in the clock, there are few rules to vote on. How does the independence computation behave with few samples, and what is the operating rule for decisions made before enough data exists?
>
> (f) **Collapsed-pair mechanics in the decision rule.** When pair `(A, B)` is classified as collapsed, they count as one voice. Specify the exact decision-rule modification: does an `approve` from only `A` count? What about `A` approves, `B` rejects?
>
> Return a design doc with algorithms, simulated-validation results, and starting parameters.

### Coding prompt (after design)

> Implement `independence/` per the attached design. Runs at M2a and on-demand when triggered by systematic Observe-vs-Validate miscalibration. Output is a classification `{member: independent_group_id}` that `council_decide` (5.2) reads. Every audit invocation logs all rationale pairs, similarities, and the classification.

---

## 5.4 Calibration test — **[S]**

> Implement `council_calibration/`: per council member, track realized-vs-Validate-predicted `U(R)` for the member's approved rules. If a member's approvals systematically under-deliver against a pre-committed threshold (measured on the member's own approvals, not on Council aggregate), flag for zero-weighting at the next M2a. This is a monitoring job, not a gate on a single rule. Output feeds the Review stage ([../methodology/01-architecture.md](../methodology/01-architecture.md) §"Review (M2a)").

---

## Exit criteria for this phase

- A synthetic rule passes through the full Council protocol on a test `ValidationReport`, producing a decision record with member-by-member votes, rationales, citations, and an aggregate decision.
- Independence audit produces the expected classification on all three simulated scenarios from 5.3 design.
- Caching works: identical `(rule, validate_report, member)` triples return cached votes without a new LLM call. Cache-miss rate is logged to audit for cost tracking.
- Two-phase query is verified to reduce LLM spend on the "obvious" approve/reject cases.

## Failure modes to pay attention to

- **The council is secretly one voice.** Multi-vendor is necessary but not sufficient for independence. If the audit's simulated-validation shows every real-world pair collapsing to one group, the vendor shortlist from Phase 0 is wrong. Rotate families.
- **Calibration ignores aggregate.** A member might have low individual calibration but be load-bearing for the aggregate decision. The methodology still zero-weights them — individual calibration is the gate. Don't override this.
- **Caches go stale.** Regime-change flags from Observe (Phase 6, see [04-lifecycle-and-sizing.md](04-lifecycle-and-sizing.md)) must force cache invalidation for affected rules. If the flag fires and cached approvals stand anyway, that is a defect.
