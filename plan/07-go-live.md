# Phases 10–11 — Dry Run, Clock Start, Sim Clock, Cutover, Real Success

**Goal**: exercise the full system end-to-end on synthetic inputs; start the M8 clock running in forward simulation; if a rule reaches `sim_success`, run the Phase 11 cutover with fractional live routing and a friction-calibration window `K_cutover`; if the real slice survives `K_live_real` months at full live fraction, log `real_success` — the only exit that corresponds to M8 methodology success.

Routing during this tree is per-rule `live_fraction` (see [README.md](README.md) "Operating mode: Routing, not modes"). Real money is not at risk during Phase 10 or during the sim clock. It becomes at risk only during Phase 11, and even then only at a ramped fraction until `K_live_real` passes.

---

## 10.1 End-to-end dry run (pre-clock) — **[M]**

Before starting the clock, run the full loop for **at least one month** on forward-simulation mode against real market data. Capital is notional throughout. This is not a coding task — it is an observation task. You operate the pipeline exactly as specified in [../methodology/07-operator-workflow.md](../methodology/07-operator-workflow.md) and watch for defects.

### Checklist during the dry run

- [ ] Every stage emits the audit records specified in [../methodology/09-audit.md](../methodology/09-audit.md).
- [ ] `verify_chain` and `verify_cross_day` from [01-foundation.md](01-foundation.md) §1.2 pass daily.
- [ ] Cost per cycle is within `$B / T × cycles_per_month` — the cheap-model-first discipline from [02-discovery-loop.md](02-discovery-loop.md) §3.2 holds under real load.
- [ ] At least one candidate reaches Paper-deploy. If zero do over a full month, Propose is broken — fix before clock start.
- [ ] **Feed parity**: Paper-deploy and Execute consume byte-identical bars ([05-execution.md](05-execution.md) §8.1b test passes daily).
- [ ] **Friction realism sanity check**: on any rule that reaches Paper-deploy, manually audit ≥5 simulated fills against the target broker's published commission/spread/borrow specs. Every fill must match within tolerance.
- [ ] Degraded-mode trigger fires correctly when you miss `N` heartbeats intentionally.
- [ ] Kill switch halts Execute within the pre-committed latency (sim-mode, but exactly the same code path that will be used with real money).
- [ ] A Council decision record reproduces byte-identical on re-run from cached inputs.
- [ ] The independence audit ([03-council.md](03-council.md) §5.3) has enough data to classify council members; classification is non-trivial (not all members collapsed to one group, not all members in separate groups).
- [ ] A rule that hits its per-rule clock expiry actually gets Retired without operator intervention.
- [ ] Every Execute record during the dry run carries `route: "sim"`; zero records carry `route: "real"`.
- [ ] `config.routing.default_live_fraction` is `0.0` and every rule's effective `live_fraction` resolves to `0.0`; attempts to edit these are refused by Execute and the refusal is logged.
- [ ] An audit-trail grep for "TODO", "FIXME", "if live_fraction == 0: skip" in the pipeline code returns zero matches.

### Failure response

If any checklist item fails, do not start the clock. Fix the defect, re-run the affected portion of the dry run, re-verify. The dry run is allowed to take longer than a month — it is **not** allowed to be shortened.

### Dry-run prompt for a coding agent (defect investigation)

> I am running the end-to-end dry run described in [plan/07-go-live.md](07-go-live.md). The following defect surfaced: `<describe>`. The audit records for the affected event chain are at `<path>`. Read [../methodology/](../methodology/) and the affected stage's source, and identify the root cause. Do not propose fixes yet — I want a root-cause analysis first.

---

## 10.2 Start the M8 clock — **[S, operator action]**

When and only when 10.1's checklist is all green, write a single audit entry with category `M8 clock`:

```json
{
  "category": "clock_start",
  "clock_id": "<uuid>",
  "T_months": <int from config>,
  "clock_ops_budget_usd": <int from config>,
  "cutover_ops_budget_usd": <int from config>,
  "K_cutover_months": <int from config>,
  "K_live_real_months": <int from config>,
  "relax_allowance": 1,
  "envelope_hash": "<sha256 of config/envelope.yaml>"
}
```

