# Phase 0 — Operator Decisions (no code)

Fix the parameters that §2 left TBD. No agent can do this.

## Decisions

| Decision | Notes |
|---|---|
| `E` — total envelope | Single pool: LLM API + market-data fees + compute + storage + backups. Suggested $15K–$25K for first 12-month clock. No trading-capital component. |
| `T` — clock duration | 12 months default (range 6–18). Pre-committed; not extensible mid-clock. |
| `N_min` — archive success threshold | 5 council-approved, replication-tested, originality-cleared Patterns. |
| `K_replicate` — re-replication window | 3 months between archive entry and the fresh-window re-test. |
| Data scope | A single concrete domain narrow enough to ship a Discover loop in a few weeks. Currently committed: SEC EDGAR submissions (free, keyless). |
| LLM vendor families | ≥ 2 distinct families for Council. Shortlist three so one can rotate without dropping below two. Count training pipelines, not products. |
| Stack | Python 3.12 on the operator's VM with off-site backup of raw store and audit log. |

## Output

A single `config/envelope.yaml` committed before code work begins; audit references its hash. Schema:

```yaml
envelope:
  total_usd: <number>            # e.g., 15000

clock:
  T_months: <int>                # e.g., 12
  budget_usd: <number>           # $B, subset of envelope.total_usd
  N_min: <int>                   # e.g., 5
  K_replicate_months: <int>      # e.g., 3
  relax_allowance: 1

data_scope:
  primary_domain: <string>
  shortlist_extensions: [<string>, ...]

llm_families: [<vendor_a>, <vendor_b>, <vendor_c>]

stack:
  language: python
  version: "3.12"
  storage:
    raw_store_path: <path>
    audit_log_path: <path>
    backup: <off-site location>
```

### Budget invariant

`envelope.total_usd` must cover the projected weekly Discover-cycle cost over `T_months` with ≥ 25% slack for unscheduled triggers. If projection exceeds the envelope: lower cycle frequency, reduce `T`, or raise `E`.

## Discipline

- The partition declared here is a hypothesis frozen for the first clock; M2a may revise.
- If the operator wants to change scope or LLM families *because of outside reading*, log the temptation in the bias log. Keep the decision.
- No decisions about *what patterns to look for* belong here. Any such ranking violates §0a / M1.
