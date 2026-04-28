# §6.3 Discovery Loop — Core Deliverable

Initial hypothesis under M1–M2. The loop produces candidate **Patterns** and lets empirical replication and council review — not operator preference — decide which enter the archive.

## Pattern object

A Pattern is:
- `spec_ref` — a `spec_id` from [02-data-and-representation.md](02-data-and-representation.md).
- `assertion` — computable predicate over the spec's output. Initial admissible kinds: `in_range(lo, hi)`, `quantile_ge(p, threshold)`, `sign(expected_sign)`. New kinds may be added at M2a if they pass meta-validation.
- `scope` — structured filter over raw-store entries (entities, time range, partition). Computable, not free-text.
- `observation_window` — frozen `(t0, t1)` on which the assertion was originally observed. Folded into `pattern_id`.
- `replication_protocol` — pre-committed held-out window selection rule and pass threshold. See [04-empirical-test.md](04-empirical-test.md).

`pattern_id = sha256(canonical_body_with_op_versions_folded_in)`. The Pattern is an inert data object; nothing about it implies a trade.

## The loop

```
Discover → Originality filter → EmpiricalTest → Council → Archive
                                                       ↘ Reject (logged, not archived)
```

### 1. Discover — tool-using agent loop

Implemented as an agent loop, not a single-shot prompt. A single-shot LLM has no path to see data, compute over it, or refine a candidate based on what it sees, and so produces guesses rather than observations.

**Tool surface** (over the access layer):
- `inspect_spec(spec_id) → {description, sample_distribution, cost_estimate}` — small statistical summary on a sample window. Read-only.
- `compute(spec_id, window) → {summary_stats, sample_values}` — run a spec on a window. Bounded by per-call cost ceiling.
- `propose_spec(body) → spec_id` — register a new spec via the feature contract. Content-addressed.
- `test_assertion(spec_ref, assertion, window) → {result, fingerprint}` — evaluate without committing.
- `submit_pattern(pattern_body) → pattern_id` — commit a candidate.

**Cost discipline.** Each cycle has a hard `$B`-fraction cap (initial: ≤ 5% weekly). Cheap-then-expensive ordering is the agent's responsibility.

**Operator co-research.** Inputs only via the two shapes in [../Objective.md](../Objective.md) §4 (tool requests / red-team requests). Discover's input layer mechanically rejects content-shaped suggestions where vocabulary detection works (denylist of named-pattern terms); inputs that pass the filter but still violate §0a are caught later via the bias log.

**Anti-pattern list.** A bounded, mutable, purely subtractive set of computable matchers against Pattern fingerprints, derived from observed replication failures in this methodology's own history. Entries that don't predict failure are removed at M2a; if meta-validation finds the list net-harmful, it is emptied. (The M1 paradox — an anti-list is still a list — is admitted, not dissolved: the list is data-derived, mutable, subtractive, and bounded.)

**Rationale handling.** The agent may emit free-text rationale; rationale is logged but **withheld from Council** to prevent contagion. Council reasons from the assertion, the fingerprint, and the EmpiricalTest report.

### 2. Originality filter

Mechanical reducibility check against the anti-pattern list. Matcher accepts or rejects based on fingerprint, not LLM judgment.

### 3. EmpiricalTest

Per [04-empirical-test.md](04-empirical-test.md). Replication on held-out windows + perturbation controls + partition robustness.

### 4. Council

Per [05-council.md](05-council.md). ≥ 2 measurably-independent approvals.

### 5. Archive

Append-only. A Pattern that fails future re-replication is *annotated* with a new record; the original archive entry is never edited.

## Rules

- **No operator-targeted Patterns.** Co-research is tool requests and red-team requests only. Bias log captures the urges that don't enter the system.
- **No-Pattern is a valid output.** Empty cycles are logged; their frequency is itself a meta-validation signal.
- **Unfamiliarity is not a gate.** A Council-approved Pattern with an unrecognized fingerprint is the expected output of a working system, not a bug.
- **Familiarity is not a gate.** A Pattern that resembles a published claim is not rejected on grounds of resemblance. Replication and council determine archive entry.

## Cost discipline

Cheaper model for tool-call iteration; frontier model only for final submission. EmpiricalTest precedes Council. Council caches by `(pattern_hash, empirical_test_hash, member_version)`. If realized cost per archive entry trends above budget, Discover throttles before the operator is asked for more — the loop slows, it does not silently eat the envelope.

## Per-cycle log

For each candidate: stage reached, gate failed (if any) with the failing statistic, audit record hash chain back to inputs, and the agent's tool-call trace (so the operator can audit *how* a candidate was derived). No Pattern "almost passed."
