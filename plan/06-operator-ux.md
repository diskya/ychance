# Phase 5 — Operator UX

**Goal**: weekly pane, M2a pane, bias log, archive browser per [../methodology/07-operator-workflow.md](../methodology/07-operator-workflow.md). No kill switch, no degraded-mode trade halting — there is no live trading under v3.0.

## Dependencies

[03-council.md](03-council.md) complete; the pipeline produces archived Patterns end-to-end.

---

## 5.1 Weekly pane — **[M]**

> Build a CLI or simple localhost TUI. The weekly view:
> - **Cycle log**: this week's Discover cycles, Patterns proposed, stage reached, archived count.
> - **New archive entries**: browsable list. Each shows `pattern_id`, `spec_ref`, `assertion`, `scope`, `observation_window`, EmpiricalTest verdict, council vote summary; click for full provenance chain.
> - **Invariant failures**: read-only.
> - **Envelope status**: `$_spent / $B`, projected runway, ack button.
> - **Bias-log textarea**: prompt *"Any moment this week the operator was tempted to override the pipeline? If nothing to note, write 'none'."* Empty submission refused.
>
> Every action writes an Operator weekly record per [../methodology/09-audit.md](../methodology/09-audit.md).

## 5.2 Archive browser — **[M]**

> Read-only browser over the Pattern corpus. Filterable by `spec_ref`, `scope`, archive date, re-replication status. Detail view shows full body, observation window, EmpiricalTest report, council votes (rationales redacted from operator UI to prevent contagion — available in audit log for the M2a Council bias-log review).
>
> The UI must not contain any "remove from archive" or "annotate as wrong" affordance. If a Pattern fails re-replication, the system appends an annotation; the operator does not.

## 5.3 M2a pane — **[M]**

> Quarterly view:
> - Architecture-diff viewer (read M2a Architecture records).
> - Meta-validation result from EmpiricalTest's meta-validation (null-op early in the clock).
> - Council membership review: independence audit classification, per-member calibration.
> - Anti-pattern list track record.
> - Bias-log drift report (produced by a Council instance — operator reads the report, not raw entries).
> - Clock-health snapshot: `t/T`, `$_spent/$B`, archive count, re-replicated count, originality-cleared count, projection vs. `N_min`.
>
> Consult-only. Architecture changes are all-or-nothing accept/reject of Council's diff.

## 5.4 Bias log — **[S]**

> Implement the textarea on the weekly pane (5.1). One line per week, free text. `none` is required if nothing to note; empty refused. Logged as an Operator weekly record.
>
> Reviewed at M2a by a Council instance, *not* the operator. The Council reading is itself audited.

---

## Exit criteria

- Weekly cycle runs in ≤ 30 minutes on the pane without leaving it.
- Archive browser is genuinely read-only (static-analysis test enforces no edit/remove affordances).
- An attempted content-shaped suggestion in Discover's co-research interface is mechanically rejected with a logged `shape_classification: flagged` entry; the UX displays its log.
- Bias log refuses empty submissions.
- M2a pane reads bias-log drift reports correctly and surfaces clock health.
