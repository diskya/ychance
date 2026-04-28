# §6.5 Adversarial Council Protocol

Initial hypothesis under M7. The council turns a single AI's output into a measurably-independent multi-opinion signal. **Independence is measured, not asserted** — agreement from models sharing training corpora counts as one voice.

## Composition

- **≥ 2 distinct vendor families** at all times. A "family" is a frontier model line from a demonstrably distinct training pipeline.
- A third family added when budget allows; rotating one out for evaluation is an M2a event.
- The label "family" is a hint; the *test* is the independence audit below.

Council membership is versioned. Rotation, retirement, or model-version updates are M2a events.

## Inputs to each member

- Pattern body in canonical form: `(spec_ref, assertion, scope, observation_window, replication_protocol, pattern_id)`.
- EmpiricalTest report in full.
- A sampled raw-data window for independent re-computation of the assertion.

Withheld:
- Discover agent's free-text rationale (prevents rationale contagion — Council reasons from assertion + evidence, not from the agent's argument).
- Other members' votes or rationales (sealed until collection).
- Identity of the proposing agent or model (prevents in-family credulity).

## Output from each member

`vote ∈ {approve, reject}`; rationale (verbatim); key-evidence citations.

## Decision rule

- Archive iff ≥ 2 `approve` votes from members the most-recent independence audit classifies as mutually independent.
- A single `reject` from an independent member blocks archive entry, even when ≥ 2 approvals exist elsewhere. Disagreement in an independent panel is high-information.
- Blocked Patterns are logged with blocking rationales; not auto-resubmitted.

## Independence audit

Run at M2a and on unscheduled trigger if archived Patterns systematically fail re-replication.

1. Collect all `(pattern, member, vote, rationale)` tuples since last audit.
2. Embed each rationale under a model **not in the council** (defensive diversity).
3. Compute pairwise cosine similarity for the *same Pattern* across council members.
4. For each pair: independence score = `1 − mean(same-pattern rationale similarity across all common patterns)`.
5. A pair below pre-committed `θ_indep` is **collapsed** — combined vote counts as one. Reported; replacement family considered next M2a.

The audit measures similarity of *reasoning*, not of outcomes. A pair that reliably disagrees on rationale but converges on the final vote counts as two voices.

## Calibration

Independence alone does not guarantee usefulness. A member whose approvals systematically fail re-replication is re-weighted to zero at next M2a, regardless of independence. Calibration is measured on the member's own approve-votes, not on the aggregate.

## Cost discipline

- **Cache by content.** `(pattern_hash, empirical_test_hash, member_version)` triple cached; re-query only on Pattern change, EmpiricalTest re-run, or partition-shift flag.
- **Two-phase query.** A short "screening query" returns `approve` / `reject` / `need full review`. Only the third triggers full rationale generation. Screening responses also cached.
- **Budget throttle.** Council defers candidates to the next cycle rather than reduce panel size mid-cycle (which would compromise the decision rule).
