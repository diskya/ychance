# Phase 8 — Forward-Simulation Execute + Notional Tax

**Goal**: wire the pipeline to a realistic forward-simulation execution layer: real market data in, simulated orders and fills out, notional P&L and notional tax tracked as if it were real. No real broker, no real capital, **yet**. Real-broker integration is deferred to Phase 11 ([07-go-live.md](07-go-live.md)) after a successful clock.

Routing is per-rule, not a global mode (see [README.md](README.md) "Operating mode: Routing, not modes"). Each rule has a `live_fraction ∈ [0, 1]`; during the sim clock, `live_fraction = 0` everywhere. Treat this phase as seriously as if real money were at stake — if the sim is wrong, every rule that Graduates is wrong, and the whole M8 clock wastes its budget on a calibrated-to-nothing signal.

## Dependencies
- [04-lifecycle-and-sizing.md](04-lifecycle-and-sizing.md) is complete. Graduated rules have notional sizing assigned.
- Phase 0 ([00-operator-decisions.md](00-operator-decisions.md)) — target broker is chosen (for friction calibration), jurisdiction and tax bracket are declared, market-data vendor is chosen.
- Ingest (from [01-foundation.md](01-foundation.md) §2.1) is streaming real market data into the raw store.

## Parallelism
- 8.1 and 8.3 are independent; can run in parallel.
- 8.2 depends on 8.1.

---

## 8.1 Friction model + market-data access — **[M]**

The sim's credibility lives or dies here. A friction model that underestimates spreads, slippage, or borrow cost produces rules that pass Observe's distribution match and fail real money.

### Research-then-code

**Research thread prompt** (~1 session):

> I am building the friction model for a forward-simulation execution layer. Rules will be evaluated against real market data (from a feed already flowing into the raw store), and fills will be simulated. The simulated fills must be calibrated so that rules that survive K_live in forward simulation also survive in real money once we cut over (Phase 11).
>
> Constraints:
> - Target broker is `<broker from config/envelope.yaml>`. Use *that broker's* commission tier and borrow rates.
> - Market-data feed is `<vendor from config/envelope.yaml>`, granularity `<bar_size>`. Quote detail may be bars-only or NBBO — design must work for both, with different fidelity bounds.
> - Retail execution: no sweep routing, no guaranteed fills, no hidden orders.
>
> Recommend a friction model with:
> (a) Fill-price model per order type (market, limit, stop). For market orders with only bars: fill at next-bar open ± half-spread ± impact. For limits: fill only if next-bar range touches the limit, with queue-position uncertainty modeled.
> (b) Spread model: estimated from intraday range-and-volume if bid/ask not available; tighter assumptions require NBBO quotes.
> (c) Slippage / market-impact model: function of order size / average daily volume.
> (d) Commission per trade per asset class per target broker tier.
> (e) Overnight borrow cost for shorts: daily cost model based on broker's published rate (config-driven parametric).
> (f) Latency: the time between "rule fires `C`" and "simulated fill" should match what a real broker round-trip would look like for this target broker tier.
> (g) Capability modeling: the sim must refuse orders that require a capability the target broker does not admit (e.g., short a symbol with no locate, trade options without options approval). A rule whose `A` requires an unavailable capability is Retired as infeasible — not silently filled.
>
> Return a design with each sub-model, its parameters, and its calibration source (broker docs, vendor quote samples, or post-cutover real fills as a future feedback loop).

**Coding prompt** (after design):

> Implement `friction/` per the attached design. Pure-function API: `simulate_fill(order_intent, market_data_slice, account_state, broker_config) -> FillResult`. Every parameter of the friction model lives in `config/envelope.yaml` under `target_broker` — no magic numbers in code. Include property tests: short orders refused when capability disallows; limit fills respect queue-position uncertainty; commissions match broker config exactly.

### 8.1b Market-data adapter for the sim — **[S]**

> Implement `market_data/` as a thin adapter over the market-data vendor chosen in `config/envelope.yaml`. Methods:
> - `stream_bars(symbols, bar_size) -> iterator` — real-time bar stream; each bar goes into the raw store via Ingest and is tapped here for sim consumption.
> - `get_quote(symbol, at_time) -> (bid, ask, last, size)` if NBBO available; else `(open, high, low, close, volume)` from the bar straddling `at_time`.
> - `get_account_state_sim() -> SimAccountState` — reads the sim's book: positions, notional cash, open orders.
>
> **Confirm feed parity** with Paper-deploy from [04-lifecycle-and-sizing.md](04-lifecycle-and-sizing.md) §6.1: Paper-deploy and Execute must read byte-identical bars. If Paper-deploy uses a different read path from Execute, Observe's distribution match is contaminated. Add a property test that proves the feed parity.

---

## 8.2 Router + Simulated Execute — **[M]**

