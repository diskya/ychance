# §6.9 Audit Trail Specification

A specification, not a hypothesis. The trail exists for (1) operator-discipline visibility at M2a, (2) methodology self-improvement (meta-validation, independence audits, architecture diffs all read it), (3) reproducibility (any archive entry must be reconstructable from raw data and the chain).

The trail is **append-only** and **content-addressed**. No record is ever edited. Corrections are new records referring to the original by hash.

## Storage

- One JSON Lines file per calendar day. Each line has `record_hash` (sha256 of the canonicalized line minus the hash field) and `prev_hash` (previous record's hash). Tampering invalidates every subsequent hash.
- Files rotate at midnight UTC; an end-of-file record carries the chain into the next day's first record.
- Operator-local with at least one off-site backup. Cost is part of `$B`.

## Common record fields

Every record carries `timestamp`, `record_id` (UUID), `record_hash`, `prev_hash`, `category`, `stage`, an `envelope` (any of `pattern_id` / `cycle_id` / `m2a_id`), and a category-specific payload.

## Record categories (general contract)

Each stage contributes its own category. Payloads are defined when the stage is built, but every category must include enough to fully reconstruct the stage's decision from raw-store inputs and prior records — no un-logged inputs, no silent state.

Currently-built categories:
- **Ingest** — `source_id`, `vendor_timestamp`, `fetch_time`, `bytes_hash`, `bytes_size`, `provenance`.
- **Represent** — `spec_id`, `spec_version`, `input_bytes_hashes`, `output_tensor_hash`, `compute_cost`, `llm_cost` (if any).
- **CostDrift** — `spec_id`, `node_id`, `declared_cost_usd`, `realized_cost_usd`, `cost_tolerance`, `model_id`. Emitted on `llm_call` realized-cost overrun.

To-be-built categories (Discover, EmpiricalTest, Council, Archive, Operator weekly/M2a, M8 clock, Architecture) — payloads will be defined alongside their stage implementations and must satisfy the general contract above.

## Operator records — load-bearing under §0a

Two operator categories are defined now because they are the §7 defense and need their contract before Discover ships:

- **Weekly** — `timestamp`, `bias_log_entry` (verbatim, mandatory; `none` is a valid value, empty is not), `cycle_log_acked`, `archive_browsed_count`, `envelope_status_acked`.
- **Co-research input** — every operator input to Discover, with `input_text`, `shape_classification` (`tool_request` / `red_team_request` / `flagged`), and the agent's response.

## Retention

- Audit trail: duration of the active M8 clock plus ≥ 1 year after exit.
- Raw-store bytes: full audit-trail window. Deletion before is a §7 violation requiring documentation.

## Integrity checks

- **Daily**: hash chain verified on the day's file at the next cycle open; a break halts Discover until resolved.
- **Weekly**: cross-file continuity check.
- **M2a**: full log replay — a random subset of archived Patterns is re-derived from raw-store inputs. Mismatches indicate either a reproducibility bug or un-logged input. Both are defects.

## What the trail does not store

API keys (referenced by key-id only); personally identifying material beyond the operator's own identity; third-party user data.

## Operator-facing views

- **Weekly pane**: this week's cycles, archived Patterns, EmpiricalTest results, invariant failures, bias-log prompt.
- **M2a pane**: per-Pattern lifecycle since last M2a, architecture diffs, clock health, bias-log drift report, council membership audit.

The operator reads. The operator does not edit. Trail is ground truth; if it disagrees with memory, memory is wrong.
