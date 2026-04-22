# Phase 9 — Operator UX

**Goal**: the three panes, kill switch, heartbeat, degraded-mode automation, and bias log — everything in [../methodology/07-operator-workflow.md](../methodology/07-operator-workflow.md). This is the interface through which the operator executes the workflow without re-entering human discretion into the loop.

## Dependencies
- [05-execution.md](05-execution.md) is complete. The pipeline has live and paper paths, audit is working, every stage emits records.

## Parallelism
- 9.1, 9.2, 9.3, 9.4 are largely independent after scaffolding is chosen. 9.2 is the blocker for any live activity.

---

## 9.1 Three panes — **[M]**

> Build an operator-facing CLI or TUI (recommend Textual or a simple Flask+HTMX localhost app — whichever keeps shipping velocity high) with three panes per [../methodology/07-operator-workflow.md](../methodology/07-operator-workflow.md):
>
> ### Daily pane
> - Kill-switch state (big, obvious, colored).
> - Un-ack'd pipeline errors (any stage that failed its invariant).
> - Envelope overrun flags on `E_ops`.
> - Retire events since last check (read-only — note, do not second-guess).
> - Execute queue clearance: green / amber / red per [../methodology/07-operator-workflow.md](../methodology/07-operator-workflow.md) daily cycle.
>
> Every operator action here writes an Operator record (daily-heartbeat category) to audit.
>
> ### Weekly pane
> - Retire-review queue: each Retire record summarized, with the trigger field prominent. Operator confirms *the trigger fired correctly* — no override of the retirement itself.
> - Graduate-approval queue: gate-check only. Display should show **which gates fired**, not the rule's rationale or grounding narrative. Showing narrative invites re-evaluation, which is §7.
> - Paper-deploy status summary.
> - Meta-pane: meta-validation tally populating? calibration + discrimination signals?
> - Bias-log prompt (see 9.4).
>
> ### Quarterly (M2a) pane
> - Architecture-diff viewer (read Review records from [../methodology/09-audit.md](../methodology/09-audit.md) §"Architecture records").
> - Meta-validation result (from [02-discovery-loop.md](02-discovery-loop.md) §4.3).
> - Council membership review (independence audit classification, per-member calibration from [03-council.md](03-council.md) §5.4).
> - Partition re-declaration form: `E_cap` / `E_ops` / `E_res`, per-rule-clock defaults.
> - Tax-model recalibration report.
> - Clock-health snapshot: `t/T`, `spent/$B`, live rules, paper-deploys, graduated. Per live rule: per-rule-clock remaining; during sim phase, months-to-`K_live` in sim; during Phase 11, current `live_fraction` + position on ramp schedule + (post-ramp) months-to-`K_live_real`.
> - Bias-log period review (reads all weekly bias entries since last M2a).

## 9.2 Kill switch — **[S]**

> Implement a kill switch accessible from the daily pane AND from a CLI command (so the operator can hit it from any terminal, including degraded-network conditions). State is a single atomic file with a mandatory `reason` string on every state change. Execute ([05-execution.md](05-execution.md) §8.2) reads this on every submit and every market-data tick. Every toggle is logged to audit per [../methodology/09-audit.md](../methodology/09-audit.md) §"Operator records" (kill-switch-toggle category).
>
> During the sim clock (all rules at `live_fraction = 0`), the kill switch halts simulated order submission and triggers `X` on simulated positions. During Phase 11, it additionally halts the real route and calls `X` on real positions. Same code path for both routes, same discipline — practicing the switch on the sim is what makes it reliable when real money is wired in.

## 9.3 Heartbeat + degraded mode automation — **[M]**

> Implement `heartbeat/`:
>
> - Requires an operator ack on the daily pane. Clock-based inference (weekend, known holiday) **does not** count as a heartbeat — an explicit ack is required on every business day.
> - After `N` consecutive missed days (initial `N=5`, config-driven), trigger degraded mode per [../methodology/07-operator-workflow.md](../methodology/07-operator-workflow.md) §"Degraded mode":
>   1. Auto-close all live positions via each rule's `X`, or fallback to broker market-close-next-session if `X` is not immediately firable.
>   2. Halt Propose / Screen / Validate / Council / Paper-deploy / Graduate stages.
>   3. Keep Ingest / Represent / Audit running so no data is lost.
> - On operator return, require an explicit "audit-gap ack" (operator reviews the gap period's audit records and acknowledges) before any stage past Audit re-runs. After ack, a full weekly cycle is forced regardless of day-of-week. Live re-deployment requires a full Propose → Graduate passage for every previously-live rule — nothing is simply "un-paused."
>
> Degraded mode is safe by default and deliberately expensive to exit (to deter overuse).

## 9.4 Bias log — **[S]**

> Implement a single-textarea "weekly bias log" form on the weekly pane. Entry is one line per week: any moment the operator was tempted to override the pipeline (override a Retire, cherry-pick a rule to Graduate, resize a position, propose an edge from outside reading). Logged to audit as an Operator record (weekly-review category, `bias_log_entry` field).
>
> This log is a §7 defense — the log is reviewed at M2a by a Council instance, not by the operator. A Council instance reading the bias log can spot patterns of drift the operator cannot self-diagnose. Include a prompt hint on the form: *"If nothing to note this week, write 'none' — empty submissions are treated as a missed log, not as 'nothing happened.'"*

---

## Exit criteria for this phase

- Full daily cycle (per [../methodology/07-operator-workflow.md](../methodology/07-operator-workflow.md)) runs in ≤ 15 minutes on the daily pane without needing any CLI outside the pane (kill-switch CLI is a backup, not a daily path).
- Heartbeat miss test: fake `N+1` missed days in a test environment, confirm degraded mode triggers exactly as specified and that recovery requires the documented ack sequence.
- Operator actions that could re-insert judgment (Retire override, Graduate reject-despite-gates-green, manual resize) are **not available** in the UI. If they exist in the code, remove them — the UI must not make §7 violations easy.
- Weekly bias-log prompt has shipped at least one entry to audit in a test run; M2a pane can read the log.
