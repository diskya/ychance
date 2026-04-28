# §6.8 Falsification and Termination Protocol (M8 Clock)

A commitment, not a hypothesis. Success, relax, and abandon are the only three legal exits.

## Pre-committed parameters (set once, at clock start)

| Parameter | Initial | Notes |
|---|---|---|
| `T` — clock duration | 12 months | Range 6–18 allowed |
| `$B` — clock spend budget | $15,000 | LLM + data + compute + storage |
| `N_min` — archive success threshold | 5 Patterns | All four success conditions below |
| `K_replicate` — re-replication window | 3 months | Months between archive entry and the fresh-window re-test |
| Relaxations allowed | 1 over `T` | One-way within a clock |

`$B` covers everything spent on the discovery loop. There is no trading capital.

`N_min = 5` is the bet that a system unable to produce 5 council-approved, replication-tested, materially-original Patterns in 12 months is not worth continuing at this scale. Re-settable only at the start of a fresh clock.

## Success criterion

The clock is met iff **at least `N_min` Patterns** in the archive satisfy *all* of:

1. **Council-approved** under [05-council.md](05-council.md) at archive time.
2. **Replication-tested** under [04-empirical-test.md](04-empirical-test.md) at archive time.
3. **Re-replicated** on a fresh held-out window selected `K_replicate` months after archive entry. The fresh window is deterministic given `pattern_id` and the replication protocol; this is a separate EmpiricalTest run, not a re-read of the archived report.
4. **Material originality.** Running the Pattern body through each independent Council family with only the prompt *"Does this assertion correspond to a well-known finding in published literature on this data domain?"* yields no converging affirmative across families at a pre-committed agreement threshold. If panels agree the Pattern is published, it does not count toward `N_min`.

The originality test is the §0a-respecting version of M8's "materially different" requirement: it does not name categories, does not impose a taxonomy, and runs on each Council family independently.

## Relax path

Up to one invocation over `T`:
1. Operator identifies one M-clause that appears binding.
2. Operator writes a documented rationale, logged in [09-audit.md](09-audit.md), naming the clause, the evidence, and the exact modification.
3. Council reviews; ≥ 2 independent approvals required.
4. On approval, the modified M-clause replaces the original for the remainder of `T`. No new `T` starts.

One-way within a clock — once relaxed, not re-tightened. A new clock starts only on full abandon-and-restart.

## Abandon path

Triggered when:
- `T` elapsed with archive-success count below `N_min` AND the single relax has been used or declined.
- `$B` exhausted before `T` with archive-success count below `N_min`.

On abandon, two documented choices, both terminating the methodology:
- **Stop.** Close the system, retain the archive. Framing falsified at current capability level. New M8 cycle attempt requires materially different methodology constitution after ≥ 3 month cool-off.
- **Hand off.** Pass the archive to whatever follow-on project the operator chooses. Any methodology built after abandon is not this methodology.

Silent continuation past `T` with no success and no relax and no abandon is a §7 violation. The clock is the point.

## Clock accounting

Every Audit record during `T` carries: `t/T`, `$_spent/$B`, archive-entry count, of-which-re-replicated count, of-which-cleared-originality count, and the projection toward `N_min`. The operator watches these at M2a. At `t = T/2` with zero archive entries, relax is probably warranted. At `t = 3T/4` with zero re-replicated entries, abandon is plausible. The judgment is *when* to invoke the formal path, not *whether* the clock applies.
