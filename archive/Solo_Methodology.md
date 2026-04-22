# Solo-Operator Methodology
## Minimum Viable Implementation for a Single Researcher with <$500k Capital

*This is not `Final_Methodology.md` at reduced scale. It is a different spec — optimized for one person, public data, retail execution, and the discipline of doing a narrow thing honestly rather than a wide thing sloppily.*

---

## 0. Honest Scope

**Who this is for.** One person. Full-time or serious part-time. No team, no prime broker, no institutional data. Budget ceiling roughly $300k–$700k/year all-in including your own time if you value it at market rate; cash expense ≤ $5k/year.

**What this is not.** This is not an attempt to run `Final_Methodology.md` on a laptop. That spec assumes a walled Tier-C group, an independent specialist team, and $50M+ AUM to justify the overhead. If you try to paper-over those gaps, you will produce confident numbers that do not survive live deployment. Don't.

**What this is.** A narrow, deliberately humble methodology that:
1. Picks **one edge family** where the alpha mechanism is structural (not informational), the capacity matches your size, and the specialist baseline is in the published academic literature.
2. Preserves the **discipline invariants** from the final spec — falsification clocks, pre-registration, walk-forward testing, honest data-tier accounting — because those cost nothing but time.
3. Drops the expensive nodes (N3 consensus surface, N6 attention-cost estimator, N8 liquidity elasticity, N11 three-agent council, N13 crowding tensor) because you cannot staff or fund them.
4. Defers any capital deployment until a pre-committed evidence bar is cleared. You spend 6–12 months in research before a dollar is at risk.

**Realistic expectations.** If you execute this well, you are aiming for **5–10% annual returns on capital deployed to the strategy**, with meaningful drawdown periods, and a capacity ceiling around $2–5M before the strategy's own edge compresses. This is a modest, honest outcome — not a fund-of-one home run.

---

## 1. Core Thesis (Solo Version)

Spinoff stubs — the newly-distributed child companies in corporate separations — are subject to **structural forced selling** by the parent's institutional holders who cannot or will not hold the stub (index funds dropping non-index names, mandate-constrained funds dumping small-cap stubs, pension funds avoiding administrative hassle). This selling is price-insensitive and front-loaded in the first 30–90 days post-distribution.

The edge exists because the selling force is **mechanical**, the absorbing capacity is **bounded by the stub's float**, and large institutional arbs **cannot deploy meaningfully into $50–300M market-cap stubs**. You are trading against a known, quantifiable flow imbalance in a capacity range that excludes your biggest competitors.

Key citations (these are your specialist baseline and your source of priors):
- Cusatis, Miles & Woolridge (1993), *JFE* 33 — classic baseline; ~10–20% 12-month outperformance.
- McConnell & Ovtchinnikov (2004), *J. Fin. Qual. Analysis* — replication through 1990s.
- Chen & Guo (2022), *Journal of Corporate Finance* — confirms persistence through 2020s; ~10–15% 12-month excess return.
- Stock Spinoffs Investing (Joe Cornell) and SpinoffResearch.com — practitioner tracking.

You should read all four before committing a dollar.

---

## 2. Axioms (Kept Intact from Final Methodology)

All five axioms survive for free:

- **A1 — Objectivity Primacy.** Decisions are driven by observable event data (distribution date, index membership, parent filing), not by LLM narrative.
- **A2 — Target Variable.** The target is expected positioning-change trajectory in the stub during the forced-flow window. The dominant mechanism is **rule-based / forced-flow** — this is identifiable by construction, so the A2 identifiability problem in the full spec does not bite here.
- **A3 — No Persona Mimicry.** No "Buffett" or "Greenblatt" framings. Just the flow mechanism.
- **A4 — Falsifiability Clock.** Every trade has a pre-committed horizon (typically 30–120 days post-distribution) and invalidation condition.
- **A5 — Decision-Quality Testing.** Walk-forward, post-cost, capacity-adjusted. MSE is irrelevant.

---

## 3. Simplified Architecture (6 Nodes, Not 14)

The full spec's 14 nodes collapse to 6 because you are trading one edge family on one asset class:

