# §6.8 Falsification and Termination Protocol (M8 Clock)

## Status
Not a hypothesis — a commitment. Per M8, the discovery process itself has a terminating clock. Success, relax, and abandon are the only three legal exits from the clock.

## Pre-committed parameters (set once, at methodology start)

| Parameter | Initial value | Source |
|---|---|---|
| `T` — clock duration | 18 months (range 12–24 allowed) | M8 suggested |
| `$B` — clock spend budget | **$15,000** (subset of `E` and of `E_ops` over `T`) | Chosen so `$B ≤ E_ops` at operator-declared partition for the full `T` |
| `K_live` — minimum live-survival window for success | 3 months | Pre-committed |
| Relaxations allowed | 1 per quarter, total 1 over `T` | Keeps relax bounded |
| Success threshold count | ≥1 rule meeting the success criterion below | §1 framing — one is enough |

`$B` is **inclusive of all LLM inference, all data feeds, all compute, all broker fees** spent on the discovery loop. It does not include capital deployed into rules — that is `E_cap` in [06-sizing-risk-portfolio.md](06-sizing-risk-portfolio.md). It does include the cost of running Council, Propose, Validate, etc. `E_cap` can lose money through live trading and that loss is not charged to `$B`.

With `E` on the low end ($50K): `$B = $15K` is 30% of `E`, which is the ceiling of what the envelope tolerates while leaving meaningful capital for live trading and reserve. If the operator commits to `E = $50K` exactly, this is a binding constraint and the loop must be cost-disciplined from day one. On the high end ($100K), `$B = $15K` is 15% — more comfortable. The initial value is held at $15K because the methodology must be feasible at the low end of `E`.

## Success criterion

The M8 clock is met iff **at least one rule** satisfies *all* of:

1. **Deployed to live capital** under [06-sizing-risk-portfolio.md](06-sizing-risk-portfolio.md).
2. **Survived ≥ `K_live`** in the live book without Retire trigger firing.
3. **Generated risk-adjusted post-cost post-tax utility** above the best competitor ([04-validation.md](04-validation.md)) over the live window, with the dominance surviving the regime-tag partition.
4. **Material originality test.** Running the rule's `G(R)` through each independent Council family with only the prompt *"Which classical strategy category does this grounding correspond to?"* yields **no converging label** across families at a pre-committed agreement threshold. This operationalizes M8's requirement that the edge be "materially different from the union of published human-known edges" — if the independent Councils can't agree on a classical label, the rule is taken as not reducible to one.

If multiple rules meet the criterion, success is claimed once. The methodology does not compete with itself for a bigger success.

## Relax path

Up to **one** relax invocation over `T`. A relax consists of:
1. Operator identifies one M-clause (`M1` through `M9`) that appears to be the binding constraint.
2. Operator writes a documented rationale, logged in [09-audit.md](09-audit.md), naming the clause, the evidence that it is binding, and the exact modification.
3. Council reviews the rationale; approval requires ≥2 independent approvals per [05-council.md](05-council.md).
4. On approval, the modified M-clause replaces the original for the remainder of `T`. No new `T` starts; the clock continues.

Relaxations are **one-way** — once relaxed, the clause is not re-tightened mid-`T`. A new clock starts only on a full abandon-and-restart decision.

## Abandon path

Triggered when any of these is true at the end of `T`:
- `T` elapsed with no rule meeting the success criterion AND the single relax has been used.
- `T` elapsed with no rule meeting the success criterion AND the operator declines to relax.
- `$B` exhausted before `T` with no rule meeting the success criterion and no remaining budget to continue.

On abandon, the operator has two documented choices, both of which terminate the methodology as constituted:

- **Revert to cash**, close all live rules, and stop. The framing is falsified for the current AI capability level; the operator may attempt a fresh M8 cycle with materially different methodology constitution (a new Objective.md) after a cool-off of at least 3 months.
- **Revert to explicitly-human-curated alternative**, documented as such — not a continuation of this methodology. The operator is no longer running AI-native discovery; the abandon is acknowledged in full. Any methodology built after abandon is not this methodology and not bound by [../Objective.md](../Objective.md).

Silent continuation — running the loop past `T` with no success and no relax and no abandon — is a discipline violation (§7). The clock is the point.

## Clock accounting (how to tell where you are)

Each Audit record timestamped during `T` carries:
- Time elapsed (`t / T`).
- Spend to date (`$_spent / $B`).
- Live-rule count and their individual per-rule clocks.
- Count of rules that have cleared Paper-deploy.
- Count of rules that have reached live deployment.
- For each live rule: months-to-`K_live`.

These are the signals the operator watches quarterly (M2a) to judge clock health. At `t = T/2` with zero live rules, a relax is probably warranted. At `t = 3T/4` with zero Paper-deploy clears, abandon is plausible. Thresholds for acting are not pre-set — judgment here is the operator's, but the judgment is *when to invoke the formal relax/abandon path*, not *whether the clock applies*.

## What the clock does not do

- It does not declare failure on a single bad cycle. The clock is about the whole `T`.
- It does not declare success on a backtest. Only live performance counts.
- It does not silently extend itself. `T` is `T`. A longer `T` starts a new clock; it is not an extension.

## Revision triggers

- Once only, at methodology start: `T`, `$B`, `K_live`, relax count are set.
- Each quarterly M2a: the clock's burn-rate and health are reviewed, but the parameters are not edited — they are re-set only at the start of a fresh clock after an abandon.