From this point, pre-committed parameters are immutable until the clock exits (i.e., until either `real_success`, `abandon_at_sim`, or `abandon_at_cutover` — see §10.4 and §11.6). The quarterly pane (see [06-operator-ux.md](06-operator-ux.md) §9.1) exposes clock-health snapshots but not clock-parameter editing.

---

## 10.3 Graduate the first rule to the committed-simulation tier — **[operator action]**

During the sim clock (all rules at `live_fraction = 0`), Graduate moves a rule from Paper-deploy (fractional notional size) to Execute (full notional size) — still sim-only. No real money moves, but every gate in [../methodology/07-operator-workflow.md](../methodology/07-operator-workflow.md) §"Graduate approval" must fire clean, same as if real capital were being committed.

### What to expect

You may want to read the rule's grounding out of curiosity. Fine, but the grounding is **not** a gate input at Graduate time — the gates are: Validate dominance statistics, Council independent approvals, Paper-deploy distribution match, correlation-clamp headroom. If all four are green, approve. If any is red, do not approve.

If the rule's grounding looks unfamiliar, that is the methodology working (per §7). Do not refuse Graduate on unfamiliarity.

If the rule's grounding looks like a classical strategy you've read about, that is not evidence against the rule. Approve or reject on the gates, not on resemblance.

**The fact that it's sim does not relax the discipline.** If you find yourself approving something you would hesitate to approve with real money, the gate thresholds are wrong; invoke M2a to revise them. Do not simply lower your standards because the P&L is notional.

---

## 10.4 Running the sim clock — **[operator, `T` months]**

Operate the daily/weekly/quarterly cadence from [../methodology/07-operator-workflow.md](../methodology/07-operator-workflow.md). During the sim clock, every rule has `live_fraction = 0`; no real money is touched.

### Sim-phase exits

The sim phase has exactly these exit categories (logged under audit category `clock_exit`):

- **`sim_success`** — ≥1 rule has cleared all four criteria from [../methodology/08-falsification-clock.md](../methodology/08-falsification-clock.md): deployed in committed-sim Execute against real forward-time data, survived `K_live` (the methodology default of 3 months) in sim, generated risk-adjusted post-cost post-tax utility above competitors, and passed the material-originality test. **This is a necessary but not sufficient condition for methodology-level M8 success.** It licenses Phase 11; it is not the end of the clock.
- **`relax_invoked`** — the single-permitted M-clause relax per [../methodology/08-falsification-clock.md](../methodology/08-falsification-clock.md) §"Relax path". Clock continues.
- **`abandon_at_sim`** — `T` elapsed with no `sim_success` and (a) no relax remaining, or (b) relax invoked and still no success. Real money was never at risk. Cost borne was `$B` of real clock-ops spend plus operator time. Begin the 3-month cool-off per [../methodology/08-falsification-clock.md](../methodology/08-falsification-clock.md) §"Abandon path". Any subsequent attempt is a fresh methodology with a fresh [../Objective.md](../Objective.md).

On `sim_success`, proceed to Phase 11. Note that a `sim_success` record is not `clock_exit: success` — the methodology-level success record is written only after a successful Phase 11 (see §11.6).

---

## Phase 11 — Cutover (conditional on `sim_success`)

This phase begins only after a `clock_exit: sim_success` audit record. It introduces the real-broker adapter, a friction-calibration window `K_cutover`, a live-fraction ramp, and finally a `K_live_real`-months real-money survival gate. Only passing that final gate produces **`real_success`**, which is the methodology's M8 success.

Phase 11 is **not** a reset of the M8 clock. The rule(s) that reached `sim_success` are the rules that cut over. You do not re-propose, re-validate, or re-council them from scratch. You do, however, run a friction-calibration window (§11.4) before increasing live_fraction, and a real-money survival window (§11.6) before claiming success.

Real capital at stake is bounded by `real_capital.target_E_cap_usd` from [00-operator-decisions.md](00-operator-decisions.md). If the envelope has been depleted by sim-clock spend and `target_E_cap_usd` is too small to support sizing at the rule's `D_R` ceiling under the correlation clamp, cutover is infeasible — log and move to `abandon_at_cutover`.

### 11.1 Cutover decision — **[operator action]**

Before building 11.2, make an explicit decision in audit:

```json
{
  "category": "cutover_decision",
  "decision": "proceed" | "defer" | "permanently_decline",
  "successful_rule_ids": [...],
  "rationale": "...",
  "envelope_feasibility": "feasible" | "infeasible_at_current_E"
}
```

This is an operator decision about the deployment layer, not about strategies. §7 is not violated — you are not choosing between rules, you are choosing whether to move the successful rule from sim to real. `defer` delays cutover for a documented period during which the rule continues in sim at full `live_fraction = 0`. `permanently_decline` maps to `clock_exit: abandon_at_cutover`.

### 11.2 Real broker adapter — **[M, broker-specific]**

> Implement `broker/` as a thin adapter over `<target broker API from config/envelope.yaml>`. Methods:
>
> - `submit_order(intent, rule_id, idempotency_key) -> broker_order_id`
> - `cancel_order(broker_order_id)`
> - `get_position() -> dict[symbol -> qty, cost_basis]`
> - `get_account_state() -> (buying_power, maintenance, margin_state)`
> - `stream_fills() -> iterator of fill events`
>
> Log every call and every response to audit. Include full integration tests against the broker's sandbox.
>
> The adapter slots under Execute's **real route** ([05-execution.md](05-execution.md) §8.2). Execute's routing is unchanged in shape: it already splits intents into `route: "real"` and `route: "sim"` sub-intents. Before Phase 11.4, all rules have `live_fraction = 0`, so the real route is empty and `broker/` is never invoked in production. In Phase 11.4 onward, `broker/` is invoked for the real sub-intent.
>
> Capability handling: the real broker's capabilities are queried at startup and compared against `target_broker.capabilities` in `config/envelope.yaml`. Any mismatch halts cutover until resolved.

### 11.3 Real-broker sandbox dry run — **[M]**

Run for ≥2 weeks on the broker's sandbox / paper endpoint with `broker/` adapter installed but `live_fraction` still `0.0`. Manually exercise the broker path on synthetic test intents. Goals:

- Every round-trip works: submit → fill → audit record with `route: "real"`.
- Idempotency holds under induced crashes.
- Reconciliation on startup correctly matches broker order history against audit.
- Capability matches what was declared in `config/envelope.yaml`.