| # | Node | Function | How You Build It |
|---|------|----------|------------------|
| S1 | **Spinoff Event Monitor** | Identify announced and upcoming spinoffs; extract distribution date, ratio, parent index membership, pro-forma stub market cap. | Python scraper of SEC EDGAR Form 10 / 10-12B filings + S&P / Russell index constituent lists. Cross-reference with Stock Spinoffs newsletter. |
| S2 | **Forced-Flow Scorer** | For each upcoming stub, estimate the *forced-sell pressure* = parent's index-fund ownership × (1 if stub is non-index-eligible) + mandate-constrained holder share. Output: score per stub. | 13F aggregation (free from SEC) for parent's institutional ownership; index-inclusion rules from S&P / MSCI / Russell docs (free); simple rubric. |
| S3 | **Pre-Registered Backtester** | Walk-forward backtest of any rule change, with point-in-time data, realistic costs, capacity cap, and borrow where relevant. | Python + pandas + vectorbt (or zipline-reloaded). Price data from Tiingo free tier or Stooq. Transaction-cost model must include spread + slippage + SEC fees. |
| S4 | **Dependence-Track Flag** | For each idea, is the causal-direction claim backed by the structural forced-flow mechanism (causal) or by pattern-matching (dependence)? If dependence, cap size and flag. | Rule: only trade stubs where the forced-flow score is in the top quartile AND at least one published paper documents the pattern for that specific sub-class. Otherwise dependence-only. |
| S5 | **Sizer + Falsification Clock** | Kelly-adjusted sizing with conservative shrinkage (1/4 or 1/8 Kelly); pre-committed max loss per position; pre-committed exit horizon. | Simple spreadsheet or Python — no need for complex N12 aggregation. |
| S6 | **Journal + Calibration Tracker** | Log every prediction (direction, magnitude, horizon, probability); track Brier score and discrimination by conviction decile. | Plain-text or SQLite log. Review quarterly. |

**What's gone from the full spec and why:**
- N3 (consensus reconstructor): you cannot afford dealer gamma / sell-side surface. For this edge you don't need it — the forced-flow mechanism is directly observable.
- N4 (LLM hypothesis generator): you're not generating hypotheses; you're replicating a published one.
- N5 (PC/GES/NOTEARS): irrelevant because your direction prior comes from a natural experiment (distribution event) documented in the literature.
- N6 (attention-cost estimator): fixed-event edge, no cross-entity lag estimation needed.
- N7 (forced-flow accountant): S2 does this for one edge family only.
- N8 (liquidity regime monitor): you'll use a simple realized-vol regime proxy if at all.
- N9 (reaction-function library): collapses to one known rule ("index funds sell stubs").
- N11 (three-agent council): downgrade to a **cross-model sanity check** — after any new rule proposal, run the logic past Claude + GPT + Gemini via API independently and look for any of the three flagging a flaw. Cheap (~$5 per check), not rigorous, but better than self-only.
- N13 (crowding tensor): proxy with Google Trends + Seeking Alpha mention count for the specific stub; crude but free.
- N14 (data tiering): you only have Tier-A/B public data; all returns are architecture alpha by construction. No Tier-C ledger needed.

---

## 4. Invariants (5, Not 8)

Keep the free ones, drop the ones that require team or expensive data:

- **SI1 — Pre-Registration.** Every rule, threshold, universe, cost model, and go/no-go criterion is committed to a timestamped git commit before any evaluation. No post-hoc parameter tweaking.
- **SI2 — Falsification Clock.** Every position has a written exit horizon and invalidation condition at entry. Violation → exit regardless of P&L.
- **SI3 — Post-Cost Walk-Forward.** Every backtest is walk-forward, point-in-time, cost-inclusive. In-sample fit is irrelevant.
- **SI4 — Specialist Baseline Dominance.** Before deploying capital, your strategy must out-perform the **published naïve baseline** (simply buy every qualifying spinoff at distribution date, hold 6 months) on walk-forward post-cost 2010–present. If you can't beat the naïve baseline, the integration has no value and you should just run the naïve baseline.
- **SI5 — Capacity Honesty.** Every backtested return is capped by realistic position sizing: you cannot own >2% of the stub's daily dollar volume on entry, period. Report returns at $100k, $500k, $1M notional separately.

---

## 5. Data Sources (All Free or <$1000/year)

**Required (free):**
- **SEC EDGAR** — full-text search for "Form 10," "Form 10-12B," "Information Statement" — identifies every US spinoff. https://www.sec.gov/edgar
- **13F filings (SEC EDGAR)** — institutional holders of the parent, quarterly.
- **Index constituent files** — S&P 500/400/600 and Russell 1000/2000/3000 publish constituent lists with effective dates. Free from provider sites.
- **Price data** — Yahoo Finance (free but survivorship-biased, do not use for backtesting), Stooq (free, point-in-time-ish), or Tiingo free tier (limited symbols, point-in-time for recent).
- **FRED** (St. Louis Fed) — macro regime labels, Fed policy dates.

**Strongly recommended (cheap):**
- **Tiingo paid tier** ($10–30/month) — clean adjusted prices with corporate actions; worth it.
- **QuantRocket** or **Interactive Brokers TWS historical** if you already have an IBKR account — better fills/costs data.
- **Stock Spinoffs newsletter** (Joe Cornell) — ~$400/year — comprehensive spinoff tracking, saves weeks of scraping time.

