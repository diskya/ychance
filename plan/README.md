# Implementation Plan — Index

A bootstrap plan for building the system described in [../methodology/](../methodology/). One-time: the M2a revision cadence only kicks in once the system is live, so this tree is a pre-clock, pre-capital build sequence.

## How to use

- **Files** are roughly sequential; later files depend on earlier ones.
- Each task is labeled **[S]** (small — paste prompt into a coding agent as-is), **[M]** (medium — one or two coding-agent sessions, may need iteration), or **[L]** (large — start a dedicated research thread with the provided prompt, decide approach, *then* hand to a coding agent).
- Prompts assume the agent has access to [../methodology/](../methodology/) and [../Objective.md](../Objective.md).
- Claude Code vs Codex: Claude Code tends to be stronger for open-ended design-and-build and for tasks spanning multiple files in this tree. Codex is fine for well-scoped **[S]** tasks. Pick whichever is in front of you.

## Operating mode: forward-simulation first, real money after

The M8 clock runs in **forward simulation**: the system pulls real market data in real time, evaluates rules, records simulated orders and fills against a realistic friction model, and tracks notional P&L. No real orders reach a broker and no real capital is at risk during the clock. Real-money cutover is a deliberate, fractional, gated post-clock phase (see [07-go-live.md](07-go-live.md) Phase 11).

### Two-tier success (preserves the methodology's falsification boundary)

To avoid a bad-state audit record where `clock_exit: success` is written before any real-money exposure, **the sim clock does not produce methodology-level success directly**. It produces a necessary-but-not-sufficient milestone:

1. **`sim_success`** (end of sim clock). A rule passed all four success criteria in forward simulation: committed-simulation deployment against real forward-time data, realistic friction, `K_live`-months wall-clock survival, material-originality test. This is a **conditional** success — it licenses Phase 11 cutover but is not M8 success in the methodology's sense.
2. **`real_success`** (after Phase 11). The same rule, after cutover, has survived `K_live_real` months in real money at ≥ a pre-committed live_fraction, with the friction model calibrated within tolerance over the cutover window `K_cutover`. **Only `real_success` corresponds to `clock_exit: success` per [../methodology/08-falsification-clock.md](../methodology/08-falsification-clock.md).**

A rule can reach `sim_success` and then fail cutover (friction-calibration breach, real-P&L distribution mismatch, or failure to survive `K_live_real`). That outcome is `clock_exit: abandon_at_cutover` — a distinct abandon category from `clock_exit: abandon_at_sim`, so the audit preserves which stage broke.

### Routing, not modes

The sim→real transition is **per-rule**, not a global flag. Each rule has a `live_fraction ∈ [0, 1]`: the fraction of its sized intent routed to the real broker; the remainder goes to the friction simulator. During sim clock, `live_fraction = 0` for every rule. During Phase 11 ramp, `live_fraction` increases per a pre-committed schedule. The sim continues to run as a **calibration shadow** alongside real execution at every stage. Every fill record carries a `route` tag (`"real"` or `"sim"`) so the two streams are audit-separable. (See [05-execution.md](05-execution.md) for the routing implementation; [07-go-live.md](07-go-live.md) §11 for the ramp schedule.)

### Budget structure (see [00-operator-decisions.md](00-operator-decisions.md))

The envelope `E` is partitioned into absolute dollar pools, not fractions:
- `$B` — real LLM/data/compute/storage spend during the sim clock (methodology default $15K).
- `$B_cut` — real ops spend during Phase 11 cutover (~$3K default).
- `E_real_cap` — real capital deployed post-cutover.
- `E_real_res` — real reserve (tax accrual, drawdown cushion).
- Plus notional sizing numbers used during sim for sizing math only.

At `E = $50K` with `$B = $15K` and `$B_cut = $3K`, about $32K remains for real capital + reserve + ongoing ops. If that is too little to deploy the successful rule at its `D_R` ceiling under the correlation clamp, cutover is infeasible and Phase 11 surfaces the mismatch as a decision input. The old fractional partition (`E_cap 0.6 / E_ops 0.25 / E_res 0.15`) is retired — at `E = $50K` it underfunds `$B`, and conflating capital with ops in one partition is what created that inconsistency.

### What this does **not** loosen

