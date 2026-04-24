# §6.9 Audit Trail Specification

## Status
A specification, not a hypothesis. The audit trail exists for three reasons, in order of priority:

1. **Regulatory defense**: if a regulator asks why a given trade was made, the audit trail reconstructs the full causal chain from raw data to order.
2. **Operator discipline (§7)**: operator re-insertion is invisible without a log. The audit trail makes it visible at M2a.
3. **Methodology self-improvement**: every meta-validation, every independence audit, every M2a architecture diff reads the audit log as its primary input.

The audit trail is **append-only** and **content-addressed**. No record is ever edited. Corrections are new records referring to the original by hash.

## Storage

- Append-only files, one per calendar day, JSON Lines.
- Each line is a record with a `record_hash` (sha256 of the canonicalized line minus the hash field itself).
- Each record has a `prev_hash` field — the hash of the previous record in the same file. This chains records; tampering with a single record invalidates every subsequent hash in the file.
- Files are rotated at midnight UTC. End-of-file record carries the chain into the next day's first record.
- Storage is operator-local with at least one off-site backup. Cost is part of `E_ops`.

## Record categories

Every record has: `timestamp`, `record_id` (UUID), `record_hash`, `prev_hash`, `category`, `stage` (one of the stages in [01-architecture.md](01-architecture.md)), `envelope` (subset of: `rule_id`, `cycle_id`, `m2a_id`), and a category-specific payload.

### Ingest records
- `source_id`, `vendor_timestamp`, `fetch_time`, `bytes_hash`, `bytes_size`, `provenance` (full triple).

### Represent records
- `feature_spec_version`, `input_bytes_hashes`, `output_tensor_hash`, `compute_cost`, `llm_cost` (if any).

### Propose records
- `rule_id` (new), `rule_object` (full executable `(C, A, H, X)`), `grounding` (full `G(R)`), `free_text_rationale`, `model_version`, `prompt_hash`, `input_slice_hashes`, `llm_cost`.
- **Free-text rationale is logged but withheld from Council** (see [05-council.md](05-council.md)). The log stores it; the pipeline gates do not route it.

### Originality-filter records
- `rule_id`, `result` (pass / reject), `matched_anti_pattern` (if reject), `anti_pattern_list_version`.

### Screen records
- `rule_id`, `screen_window`, `statistics` (all of them, not a summary), `pass/fail`, `compute_cost`.

### Validate records
- `rule_id`, `validate_protocol_version`, `windows_used` (with proof of disjointness from Screen windows), `utility_distribution`, `challenger_reports`, `robustness_profile`, `partition_profile`, `compute_cost`, `llm_cost`.

### Council records
- One record per member per rule:
  - `rule_id`, `member_id`, `member_version`, `vote`, `rationale` (verbatim), `key_evidence_citations`, `llm_cost`.
- Plus one **decision record** aggregating the member records: `rule_id`, `decision` (approve/reject), `independent_approver_member_ids`, `decision_rule_version`.

### Paper-deploy records
- Session-level: `rule_id`, `paper_deploy_id`, `start_time`, `end_time`, `size_function_version`.
- Per-tick / per-firing: `rule_id`, `paper_deploy_id`, `firing_time`, `C_value` (boolean + the values `C` consumed), `A_value`, `position_after`, `paper_cost_model_version`, `realized_paper_pnl_contribution`.

### Observe records
- `rule_id`, `window`, `realized_vs_predicted_test`, `distribution_match_statistic`, `correlation_vector` (with every live rule), `partition_tag_performance`.

### Graduate / Retire records
- **Graduate**: `rule_id`, `size_allocated`, `gates_fired` (with references to the specific Validate/Council/Observe records that satisfied each gate), `operator_ack_record_id`.
- **Retire**: `rule_id`, `trigger` (one of: drawdown, distribution-mismatch, per-rule-clock-expiry, correlation-clamp, council-rereview-failure, infeasibility), `final_position_exit`, `post_mortem_reference`.

### Execute records
- Per order: `rule_id`, `order_intent`, `broker_order_id`, `submission_time`.
- Per fill: `broker_order_id`, `fill_time`, `price`, `quantity`, `fees`, `slippage_vs_paper`.
- Per rejection: `broker_order_id`, `rejection_reason`, `operator_notification_time`.

### Operator records
- Daily heartbeat: `operator_id`, `timestamp`, `acknowledgments` (kill-switch state, pending queue approval, envelope touchpoint).
- Weekly review: `timestamp`, `retire_events_reviewed`, `graduate_events_approved`, `bias_log_entry` (operator's personal near-override log entry for the week, verbatim).
- M2a quarterly: `timestamp`, `architecture_diff_hash`, `meta_validation_result`, `membership_changes`, `partition_redeclaration`, `tax_model_recal`, `clock_health_snapshot`, `bias_log_period_review`.
- Kill switch toggle: `timestamp`, `new_state`, `reason` (free text, mandatory, logged verbatim).

### M8 clock records
- Per clock start: `clock_id`, `T`, `$B`, `K_live`, `relax_allowance`.
- Per relax invocation: `clock_id`, `clause_relaxed`, `rationale`, `council_approval_record_ids`.
- Per clock exit: `clock_id`, `exit_type` (success / abandon), `success_rule_id` (if success), `abandon_action` (cash / human-curated-alternative, if abandon).

### Architecture records
- Per M2a diff: `m2a_id`, `architecture_version_before`, `architecture_version_after`, `diff`, `red_team_council_record_ids`, `decision`, `rationale`.
- Per out-of-cycle trigger: same fields plus `trigger_event_record_id`.

## Retention

- **Full audit trail**: retained for the duration of the active M8 clock plus at least 2 years after the clock exits.
- **Jurisdiction-specific extension**: whatever the operator's tax and securities regulations require as a minimum, with 2 years added for a safety margin.
- **Raw-store bytes**: retained for the full audit-trail window. Deletion before the window ends is a discipline violation (§7) and requires operator documentation.

## Audit-trail integrity checks

- **Daily**: hash chain of the current day's file is verified on daily-cycle open; a break halts Execute until resolved.
- **Weekly**: cross-file hash continuity check.
- **Quarterly (M2a)**: full log replay — a subset of rules is picked at random, and the pipeline is re-run from raw-store inputs to see that the same decisions emerge. Mismatches indicate either a reproducibility bug (fix it) or a pipeline that depends on an un-logged input (fix the pipeline).

## What the audit trail does not store

- No secrets in plaintext (API keys, broker credentials). Those are referenced by key-id.
- No personally identifying material beyond the operator's own identity.
- No third-party user data. (This methodology does not touch any.)

## Operator-facing views of the audit trail

- **Daily pane**: filtered to the current day's Execute, Observe, Retire, and any invariant-failure records.
- **Weekly pane**: current week's Graduate, Retire, Paper-deploy, and Observe summaries.
- **Quarterly pane**: per-rule lifecycle, architecture diffs, clock health, bias log compilation.

The operator reads these panes. The operator does not edit the trail. The trail is ground truth; if it disagrees with memory, memory is wrong.