**Explicitly avoided:**
- Options chain data (not needed for this edge)
- Dealer gamma / positioning data (not needed)
- Sell-side estimate surfaces (not needed)
- Any alt-data or vendor feed
- Any Tier-C feed

---

## 6. Tool Stack

All free / open-source:

- **Python 3.11+**, **pandas**, **numpy**, **scipy**, **statsmodels**
- **vectorbt** or **zipline-reloaded** for backtesting (vectorbt is simpler for event-driven strategies)
- **sec-edgar-downloader** for EDGAR access
- **pandas-datareader** / **yfinance** / **tiingo-python** for prices
- **SQLite** for trade journal
- **git** for pre-registration (every rule change is a timestamped commit)
- **Jupyter** for research; plain Python scripts for production
- **Claude / GPT / Gemini APIs** for cross-model sanity checks (~$5–20/month total)

---

## 7. Phased Roadmap (12–18 Months)

**Months 1–2 — Literature and Universe.**
- Read Cusatis-Miles-Woolridge, McConnell-Ovtchinnikov, Chen-Guo, and Greenblatt's *You Can Be a Stock Market Genius* (ch. on spinoffs).
- Build the historical US spinoff universe 2005–2025 from SEC filings. Target: ~300–500 events.
- Verify against Stock Spinoffs / SpinoffResearch records.
- Output: a clean dataset of (parent, stub, distribution_date, distribution_ratio, parent_index_memberships, stub_first_day_mcap).

**Months 3–4 — Naïve Baseline.**
- Implement the naïve baseline: buy every qualifying stub at distribution date, hold 6 months, equal-weight.
- Walk-forward, point-in-time, post-cost (include bid-ask, commission, slippage). Use 20bps round-trip as conservative.
- Report: annualized return, Sharpe, max drawdown, win rate, hit rate by sub-cohort (small-cap parent, large-cap parent, index-dropped stub, index-eligible stub).
- **Commit the baseline to git before proceeding.** This is SI1 in action.

**Months 5–7 — Forced-Flow Scorer.**
- Build S2. For each spinoff, compute: parent index-fund ownership (%), stub's probability of being dropped from parent's indexes, estimated forced-sell dollar volume as fraction of stub's free float.
- Bucket stubs by forced-flow score.
- Backtest: does the top quartile by forced-flow score out-perform the naïve baseline post-cost?
- **If yes by >1.5x Sharpe, promote to strategy. If no, the integration adds no value — revert to naïve baseline.**

**Months 8–10 — Adversarial Review.**
- Run your proposed strategy past Claude, GPT, and Gemini independently via API. Prompt each: "Here is a pre-registered strategy and its walk-forward result. What is the most likely way this is wrong?"
- Catalog every flaw raised. Investigate each.
- Typical failure modes to expect: survivorship bias in the spinoff universe, point-in-time leakage in index-membership data, look-ahead in the distribution date, overstated liquidity in backtest, missing small-cap cost premium.

**Months 11–12 — Paper Trading.**
- Paper-trade the strategy for 3 months against actual market conditions.
- Log every deviation between backtest expectation and paper result.
- If paper-trade performance is within 50% of backtest (conservative), proceed to go/no-go gate.

**Months 13+ — Capital Deployment (conditional).**
- If go/no-go gates (Section 9) are cleared, deploy **at most 20% of your total liquid net worth** to this strategy, and within that 20%, cap single-position notional per SI5.
- Re-run walk-forward every quarter. If performance deviates from backtest by >2 sigma for two consecutive quarters, halt and investigate.

---

## 8. Pre-Registration Template

Before any capital deployment, commit the following to a timestamped git repo:

```
STRATEGY: spinoff_stub_forced_flow_v1

UNIVERSE:
  - US-listed spinoffs distributed 2005-<eval_start>
  - Parent must have been in S&P 500/400/600 or Russell 1000/2000/3000 at announcement
  - Stub first-day market cap: $50M - $2B
  - Exclude: financial sector, pre-distribution trading <10 days

ENTRY:
  - Long at opening auction of distribution-date + 1
  - Only if forced-flow score >= <threshold>
  - Maximum position size: min(2% of stub daily $ volume, 5% of strategy NAV)

EXIT (any triggers):
  - Hold period: 90 calendar days
  - Stop: -25% from entry
  - Positive exit on +40% (take-profit)

FALSIFICATION CLOCK:
  - If at day 30 the position is -15% or worse, exit regardless of take-profit logic
  - If stub is acquired, delisted, or halted: exit at first available bid

COST MODEL:
  - Commission: $1/side fixed
  - Spread: 20bps round-trip (25bps for sub-$200M market cap)
  - Slippage: 10bps on exit in stressed tape

CAPACITY CAP:
  - Strategy NAV floor: $50k
  - Strategy NAV ceiling: $2M (edge compresses above)

GO CRITERIA (all must hold):
  - Walk-forward annualized return (2010-eval_start): >8% net
  - Sharpe ratio: >0.8 net
  - Max drawdown: <25%
  - Must beat naïve baseline Sharpe by >0.3
  - Must beat SPY buy-and-hold Sharpe walk-forward

NO-GO CRITERIA (any triggers):
  - Walk-forward Sharpe <0.5 net
  - Paper-trade underperforms backtest by >50% over 3 months
  - Any identified data-leakage or survivorship-bias artifact
```

