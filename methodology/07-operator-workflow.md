# §6.7 Operator-Facing Workflow

## Status
Initial hypothesis under M9. The workflow must be executable by one person within §2 bandwidth, including a degraded mode when the operator is unavailable.

## The operator's job in one sentence

**Run the loop; don't substitute for the loop.** Clear the queue, fire the gates, log the events, hold the kill switch. Nothing more.

## Daily cycle — ~15 minutes

Target frequency: every trading day the operator is available. Missing a day is not a crisis (Execute has order-of-the-day logic; missing days beyond the degraded-mode threshold triggers the auto-exit below).

Steps (order matters):

1. **Kill switch status check.** Confirm kill switch is in the intended state. If the operator cannot remember setting it, assume it is wrong and re-declare explicitly.
2. **Audit pane glance.** Open [09-audit.md](09-audit.md)'s viewer. Look for:
   - Un-ack'd pipeline errors (any stage that failed its invariant).
   - Envelope overrun flags on `E_ops`.
   - Retire events since last check (just note them; do not second-guess).
3. **Execute queue clearance.** Confirm pending orders for the day match live rules' firings under current `C`. This is a **gate check**, not a review of the rules.
   - Green: queue fires cleanly → approve.
   - Amber: a broker-side issue (credit, symbol halt, capability issue) → log and skip affected orders; the affected rule will either Retire or survive on subsequent cycles.
   - Red: queue disagrees with logged rule state → halt Execute, escalate to weekly-review state, do not place any orders until resolved.
4. **Envelope touchpoint.** Check `E_ops` burn rate vs. plan. If overrun-projected, Audit should already have flagged it; confirm and let the automatic throttle do its job.

## Weekly cycle — ~2 hours

Target frequency: once per week, same day each week, pre-committed.

Steps:

1. **Retire review.** For each Retire event since last week, read the Retire record. Confirm the trigger condition matches the Retire rule in [03-discovery-loop.md](03-discovery-loop.md). Do **not** re-evaluate whether the rule should have been retired.
2. **Graduate approval (gate check only).** For each Graduate candidate since last week:
   - Confirm Validate output exists and is within pre-committed thresholds.
   - Confirm Council has ≥2 *independent* approvals per [05-council.md](05-council.md).
   - Confirm sizing from [06-sizing-risk-portfolio.md](06-sizing-risk-portfolio.md) fits current `E_cap` and correlation clamp.
   - If all gates fired, approve. **Do not read the rule's grounding in hope of agreeing with it.** §7 again.
3. **Paper-deploy review.** Confirm Paper-deploy duration requirements are being respected; confirm Observe is running distribution-match tests.
4. **Meta-pane glance.** Check the meta-validation running tally (see [04-validation.md](04-validation.md)) — is it populating? Are there signals of a protocol mismatch?
5. **Operator-bias log entry.** Write one line in a personal log: any moment in the past week when the operator was tempted to override a pipeline decision. This log is not seen by the Council; it exists to surface §7 re-insertion attempts at M2a.

## Quarterly cycle (M2a) — ~1 day

Target frequency: every 3 months, plus unscheduled triggers (drawdown breach, M8 relax path invocation, independence-audit pair collapse, systematic Observe-vs-Validate miscalibration).

Steps:

1. **Architecture review.** Council instances (rotated, distinct from the deploy-decision council) propose diffs to [01-architecture.md](01-architecture.md). Red-team each proposal. Operator executes the winning proposal; operator does not propose.
2. **Meta-validation of the validation protocol.** Per [04-validation.md](04-validation.md). Replace current protocol if a challenger strictly dominates.
3. **Originality-filter review.** The anti-pattern list in [03-discovery-loop.md](03-discovery-loop.md) is re-derived from the last cycle's statistics. Entries added, entries removed, entries re-weighted.
4. **Council membership review.** Independence audit ([05-council.md](05-council.md)); calibration test; member rotations.
5. **Sizing / partition re-declaration.** Re-declare `E_cap` / `E_ops` / `E_res` partition. Re-declare sizing function, drawdown ceilings, correlation clamp.
6. **Tax-model recalibration.** Compare realized tax on closed positions to the model; re-fit.
7. **M8 clock check.** Time remaining on `T`, spend remaining of `$B`. If the clock is near expiry and no success, read [08-falsification-clock.md](08-falsification-clock.md) and decide on relax or abandon.
8. **Operator-bias log review.** Read the personal bias log; any pattern of near-override is itself a Council audit input on whether operator discipline is holding.

## Degraded mode (M9)

Triggered by: operator heartbeat absent for `N` consecutive days (initial hypothesis, revisable: `N = 5`). The operator heartbeat is an explicit daily ack in the Audit log; no ack = no heartbeat. Clock-based inference (weekend, known holiday) does not count.

On trigger:
1. Execute auto-closes all live positions per each rule's `X` or, if `X` is not immediately firable, a pre-committed retirement-exit policy (typically: market-close next available session, taking the spread).
2. Propose, Screen, Validate, Council, Paper-deploy, Graduate all halt.
3. Ingest, Represent, Audit continue so no data is lost.
4. When the operator returns, the operator:
   - Ack's the audit gap.
   - Runs a full weekly cycle regardless of day-of-week.
   - Restarts Propose manually. Live re-deployment requires full Propose→Graduate passage for every rule; no rule is simply "un-paused."

Degraded mode is **safe by default and expensive by design** — it is meant to be unpleasant enough to deter overuse, but automatic enough that an unexpected incapacitation does not destroy capital.

## What the operator is never asked to do

- Choose which rule to deploy from a list of candidates.
- Override a Retire trigger to keep a rule alive.
- Size a rule, adjust a sizing function, or rebalance between rules mid-cycle.
- Propose edges from outside reading, from intuition, or from memory of past trades.
- Accelerate Graduate by shortening Paper-deploy.
- Delay Retire because "maybe it will come back."

Each of these is an instance of §7 re-insertion and is a discipline violation regardless of whether it would help in a specific case.

## Bandwidth budget

Target: ≤ 15 min/day + 2 hr/week + 1 day/quarter ≈ 5–7 hr/week average excluding quarterly days. If realized bandwidth exceeds this target sustainedly, the methodology is failing its §2 obligation and the excess is a Review input: either operator behavior is re-inserting human judgment (a §7 failure) or the pipeline is asking too much of the operator (an M9 failure surfaced at M2a).
