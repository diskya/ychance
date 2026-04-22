# §6.5 Adversarial Council Protocol

## Status
Initial hypothesis under M7. The council exists to turn a single AI's output into a measurably-independent multi-opinion signal. **Independence is measured, not asserted** — agreement from models sharing training corpora or embeddings counts as one voice.

## Composition

- **≥2 distinct vendor families** at all times, where a "family" is a frontier model line from a demonstrably distinct training pipeline (distinct vendor, distinct base model lineage).
- **Budget permitting**, a third family is added for decisions above a pre-committed capital-at-risk threshold.
- A "family" is a label; the *test* is the independence audit below. A label alone does not grant independence.

Council membership is versioned. Rotating in a new family, retiring a family, or updating any member's model version is a Review-stage event (M2a or a documented trigger).

## Inputs to each member

For each candidate rule `R`, each council member receives:
- The rule object `(C, A, H, X)` in executable form.
- The grounding `G(R)` — the empirical signature claimed to be exploited.
- The Validate output ([04-validation.md](04-validation.md)) in full: distributions, competitor reports, robustness profile, regime partition.
- A sampled raw-data window for independent re-computation of `G(R)`.

Deliberately withheld:
- The Propose-stage free-text rationale (prevents rationale contagion — Council must reason from grounding and evidence, not from the proposer's argument).
- Other council members' votes or rationales (votes are sealed until collection).
- The identity of the proposing model (prevents in-family credulity).

## Output from each member

- **Vote**: one of `approve`, `reject`.
- **Rationale**: free text explaining the vote. Rationales are logged verbatim and used by the independence audit (below).
- **Key-evidence citations**: references to specific Validate output elements and/or raw-data slices the rationale depends on. Used for downstream replay when a rule graduates/retires.

## Decision rule

- A rule may Graduate iff it has ≥2 `approve` votes *from members that the most-recent independence audit classifies as mutually independent*.
- A single `reject` from an independent member blocks Graduation even when ≥2 approvals exist elsewhere. (Rationale: disagreement in an independent-measured panel is high-information.)
- A rule with a council-block goes back to Propose with the blocking rationales; Propose may revise and resubmit, or retire the candidate.

## Independence audit

Run at Review (M2a) and on an unscheduled trigger if Observe shows Council approvals systematically overpredicting realized `U(R)`.

Procedure:
1. Collect all council (rule, member, vote, rationale) tuples since the last audit.
2. For each rationale, compute an embedding under a model **not in the council** (defensive diversity).
3. Compute pairwise cosine similarity of rationales for the *same rule* across council members.
4. For each pair of members, the **independence score** is 1 minus the mean same-rule rationale similarity across all common rules in the window.
5. A pair with independence score below a pre-committed threshold `θ_indep` is **collapsed** — their combined vote counts as one. Collapsed pairs are reported and a replacement family is considered at the next Review.

Agreement on *correct* rejections does not reduce independence by itself. The audit measures similarity of *reasoning*, not of outcomes. A pair that reliably disagrees on rule-by-rule rationale but converges on the final vote is counted as two voices.

## Calibration test

Independence alone does not guarantee usefulness. A Council member whose approvals systematically fail Observe (live-realized `U(R)` below predicted by Validate across approved rules) is re-weighted to zero at the next Review, regardless of independence from other members. Calibration is measured on the member's own approve-votes, not on the Council aggregate.

## Cost discipline

Council is expensive; the envelope makes this acute.

- **Cache by content.** A (rule, Validate output, member-version) triple is cached; re-query only on rule change, Validate re-run, or regime-change flag from Observe.
- **Two-phase query.** A short "screening query" to each member returns `approve` / `reject` / `need full review`. Only `need full review` triggers the full rationale generation. Screening-query responses are also cached.
- **Regime-change flag.** When a rule has been paper-deploy or live for long enough and Observe detects a regime shift (using the regime tags defined in [04-validation.md](04-validation.md)), a re-query is forced. Between such flags, cached decisions stand.
- **Budget throttle.** If Council spend for the cycle exceeds its `$B` allocation, Council defers candidates to the next cycle; it does not reduce panel size mid-cycle (reducing panel size mid-cycle would compromise the decision rule).

## Out-of-scope for Council

- **Council does not revise rules.** It approves or rejects; rewriting is Propose's job.
- **Council does not set sizing.** That is [06-sizing-risk-portfolio.md](06-sizing-risk-portfolio.md)'s job.
- **Council does not read the operator's preferences.** The operator has no seat on the Council. This is load-bearing — §7.

## Revision triggers

- Scheduled: Review (M2a) runs the independence audit and the calibration test; membership is adjusted accordingly.
- Unscheduled: systematic Observe miscalibration of approved rules; a council pair collapsing under an out-of-cycle audit; a vendor retirement or model-version change.
