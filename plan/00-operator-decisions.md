# Phase 0 — Operator Decisions (no code)

**Goal**: fix the parameters that §2 left TBD and that the methodology takes as inputs. No agent can do this for you.

## Decisions

| Decision | Notes |
|---|---|
| **Clock phase starts in sim** | Per [README.md](README.md) "Operating mode" section. Real-money cutover is Phase 11 ([07-go-live.md](07-go-live.md)) after a successful sim clock. |
| **`E` — total envelope** | $50K–$100K declared. Budgeted across three dollar pools below. |
| **Clock ops budget `$B` (absolute dollars)** | The real-dollar cost of running the sim clock: LLM API, market-data fees, compute, storage, backups. Methodology default is `$B = $15K`. Declare as an absolute number, not as a fraction of `E` — this is what ChatGPT-finding-2 demanded. **At `E = $50K`, `$B = $15K` consumes 30% of the envelope**; the remaining $35K is reserved for cutover ops + post-cutover real capital + reserve. If that leaves you too little real capital for cutover sizing, either raise `E`, lower `$B`, or shorten `T`. |
| **Cutover ops budget `$B_cut` (absolute dollars)** | Real-dollar cost of the Phase 11 cutover phase (broker sandbox work, live monitoring, continued LLM/data spend while shadow sim runs). Initial hypothesis: `$B_cut ≥ $3K`. Subtracts from envelope too. |
| **Post-cutover real capital `E_real_cap`** | Real-dollar real capital available after cutover = `E − $B − $B_cut − ongoing_ops_reserve`. At `E=$50K`, `$B=$15K`, `$B_cut=$3K`, ongoing reserve of $5K → `E_real_cap ≈ $27K`. Declare the target now, revisit at cutover decision time. |
| **Sim-phase notional sizing** | During the sim clock, sizing in [04-lifecycle-and-sizing.md](04-lifecycle-and-sizing.md) uses a **notional** `E_cap_notional` — any magnitude the operator chooses. Keeping `E_cap_notional ≈ E_real_cap` makes post-cutover sizing continuity easier; deviating is allowed but log the rationale. |
| **Jurisdiction** | Country + tax residency. Drives tax model and the retail-availability constraints on which instruments `A` may reference (shorts/options/futures only to the extent a retail broker in the jurisdiction would offer them; the sim must honor this). |
| **Target broker (for sim and later cutover)** | Pick a specific broker now even though you won't integrate until Phase 11. The sim's friction model is calibrated to *this* broker's tier — commissions, spreads, borrow availability, fractional-share support. Changing target broker mid-clock voids the sim's calibration. Shortlist 2, pick 1 before Phase 8 ([05-execution.md](05-execution.md)). |
| **LLM vendor families** | ≥2 distinct families for Council (per [../methodology/05-council.md](../methodology/05-council.md)). Shortlist at least three so one can be rotated. Count distinct *training pipelines*, not products. |
| **Market-data vendor** | For the forward sim to be credible, the live feed must be real market data, not synthetic. Pick a specific retail-accessible vendor for quotes and bars. Any paid subscription enters `$B`. |
| **Other data vendor shortlist** | Non-price feeds (filings, macro, etc.) as AI-proposals later require. Start with free/cheap retail-accessible feeds. |
| **Clock durations** | `T` = 12–24 months (methodology default 18). `K_live` = 3 months (applied in real money per-rule post-cutover, not in sim — see [07-go-live.md](07-go-live.md)). `K_cutover` = 1 month default (friction-calibration window, distinct from `K_live`). |
| **Stack** | Language + runtime for the system. Recommend Python 3.12 (ecosystem fit for data/ML + LLM SDKs + broker SDKs), on your Ubuntu VM with a remote backup of raw store and audit log. |

## Output

A single `config/envelope.yaml` (or equivalent) committed before Phase 1 begins. The audit trail will reference its hash. Suggested schema:

```yaml
# Envelope is partitioned into absolute dollar pools, not fractions.
# No global operating_mode — routing is per-rule (see below).
envelope:
  total_usd: <number>                   # e.g., 50000

# Real-dollar spend during the sim clock (LLM, data, compute, storage).
clock:
  T_months: <int>                        # e.g., 18
  ops_budget_usd: <int>                  # $B, e.g., 15000
  relax_allowance: 1
  # Durations used by Phase 11 cutover, set here so they are pre-committed
  # before the clock starts:
  K_cutover_months: <int>                # e.g., 1 — friction calibration window
  K_live_real_months: <int>              # e.g., 3 — real-money survival gate

# Real-dollar spend during Phase 11 cutover.
cutover:
  ops_budget_usd: <int>                  # $B_cut, e.g., 3000

# Real capital available post-cutover (target, confirmable at cutover decision).
real_capital:
  target_E_cap_usd: <int>                # e.g., 27000
  target_E_res_usd: <int>                # reserve, tax accrual, drawdown cushion

# Notional sizing numbers used during the sim clock (fake dollars, for sizing math).
sim_notional:
  E_cap_usd: <number>                    # e.g., 27000 (matches target_E_cap_usd for continuity)
  E_res_usd: <number>

# Routing: per-rule live_fraction replaces the old global operating_mode.
# During sim clock, all rules have live_fraction = 0.
# During Phase 11 cutover, the ramp edits this.
routing:
  default_live_fraction: 0.0             # ramped in Phase 11; per-rule override allowed
  shadow_sim_enabled: true               # always true during cutover for calibration

operator:
  jurisdiction: <country>
  tax_bracket: <parametric>

target_broker:
  choice: <name>                         # drives friction calibration
  capabilities: [long, short?, options?, futures?, margin?]
  commissions: <parametric>
  borrow_rates: <parametric>

market_data:
  vendor: <name>
  bar_size: <e.g., 1min, 1day>
  quote_type: <bars_only | nbbo_quotes>

llm_families:
  - <vendor_a>
  - <vendor_b>

data_vendors:
  - <vendor_x>
  - <vendor_y>
```

Fields marked `<parametric>` are config-driven hypotheses revisable at M2a — do not hardcode them into code later.

### Budget invariants the config must satisfy

Before committing the file, verify:
- `clock.ops_budget_usd + cutover.ops_budget_usd + real_capital.target_E_cap_usd + real_capital.target_E_res_usd ≤ envelope.total_usd` (leaves slack for ongoing ops after full cutover).
- `real_capital.target_E_cap_usd` is enough to support sizing at least one graduated rule at its minimum `D_R` ceiling without tripping the correlation clamp at `N_eff = 1`. If this fails, the envelope is too small for real-money deployment; cutover will not be feasible even after a successful sim clock. Surface this in the Phase 11 cutover decision.

## Discipline

- The partition you declare here is a hypothesis, not a permanent commitment. The methodology revises it at M2a. But during the pre-clock build and the first clock run, the partition is frozen.
- If you find yourself wanting to change the partition or the broker or the LLM families *because you read something external*, log the temptation in what will become the bias log (implemented in Phase 9, see [06-operator-ux.md](06-operator-ux.md)). Keep the decision as-is.
- No decisions about *what edges you'll look for* belong here. Any such ranking violates M1. If you feel compelled to write one down, that is itself a §7 signal.
