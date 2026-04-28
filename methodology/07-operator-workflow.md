# §6.7 Operator Workflow

The workflow is small because there is no live trading, no kill switch, no execution to monitor.

## Daily — typically zero touch

The system runs Ingest, scheduled Discover cycles, and Audit on its own schedule. If a stage's invariant fails, Audit emits an `InvariantViolation` record and the affected stage halts. The operator is notified and resolves before the next scheduled cycle.

## Weekly cycle (≤ 30 minutes)

1. **Read the cycle log.** Discover cycles run, Patterns proposed, stage reached, archived count. Read; do not re-evaluate.
2. **Read newly archived Patterns.** Browse the new corpus entries. Do not "approve" — Council already did. Read for understanding.
3. **Submit the bias log entry.** One free-text line capturing any moment this week the operator was tempted to (a) type a content-shaped suggestion into Discover, (b) argue with a Council rejection, (c) add a Pattern from outside reading, (d) retire a Pattern because it looks "wrong." If nothing to note, write `none`. Empty is refused — `none` and missed weeks are different.
4. **Acknowledge envelope status.** Read `$_spent / $B`. Halt new cycles if a budget is overrun.

## Quarterly (M2a) cycle — ~½ day

1. **Architecture review.** Read the architecture diff Council produced. Execute or reject as a single all-or-nothing change.
2. **Meta-validation.** Run the protocol's meta-validation per [04-empirical-test.md](04-empirical-test.md). Swap protocol if a challenger dominates.
3. **Council membership review.** Read the independence audit and per-member calibration; rotate if indicated.
4. **Anti-pattern list review.** Empty if meta-validation rejects its utility.
5. **Bias log review.** A Council instance — *not* the operator — reads the bias log entries since last M2a and produces a drift report. The operator reads the report. (Reading one's own bias log invites self-justification.)
6. **Clock health snapshot.** Read `t/T`, `$_spent/$B`, archive-entry count vs. `N_min`. Decide whether to invoke relax or abandon per [08-falsification-clock.md](08-falsification-clock.md).

## Degraded mode

Operator misses heartbeats for `N` consecutive days (initial `N=7`):
- Discover halts new cycles.
- Ingest, Represent, Audit continue. No data lost.
- Council and EmpiricalTest finish in-flight Patterns then idle.
- On return, an explicit "audit-gap ack" is required before Discover resumes — the operator reviews the gap-period audit records and acknowledges. Friction by design.

No live trading means no positions to close, no orders to cancel, no exposure to manage during degraded mode.