> Implement `execute/` per [../methodology/01-architecture.md](../methodology/01-architecture.md). Execute is a **router** that, per intent:
>
> 1. Reads the rule's effective `live_fraction` (from `config.routing` with optional per-rule override; resolved at execution time, not intent-generation time).
> 2. Confirms kill-switch state (from [06-operator-ux.md](06-operator-ux.md) §9.2). Kill switch halts both real and sim routes.
> 3. Re-evaluates `C` against the latest real market data through `market_data/`. If `C` no longer holds, drops the order with a dropped-order record.
> 4. Computes two sub-intents from the original sized intent:
>    - **Real sub-intent** with size = `intent.size × live_fraction`.
>    - **Sim sub-intent** with size = `intent.size × (1 − live_fraction)` if `config.routing.shadow_sim_enabled` is `false`; otherwise **always simulate the full intent size** as a shadow (the committed-but-not-sent portion plus a shadow of the real portion for friction calibration).
> 5. During the sim clock (`live_fraction = 0` for all rules), the real sub-intent is empty and only the sim route runs.
> 6. During Phase 11 cutover, both routes run; their sizes sum to `intent.size` (with the shadow overlap handled per the design).
>
> **Fill emission** — one record per route:
> - Real fills carry `route: "real"`, plus broker-provided fields.
> - Sim fills carry `route: "sim"`, plus the friction model's intermediates (predicted spread, predicted slippage, modeled latency).
> - Every record identifies the parent `intent_hash` so post-hoc reconciliation can join real vs. sim for the same intent.
>
> Idempotency keys are derived from `(rule_id, intent_hash, route, submit_time_bucket)` — so a real idempotency conflict does not silently suppress the sim counterpart, and vice versa.
>
> During the sim clock, `config.routing.default_live_fraction` is pinned to `0.0`; edits to this field are refused by Execute unless the current phase is Phase 11 (enforced at runtime, logged on every refusal). Per-rule overrides are likewise gated.
>
> Kill switch behavior: when active, refuses new orders on both routes and calls `X` on both real and sim positions. Same code path for both — **no `if live_fraction == 0: skip_kill_check` anywhere**.

---

## 8.3 Tax accrual (notional during clock, real post-cutover) — **[M]**

> Implement `tax/` per [../methodology/06-sizing-risk-portfolio.md](../methodology/06-sizing-risk-portfolio.md). The module runs on both routes:
>
> - **Sim route**: per simulated realized-gain event, estimate tax under the operator's jurisdictional bracket; accrue into `sim_notional.E_res_usd`. This feeds into `U(R)` so Validate sees post-tax utility during the clock.
> - **Real route** (Phase 11+): per real realized-gain event, estimate tax; accrue into `real_capital.target_E_res_usd` (or its realized balance). This drives actual reserve requirements and the tax-model recalibration.
>
> At each M2a, emit a calibration report comparing model predictions against:
> (i) during the sim clock, sim post-tax `U(R)` vs. sim pre-tax `U(R)` on closed rules — bounds the model's internal consistency;
> (ii) post-cutover, real realized tax vs. model estimate — the authoritative feedback loop.
>
> All parameters live in config. Never hardcode tax rates.

---

## Exit criteria for this phase

- `friction/` produces fills that match hand-checked reference cases for each order type under the target broker's spec.
- `simulate_fill` refuses orders that require unavailable capabilities.
- Kill switch verified: flipping it mid-order drops pending intents on both routes and triggers `X` on all positions within the pre-committed latency.
- Feed parity test passes: Paper-deploy and Execute consume byte-identical bars.
- Execute records carry a `route` tag; during the sim clock, every record has `route: "sim"` and no record has `route: "real"`. Property-tested.
- Edits to `config.routing.default_live_fraction` are refused during the sim clock; the refusal is logged.
- Tax accrual tested on synthetic realized-gain events; realized-vs-estimated comparison works on the sim route.
- An audit-trail grep for "hardcoded tax rate", "TODO: friction", or "if live_fraction == 0: skip" turns up zero matches.

## Failure modes to watch

- **Friction optimism.** If spread or slippage assumptions are more generous than reality, the sim will bless rules that fail live. Calibrate against your target broker's actual commission schedule, and if NBBO data is available, compare your bar-only spread estimates to realized spreads from NBBO on a sample — if your model is systematically tighter, widen it.
- **Feed parity silent divergence.** A subtle off-by-one in bar timestamps between Paper-deploy and Execute corrupts the Observe distribution match. The parity test must run on every daily cycle.
- **Kill switch only works in the UI.** The kill switch must be read by Execute on every submit, not just when the operator clicks it. Otherwise a stuck daemon continues to place sim orders after a kill. Property test: set kill switch, simulate an intent submission, assert zero fills produced on both routes.
- **`route` field spoofing.** Post-cutover, an intent will legitimately emit both a `route: "real"` fill and a `route: "sim"` shadow fill. Pre-cutover records are sim-only. The sets are audit-separable. Do **not** rewrite historical records when cutting over — that would break the audit chain.
- **Capability drift in target broker.** Even pre-cutover, the target broker's capabilities can change (new asset class, fee change). Monitor broker announcements and log changes into the audit as a `target_broker_change` record; trigger a friction-model recalibration.
- **Sim fills being "too clean."** Real fills are messy: partial fills, cancellations, requotes. The sim should model partial fills explicitly, not assume all-or-nothing fills. A rule tuned against all-or-nothing may fail on partial-fill regimes live.