Success of 11.3 unlocks edits to `live_fraction` (Execute's guard from [05-execution.md](05-execution.md) §8.2 is relaxed by an explicit audit record; no other path is permitted).

### 11.4 Cutover-calibration window `K_cutover` — **[operator, `K_cutover_months` (default 1)]**

Set `config.routing.default_live_fraction = 0.1` (or a per-rule override for the successful rule only). The real broker now receives 10% of the successful rule's sized intent; the friction simulator runs the full-size shadow. This window is about **friction-model calibration, not rule survival** — you are comparing the sim's predicted fills to the broker's actual fills.

Pre-committed tolerances for `K_cutover` (all config-driven, revisable at M2a):

- **Fill-price divergence**: median absolute real-minus-predicted fill price ≤ pre-committed bps of price, across all fills.
- **Slippage distribution**: KS-test or analogous between real-slippage and sim-predicted-slippage distributions not rejected at pre-committed level.
- **Commission / borrow / tax**: realized per-fill costs match model within tolerance.
- **No broker capability surprises**: the real route never returns "capability not available" on an intent the sim admitted.

**`K_cutover` does NOT test rule survival.** It tests the friction model. A sample size at 10% live fraction over 1 month is generally too small to re-run `K_live`'s rule-survival gate, and re-running that gate here would be a type error.

If tolerances hold through `K_cutover`: proceed to 11.5.

If tolerances fail: **roll back**. Reset `live_fraction = 0`, recalibrate `friction/` or `tax/`, re-run 11.3 on the updated models, and retry 11.4 with a fresh `K_cutover` window. Roll-back is logged; rollbacks do not accumulate against the M8 clock's relax allowance but do consume `cutover.ops_budget_usd`. If `cutover.ops_budget_usd` is exhausted without 11.4 clearing, the cutover is falsified → `clock_exit: abandon_at_cutover`.

### 11.5 Live-fraction ramp — **[operator, ramp_duration months]**

After `K_cutover` clears, increase `live_fraction` per a pre-committed schedule (config-driven, revisable). Suggested initial ramp:

| Step | `live_fraction` | Hold duration | Gate |
|---|---|---|---|
| 1 | 0.1 → 0.25 | 1 month | `K_cutover` tolerances continue to hold |
| 2 | 0.25 → 0.5 | 1 month | Same |
| 3 | 0.5 → 1.0 | 1 month | Same |

During the ramp, `shadow_sim_enabled` stays `true`: the sim simulates the full intent size for continued calibration. Each step is gated on the same `K_cutover` tolerances — if any tolerance breaches at any step, revert to the previous step, not to zero. The ramp is monotone only when clean.

The ramp is **not** `K_live_real` — see 11.6. A rule at `live_fraction = 1.0` during the ramp has not yet earned `real_success`.

### 11.6 `K_live_real` at full fraction → **`real_success`** — **[operator, `K_live_real_months` (default 3)]**

After the rule reaches `live_fraction = 1.0` (end of 11.5), a fresh `K_live_real`-months window begins with the rule fully live. The gate:

- The **real route's** P&L stream, over `K_live_real` months, must satisfy the methodology's original four success criteria applied to real-money-realized numbers:
  1. Deployed to live capital ✅ (by construction at `live_fraction = 1.0`).
  2. Survived `K_live_real` months in the live book without Retire triggering.
  3. Generated risk-adjusted post-cost post-tax utility (real, not sim) above competitors from [../methodology/04-validation.md](../methodology/04-validation.md).
  4. Material-originality test passed against the rule's current grounding.

If all four hold at the end of `K_live_real`, log:

```json
{
  "category": "clock_exit",
  "exit_type": "real_success",
  "clock_id": "...",
  "successful_rule_ids": [...],
  "envelope_hash": "<sha256 of current config/envelope.yaml>"
}
```

This is the **only** record that corresponds to M8 methodology success per [../methodology/08-falsification-clock.md](../methodology/08-falsification-clock.md).

If any of the four fails during `K_live_real`:

- If it is a Retire trigger (drawdown, distribution-mismatch, per-rule clock, correlation clamp, council re-review failure), the rule Retires normally per [04-lifecycle-and-sizing.md](04-lifecycle-and-sizing.md). If no other rule is at `live_fraction > 0`, log `clock_exit: abandon_at_cutover`.
- If it is a calibration-shadow breach (sim-vs-real drift exceeds `K_cutover` tolerances) that persists beyond a pre-committed reversion window, drop back to the previous ramp step. If this repeats, abandon_at_cutover.
- If utility-above-competitors fails at end of `K_live_real`: the rule passed sim but loses in real — the friction model was too generous. Retire the rule, log `clock_exit: abandon_at_cutover`, and preserve the calibration data as input to the next (fresh) methodology attempt.

### 11.7 Post-`real_success` — the plan ends

After `real_success`, the sim continues to run as a calibration shadow forever. Quarterly M2a gains a "sim-vs-real drift" report. New rules discovered by the pipeline go through the full sim → cutover ramp → `K_live_real` sequence before being graduated to real money; the two-tier success gate is permanent, not one-time.

Nothing new is built at this point except as architecture-diffs approved at M2a (per [../methodology/01-architecture.md](../methodology/01-architecture.md) §"Review (M2a)"). This plan is done. The methodology takes over.

---

## Discipline reminders

- **The sim is not a license to relax gates.** The gates at Graduate, the per-rule drawdown ceilings, the correlation clamp — all of them are load-bearing even with notional money, because the whole point is to produce rules that will survive cutover. If you soften gates "because it's just sim," the cutover validation window will reject those rules and you will have wasted clock time.
- **Forward time is inviolable.** The sim must read data as of wall-clock-now. If you find a bug that peeks even a bar ahead, every downstream statistic since the bug was introduced is contaminated — fix the bug, then re-run the affected window, then flag in audit.
- **Real money is a separate clock.** The 3-step cutover schedule in 11.5 is itself a small validation clock. Treat tolerance breaches as reasons to go slower, not reasons to push through.
- **The hardest part is still not building or sizing. It is sitting through weeks of zero Graduate events without re-inserting your own edge ideas.** Re-read §7 of [../Objective.md](../Objective.md) before every weekly pane. If you notice yourself drifting, write it in the bias log — that is what the log is for.