- Realistic friction is non-negotiable. A sim with zero spreads or zero slippage is worse than useless — it will pass rules that lose money live.
- Forward-time evaluation is non-negotiable. The sim must read data as of wall-clock-now, never the future.
- Everything else in the methodology applies unchanged: the discovery loop, Validate, Council, Observe, Retire triggers, the audit chain, the bias log. The sim is the output layer only.
- Why this is compatible with §0 and §7: the sim-vs-real decision is about the deployment *layer*, not about which rules to run. The operator is not substituting human judgment for AI rule selection; they are deferring real-capital commitment to after the pipeline demonstrates it works.

## Files

| File | Scope |
|---|---|
| [00-operator-decisions.md](00-operator-decisions.md) | Phase 0 — parameters you fix before any code |
| [01-foundation.md](01-foundation.md) | Phases 1–2 — storage, audit, data pipeline |
| [02-discovery-loop.md](02-discovery-loop.md) | Phases 3–4 — Propose, Screen, Validate, meta-validation |
| [03-council.md](03-council.md) | Phase 5 — adversarial council + independence audit |
| [04-lifecycle-and-sizing.md](04-lifecycle-and-sizing.md) | Phases 6–7 — Paper-deploy, Observe, Graduate/Retire, sizing, portfolio |
| [05-execution.md](05-execution.md) | Phase 8 — forward-simulation Execute, friction model, notional tax |
| [06-operator-ux.md](06-operator-ux.md) | Phase 9 — daily/weekly/quarterly panes, kill switch, heartbeat |
| [07-go-live.md](07-go-live.md) | Phases 10–11 — dry run, clock start, post-clock discipline |

## Clock discipline

The M8 clock in [../methodology/08-falsification-clock.md](../methodology/08-falsification-clock.md) starts when the **discovery loop can produce a Graduate candidate end-to-end** — not when you start building. Phases 0–9 are pre-clock. Phase 10 starts the clock.

Track pre-clock spend separately from `$B`. Data-vendor trials, LLM API experiments, and compute spent during build come out of `E_ops`, not `$B`. Keep a running tally from day one — if build eats more than `E_ops − $B`, the partition was wrong and needs re-declaration before the clock starts.

## Sequencing and parallelism

- **Serial spine**: [00](00-operator-decisions.md) → [01](01-foundation.md) → [02](02-discovery-loop.md) → [03](03-council.md) → [04](04-lifecycle-and-sizing.md) → [05](05-execution.md) → [06](06-operator-ux.md) → [07](07-go-live.md).
- **Parallelism within a phase** is noted in each file.
- **Hard gate 1 (clock start)**: no clock until the Phase 10 dry run in [07-go-live.md](07-go-live.md) passes and the clock-start audit record is written.
- **Hard gate 2 (real money)**: no real capital until Phase 11 ([07-go-live.md](07-go-live.md)) — requires a `clock_exit: sim_success` audit record, an explicit cutover decision, the real-broker sandbox dry run, and a `K_cutover` friction-calibration window with tolerances met. Full `real_success` requires an additional `K_live_real` survival window at `live_fraction = 1.0`.

## Rough effort estimates (solo, part-time)

| Phases | Estimate |
|---|---|
| 0–1 ([00](00-operator-decisions.md), [01](01-foundation.md)) | 1–2 weeks |
| 2 (data part of [01](01-foundation.md)) | 2–3 weeks depending on vendor count |
| 3–5 ([02](02-discovery-loop.md), [03](03-council.md)) | 6–10 weeks — research threads concentrate the time here |
| 6–9 ([04](04-lifecycle-and-sizing.md), [05](05-execution.md), [06](06-operator-ux.md)) | 4–6 weeks |
| 10 dry run ([07](07-go-live.md)) | ≥ 4 weeks minimum |

**Total pre-clock build: ~4–6 months** at realistic solo bandwidth. If it runs longer, that is itself a signal the architecture is too heavy for solo scale — invoke the §7 / M9 test before committing capital.

## Failure modes to watch during build

- **Taxonomy leakage via prompts.** Every LLM prompt is a vector for re-inserting human categories. A Propose prompt that tells the model "look for signals like X or Y" is a defect even when the code doesn't enforce those categories. Grep your prompts for named strategies before shipping each stage.
- **Convenience backdoors.** An "emergency override" API on the sizing function or the Retire triggers is a §7 violation waiting to happen. If you find one in review, delete it and document the deletion in audit.
- **Silent state.** Any variable that changes between stage runs without a corresponding audit record is a reproducibility hole. Property-test stage invariants.
- **Cost blowup.** The cheap-model-first / frontier-model-adjudicate discipline is load-bearing. If your dry run shows cost per candidate trending above `$B / expected candidate count`, throttle *before* the clock starts.
