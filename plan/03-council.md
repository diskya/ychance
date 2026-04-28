# Phase 4 — Council + Independence

**Goal**: the adversarial critic protocol per [../methodology/05-council.md](../methodology/05-council.md). The weight-bearing piece is *measured* independence.

Requires [02-discovery-loop.md](02-discovery-loop.md) through EmpiricalTest and ≥ 2 distinct vendor families from Phase 0. Legacy `council_llm/` and `council_decide/` were deleted; rebuild clean.

---

## 4.1 Voter wrapper — **[M]**

> Build `council_llm/` abstracting over ≥ 2 distinct vendor families with a common interface:
> ```python
> def vote(pattern, empirical_test_report, raw_slice) -> (vote, rationale, citations)
> ```
> Enforce sealed votes, no Discover rationale, no proposer identity. Cache by `(pattern_hash, empirical_test_hash, member_version)`. Two-phase query: `approve` / `reject` / `need full review`; only the third triggers full rationale generation. Each voter is a `Stage` subclass and audits vote records.

## 4.2 Decision rule — **[S]**

> Build `council_decide/` reading the current independence classification (from 4.3) and applying the [../methodology/05-council.md](../methodology/05-council.md) decision rule: ≥ 2 `approve` from mutually-independent members; any independent `reject` blocks. Approved → Archive; rejected → log with blocking rationales (no auto-resubmit). Aggregate decision audited.

---

## 4.3 Independence audit — **[L]**

The research-heavy part and the load-bearing piece of M7.

### Research thread prompt

> Design pairwise rationale-similarity per [../methodology/05-council.md](../methodology/05-council.md). Specify: non-council embedder, similarity metric, initial `θ_indep`, sparse-data rule, collapsed-pair decision mechanics, and simulated validation for identical models, distinct families, and correlated blind spots.

### Coding prompt (after design)

> Implement `independence/`. Runs at M2a and on-demand when triggered by systematic re-replication failure of approved Patterns. Output is a classification `{member: independent_group_id}` consumed by `council_decide`. Every audit invocation logs all rationale pairs, similarities, and the classification.

## 4.4 Calibration test — **[S]**

> Implement `council_calibration/` tracking re-replication outcomes per member's approved Patterns. A member whose approvals systematically fail re-replication against a pre-committed threshold is flagged for zero-weighting at next M2a. Output feeds Review.

---

## Exit criteria

- A synthetic Pattern passes the full Council protocol on a test `EmpiricalTestReport`, producing a decision record with member-by-member votes, rationales, citations, aggregate decision.
- Independence audit produces expected classification on all three simulated scenarios.
- Caching: identical `(pattern, empirical_test_report, member)` triples return cached votes without a new LLM call.
- Two-phase query reduces LLM spend on obvious cases (verified).