---

## 9. Go / No-Go Gates for Capital Deployment

Capital deployment is permitted if and only if **all five** of the following are true:

1. **Baseline dominance.** Walk-forward Sharpe of your strategy exceeds the naïve (buy-every-stub) baseline by ≥ 0.3 post-cost.
2. **Absolute floor.** Walk-forward annualized return ≥ 8% net, Sharpe ≥ 0.8 net, max drawdown ≤ 25%, on 2010–present panel.
3. **Out-of-sample fidelity.** Paper-trade Sharpe over 3 months is within 50% of expected backtest Sharpe for the same period.
4. **Adversarial clearance.** No un-resolved critique from Claude + GPT + Gemini independent review stands.
5. **Capacity honesty.** Backtested returns at your intended deployment size (not frictionless size) still clear gates 1–2.

If any gate fails, **do not deploy**. Either fix the strategy (and re-pre-register) or run the naïve baseline, which is itself a valid strategy if it clears the absolute floor.

---

## 10. Expected Outcomes (Honest)

**Baseline expectation** (based on Chen & Guo 2022 and similar):
- Naïve baseline: ~8–12% annualized before costs, ~5–8% after realistic retail costs, Sharpe ~0.4–0.7.
- Forced-flow enhanced: ~10–16% annualized before costs, ~7–11% after costs, Sharpe ~0.6–1.0 if enhancement genuinely works.
- Max drawdown: 15–30% in years with concentrated spinoff clustering or market-wide small-cap selloffs.
- Capacity: $2–5M before edge visibly compresses.

**Translated to dollars:**
- $250k deployed at the top of this range: ~$17k–$27k/year gross, before your own time cost.
- This is not a living. It is a *disciplined side engagement* or a *proof of methodology* that earns while you decide whether to pursue the institutional path.

**What will actually happen:**
- Your first backtest will look amazing. It is almost certainly leaking.
- You will find three subtle point-in-time bugs in months 3–7.
- You will discover that ~20% of the historical spinoffs in your universe are un-trackable because of data gaps; this is normal.
- You will have one stretch where the strategy is flat or down for 6–9 months and you will want to abandon the discipline. Don't.

---

## 11. When to Scale / When to Quit

**Scale up** (raise deployed capital, within SI5 capacity) if:
- 18+ months of live performance within 1 sigma of walk-forward backtest.
- No new competing published research has decayed the edge.
- You have bandwidth to add a **second edge family** (best candidate: month-end institutional rebalance flows per Etula-Rinne-Suominen-Vaittinen 2020).

**Quit this strategy** if any of:
- Two consecutive quarters with live Sharpe <0 and walk-forward backtest still positive (the edge has decayed and you're behind it).
- A meaningfully sized published paper documents saturation of the forced-flow edge.
- You find a data or survivorship bug that, when corrected, makes the backtest fail go/no-go gates.
- Your discipline breaks: you miss a scheduled exit, modify pre-registered rules without re-committing, or deploy beyond SI5 capacity.

**Graduate to full methodology** (`Final_Methodology.md`) if:
- You have cleared go/no-go on this edge live for 2+ years.
- You have the ability to partner with one or more people who can form the independent specialist team (C8) and the Tier-C wall (C5).
- You have capital access (yours or partners') ≥ $50M.
- You have demonstrated discipline honestly — not just returns, but adherence to SI1–SI5.

---

## 12. Closing Honest Note

The final methodology and this solo methodology are not the same thing in two sizes. They are different contracts with reality. The final methodology assumes you can afford rigorous falsification; it aims at a ceiling. This solo methodology assumes you cannot afford full rigor; it aims at an honest floor.

What makes the solo path viable is not that it is cheaper — it is that it **picks one edge where the structural mechanism does the work you cannot afford to do yourself**. The index fund dumping the stub is your Phase-0 specialist. The academic literature is your peer review. Your pre-registration is your test hygiene. Your falsification clock is your risk committee.

Build it slowly. Commit everything to git. Do not deploy capital until the gates are cleared. Read the original four papers at least twice. Re-read this document in six months; the advice that irritates you is usually the advice you most needed.

Good luck. The edge is real and the discipline is free.
