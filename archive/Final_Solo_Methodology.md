> **Status (as of 2026-04-21): Demoted to seed hypothesis under [Objective.md](Objective.md) v2.**
>
> The ranked edge list in this document (spinoff stubs, tax-loss / window-dressing reversal, CEF activist/tender discount compression, convertible calls, odd-lot tenders, SEO microcap, rights offerings, PEAD) is a *human* hypothesis about where edge lives for a sub-$500k operator, drawn from the classical event-driven / value special-situations tradition. Objective.md §3 M1 explicitly forbids curated edge taxonomies as inputs. Under the new framing, these edges may appear only as *outputs* the AI-native system independently re-derives, not as *inputs* to start from.
>
> What remains useful here is the inventory of solo-operator *constraints* — data access, retail execution realism, capacity arithmetic, decay rules, pre-registration discipline — which is consistent with Objective.md §2. What does *not* bind is the strategy ranking, the year-by-year sequencing, and the pre-committed capital routing to named classical edges.
>
> Treat this document as prior art and as a catalogue of constraints, not as a program to execute.

---

# Final Solo Methodology
## Public-Data Forced-Flow Edge Program for a Solo Operator

Date: 2026-04-20

This document supersedes `Solo_Methodology.md` for edge selection and sequencing. It does not replace the broader institutional architecture in `Final_Methodology.md`; it narrows that architecture to what one operator with less than $500k, public data, and retail execution can actually research, test, and trade.

This is not investment advice. It is a research and operating specification.

---

## 1. Executive Decision

The first edge remains **spinoff stubs**.

After reviewing the additional edge candidates and Gemini's recommendations, the final sequence is:

| Rank | Edge Family | Status | Role |
|---|---|---|---|
| 1 | Spinoff stubs and distributed equity stubs | FEASIBLE | Year 1 core strategy |
| 2 | Small-cap tax-loss / window-dressing reversal | FEASIBLE | Year 2 strategy |
| 3 | Closed-end fund activist/tender discount compression | FEASIBLE-TO-MARGINAL | Year 3 strategy, catalyst-only |
| 4 | Convertible call / mandatory conversion pressure | MARGINAL | Dark-horse 2-week sprint |
| 5 | Rights offerings and deeply discounted microcap capital raises | MARGINAL | Research backlog only |
| 6 | SEO microcap price pressure | MARGINAL | Do not promote yet |
| 7 | Odd-lot tender offer arbitrage | FEASIBLE BUT TINY | Administrative sidecar, not a core edge |
| 8 | PEAD / pre-earnings or post-earnings drift | DECAYED | Explicitly rejected |

The main disagreement with Gemini is important:

- **Convertible call forced flows** are real, but the modern evidence base is thin and older studies are mixed on whether the post-call price effect reverses. This is a sprint candidate, not a Year 2 allocation.
- **SEO price pressure in microcaps** is not cleanly long-only. Offerings often reveal adverse selection and financing distress. The supply shock is mechanical, but the expected return sign is not reliable enough to promote without a dedicated test.
- **Odd-lot tender arbitrage** is legally real and retail-suitable, but the capacity is capped at 99 shares per account per event. It is too small to be a methodology pillar.

The strongest solo program is therefore not "find many clever special situations." It is:

1. Master one structural forced-flow edge.
2. Add only edges whose mechanism is non-discretionary, capacity-constrained, and testable with public data.
3. Reject anything where the remaining alpha is mainly informational, high-speed, or dependent on unavailable institutional plumbing.

---

## 2. Non-Negotiable Solo Criteria

An edge family can receive production research time only if all six conditions hold:

1. **Capacity below $10M.** The edge must be too small or operationally annoying for large institutions.
2. **Data cost below $1k/year.** EDGAR, SEC APIs, FINRA, fund sites, FRED, Stooq, Tiingo, Yahoo, issuer NAV pages, and exchange public files are acceptable.
3. **Structural or semi-structural mechanism.** The driver must be forced selling, forced buying, tax timing, index rules, tender mechanics, holder mandates, or calendar liquidity needs.
4. **Published baseline.** There must be an academic or credible working-paper baseline, plus 2020+ evidence that the mechanism still exists or that the institutional setting still matters.
5. **Retail execution.** Long-cash equity only. No options, futures, swaps, hard-to-borrow shorts, ADR conversion, foreign custody, prime brokerage, or sub-minute execution.
6. **Pre-registrable rules.** Entry, exit, invalidation, cost model, and capacity cap must be written before testing.

If a candidate fails any condition, it can still be logged as a side observation, but it cannot become a capital-deployment strategy.

---

## 3. Final Edge Stack

### Edge 1: Spinoff Stubs and Distributed Equity Stubs

**Verdict:** FEASIBLE.

**Mechanism:** Parent holders receive a new security they may be unable or unwilling to hold. Index funds, mandate-constrained institutions, income funds, sector funds, and large-cap managers often sell the distributed stub with limited regard for valuation. The pressure is concentrated around distribution and the first 30-120 trading days.

**Why it survives:** Many stubs are small, illiquid, administratively awkward, and under-followed. The dollar capacity is not attractive for large funds, but it is sufficient for a solo operator.

**Data:** SEC Form 10 / 10-12B / information statements, 8-Ks, S-1s for carve-outs, parent 13F holders, index constituent lists, Stooq/Tiingo/IBKR prices.

**Core citations:**

- Cusatis, Miles, and Woolridge, 1993, *Journal of Financial Economics*, "Restructuring through spinoffs."
- McConnell and Ovtchinnikov, 2004, *Journal of Financial and Quantitative Analysis*, spinoff follow-up evidence.
- Chen and Guo, 2022, *Journal of Corporate Finance*, the operator's cited modern spinoff baseline.
- Recent spin-off literature continues to document positive market effects and post-event behavior, e.g. Gupta, Kumar, and Chattopadhyay 2022 on 2003-2020 Indian spin-offs: https://www.tandfonline.com/doi/abs/10.1080/23322039.2022.2109277
- Recent U.S. spin-off capital-structure update: https://www.mdpi.com/2227-7072/13/3/173

**Production status:** Year 1 only. No second edge is traded until this one has a clean research database, paper-trade log, and go/no-go record.

---

### Edge 2: Small-Cap Tax-Loss / Window-Dressing Reversal

**Verdict:** FEASIBLE.

**Mechanism:** Taxable investors and some institutions sell losing small-cap positions near year-end or quarter-end to realize losses or avoid reporting embarrassing holdings. Selling pressure is price-insensitive in illiquid names. Pressure tends to abate after the reporting/tax date, producing reversal candidates.

**Why it survives:** The strongest effect sits in low-price, low-liquidity, small-cap losers where transaction costs, bad optics, and limited capacity repel institutions. It is not easy to capture with broad indexes.

**Data:** Daily prices, market cap, volume, prior returns, tax year calendar, quarter-end calendar, 13F ownership snapshots if used conservatively.

**Core citations:**

- Chen and Singal, 2003, tax-loss selling and January/December effects: https://www.tandfonline.com/doi/abs/10.2469/faj.v59.n4.2547
- Sias, 2007, momentum seasonality, quarter-end window dressing, and tax-loss effects: https://www.tandfonline.com/doi/abs/10.2469/faj.v63.n2.4521
- Chaudhuri, Burnham, and Lo, 2020, *Financial Analysts Journal*, tax-loss harvesting alpha and wash-sale constraint: https://alo.mit.edu/research-page/an-empirical-evaluation-of-tax-loss-harvesting-alpha/
- Broader 2025 evidence that individual taxable accounts still show December tax-loss selling patterns: https://www.tandfonline.com/doi/full/10.1080/15427560.2025.2485461

**Pre-registered baseline:**

- Universe: U.S. common stocks, market cap $30M-$1B, price above $1, average dollar volume above a minimum floor.
- Signal: prior 6-12 month loser, negative YTD return, high unrealized-loss proxy, adequate liquidity, no bankruptcy/delisting flag.
- Entry: last 3-7 trading days of December or first 1-3 trading days of January, depending on tested rule.
- Exit: 10-25 trading days after entry.
- Invalidations: bankruptcy filing, delisting notice, reverse split with financing distress, bid-ask spread above pre-registered cap.

**Role:** Year 2 strategy if and only if spinoff stubs pass Year 1 gates.

---

### Edge 3: Closed-End Fund Activist/Tender Discount Compression

**Verdict:** FEASIBLE-TO-MARGINAL. Feasible only when catalyst-filtered; generic discount mean reversion is not enough.

**Mechanism:** Closed-end funds do not have ETF-style creation/redemption, so discounts to NAV can persist. Activists can force or negotiate self-tenders, managed distribution changes, mergers, liquidation, conversion to open-end structures, or discount-management programs. Tender offers near NAV create a structural path for discount compression.

**Why it survives:** CEFs are small, retail-heavy, fragmented, and operationally dull. Activists can monetize discounts, but the universe is too small for many institutions. Retail can participate with long common shares.

**Data:** Fund NAV pages, fund annual reports, EDGAR N-CSR/N-CSRS/N-PORT/Schedule TO/13D/13G, CEFConnect or CEFData as convenience layers, issuer press releases.

**Core citations and evidence:**

- Pontiff, 1996, *QJE*, "Costly Arbitrage: Evidence from Closed-End Funds": https://academic.oup.com/qje/article/111/4/1135/1932203
- Lee, Shleifer, and Thaler, 1991, closed-end fund sentiment baseline: https://www.nber.org/papers/w3465
- Lenkey, 2014, activist arbitrage and closed-end funds: https://academic.oup.com/rof/article-pdf/18/1/271/26314074/rfs052.pdf
- Durmaz, 2023, closed-end fund discounts and policy uncertainty: https://www.mdpi.com/1911-8074/16/3/200
- ICI 2025 report: traditional CEF discounts persisted in 2024 and activism remained high: https://www.idc.org/system/files/2025-04/per31-04.pdf
- 2021 Harvard governance note on CEF activism after COVID dislocations: https://corpgov.law.harvard.edu/2021/01/03/shareholder-activism-at-closed-end-funds-in-the-wake-of-covid-19/

**Pre-registered baseline:**

- Universe: U.S.-listed traditional CEFs with daily NAV and sufficient dollar volume.
- Signal: discount wider than own 3-year percentile threshold plus one catalyst: activist 13D, Schedule TO, announced tender, board-approved discount program, liquidation/merger proposal, or credible activist slate.
- Entry: after public catalyst filing or after discount-program trigger is objectively met.
- Exit: tender expiration, discount normalization, catalyst failure, or 120-180 days.
- Invalidations: NAV stale/unreliable, leverage stress, distribution cut without catalyst, fund asset class outside competence.

**Role:** Year 3 strategy after tax-loss strategy is built and paper-traded.

---

## 4. Gemini Recommendations: Final Assessment

### Convertible Bond Call Notice / Mandatory Conversion Forced Flows

**Final verdict:** MARGINAL, dark-horse sprint.

**What Gemini got right:** The mechanism is structural. A call or mandatory conversion can force convertible holders to convert, sell bonds, adjust hedges, or receive common shares. Filings and indentures are public.

**What Gemini overstated:** Modern convertible arbitrage desks do monitor these events, and much of the relevant flow involves the bond and hedge book rather than a simple common-stock long setup. Older evidence is mixed: some studies find negative call-announcement effects and price pressure; others find weak or no clean reversal. There is not enough post-2020 confirmation of a simple retail long-only edge.

**Core citations and evidence:**

- Grundy, Veld, Verwijmeren, and Zabolotnyuk, 2014, *Journal of Corporate Finance*, price pressure around conversion-forcing calls: https://www.sciencedirect.com/science/article/pii/S092911991300093X
- Datta and Iskandar-Datta, 2009, *JFQA*, valuation effects of convertible bond calls: https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/new-evidence-on-the-valuation-effects-of-convertible-bond-calls/AA3F94D0095196F05D13D64D5EB4AF2C
- 2019 review evidence around convertible preferred calls and earnings management: https://www.sciencedirect.com/science/article/abs/pii/S1059056017304835
- Current U.S. convertible terms commonly include no-call periods and 130% stock-price triggers: https://www.mayerbrown.com/-/media/files/perspectives-events/publications/brochures/2025/mb-convertible-bonds-2025.pdf

**Two-week sprint question:** After a public call notice or mandatory conversion trigger, do small issuers show a statistically reliable rebound after forced conversion/hedge-related pressure clears, net of costs?

**Sprint output required:** If the answer is not clearly yes after a 2010-2026 EDGAR sample, reject.

---

### SEO Price Pressure in Microcaps

**Final verdict:** MARGINAL. Do not promote to Year 2.

**What Gemini got right:** Offer size, dilution, and pricing are observable from prospectuses and 424B filings. Relative offer size can create mechanical supply pressure.

**What Gemini overstated:** In microcaps, SEOs and confidentially marketed public offerings often reveal financing distress, adverse selection, cash burn, or shareholder dilution. A price drop is not automatically a rebound opportunity. The operator would risk buying a structurally weak issuer after a dilutive event.

**Core citations and evidence:**

- Autore, Jones, Kovacs, and Peterson, 2021, *Journal of Corporate Finance*, confidentially marketed public offers are often used by small negative-cash-flow firms and show large negative announcement reactions: https://nscpolteksby.ac.id/ebook/files/Ebook/Journal%20International/Marketing/Journal%20of%20Corporate%20Finance%20-%20Volume%2068%2C%20June%202021%2C%20101975.pdf
- COVID-period SEO evidence shows strongly negative announcement effects and worse reactions for smaller firms: https://link.springer.com/article/10.1007/s11573-022-01089-6
- Broader SEO review of firm-category impacts: https://www.mdpi.com/1186116

**Research-only rule:** SEO/microcap capital raises may be used as exclusion filters or as ingredients in tax-loss/forced-selling screens, but not as a standalone long strategy until a walk-forward post-cost test proves the sign of the edge.

---

### Odd-Lot Tender Offer Arbitrage

**Final verdict:** FEASIBLE BUT TINY. Sidecar only.

**Mechanism:** For issuer tender offers under Rule 13e-4, issuers may accept all shares tendered by holders owning fewer than 100 shares before prorating larger tenders, if the offer documents include the odd-lot preference and the holder tenders all shares.

**Why it survives:** The maximum position is usually 99 shares per account. The dollar profit per event is too small for institutions and often too small for a solo operator unless the process is automated.

**Critical limitation:** The odd-lot preference is not universal. SEC staff confirms it is available for issuer tender offers governed by Rule 13e-4, not for all tender offers under Regulation 14D. The offer documents control.

**Sources:**

- SEC Tender Offer C&DIs, Question 101.11: https://www.sec.gov/divisions/corpfin/guidance/cdi-tender-offers-and-schedules.htm
- 17 CFR 240.13e-4(f)(3)(i): https://www.law.cornell.edu/cfr/text/17/240.13e-4
- SEC odd-lot tender offer rule history: https://www.sec.gov/rules-regulations/1996/12/odd-lot-tender-offers-issuers

**Operating rule:** Track it, but do not count it toward strategy returns, capacity, or edge-family diversification. Treat it as occasional administrative yield.

---

### PEAD / Earnings Drift

**Final verdict:** DECAYED for this program.

**Reason:** The remaining public-data PEAD is either too fast, too small, too microcap/illiquid, or too informational. That violates the structural forced-flow criterion.

**Core evidence:**

- Martineau, "Rest in Peace Post-Earnings Announcement Drift," finds analyst-surprise PEAD largely disappeared after 2006 for non-microcaps and after 2016 for microcaps; remaining random-walk microcap drift is short-lived and weak: https://cfr.ivo-welch.info/published/papers/martineau2021rest.pdf
- Retail attempts to trade PEAD usually become an earnings-surprise prediction problem requiring alternative data or speed.

**Rule:** No PEAD strategy in this solo methodology.

---

## 5. Research Queue and Sequencing

### Year 1: Spinoff Stub Program

Deliverables:

1. Full U.S. spinoff database from 2005-present.
2. Naive baseline: buy all qualifying stubs after distribution; hold 90/180 days.
3. Forced-flow enhanced baseline: rank by parent holder constraints, index mismatch, stub size, and likely mandate selling.
4. Paper trading for at least 6 months or at least 10 live events, whichever takes longer.
5. No capital deployment unless go/no-go gates pass.

### Year 2: Small-Cap Tax-Loss / Window-Dressing Program

Start only after Year 1 data and execution process are clean.

Deliverables:

1. Historical universe of U.S. small-cap losers, including delisting/reverse-split handling.
2. December/January and quarter-end tests.
3. Transaction-cost model by price bucket and dollar-volume bucket.
4. Separate test for tax-loss selling and institutional window dressing.
5. Paper trade one full year-end cycle before capital.

### Year 3: CEF Activist/Tender Discount Program

Start only after Year 2 program has a full research notebook and at least one paper-traded cycle.

Deliverables:

1. Daily CEF NAV/price/discount history.
2. EDGAR parser for 13D, 13G, Schedule TO, N-CSR, tender and liquidation filings.
3. Catalyst taxonomy.
4. Tender-proration model.
5. Paper trade 10 catalyst events before capital.

### Dark-Horse Sprint: Convertible Call / Mandatory Conversion

Sprint length: 2 weeks.

Sprint deliverables:

1. EDGAR search terms:
   - "notice of redemption"
   - "convertible notes"
   - "mandatory conversion"
   - "provisional redemption"
   - "conversion price"
   - "130% of the conversion price"
2. Build 2010-2026 event list.
3. Measure common-stock returns from announcement to conversion date and 1/5/20/60 trading days after conversion date.
4. Bucket by market cap, conversion shares as percent of float, pre-call short interest, and liquidity.
5. Decide: promote to research backlog or reject.

Promotion requires:

- At least 80 usable events.
- Net post-cost effect above 3% over 20-60 trading days in the target bucket.
- Mechanism-consistent timing.
- No dependence on shorting, options, or bond execution.

---

## 6. Solo Architecture

The production system has seven modules.

| Module | Name | Purpose |
|---|---|---|
| S1 | Event Ingestion | EDGAR, fund filings, corporate-action calendars, prices, NAVs |
| S2 | Mechanism Classifier | Forced flow, tax, mandate, tender, rebalance, informational, unknown |
| S3 | Eligibility Gate | Applies the six solo criteria before any test |
| S4 | Pre-Registered Backtester | Point-in-time, walk-forward, post-cost, capacity-capped |
| S5 | Paper-Trade Journal | Logs every live candidate, whether traded or skipped |
| S6 | Go/No-Go Evaluator | Promotes, pauses, or rejects strategies by fixed thresholds |
| S7 | Decay Monitor | Detects crowding, rising costs, disappearing effect size, or execution drift |

LLMs may assist with filing extraction and red-team critique, but no LLM output is a tradable signal.

---

## 7. Universal Pre-Registration Template

Every edge version must be committed before testing.

```yaml
strategy_name:
version:
date_registered:

edge_family:
mechanism:
citations:

universe:
  inclusion_rules:
  exclusion_rules:
  data_sources:
  survivorship_handling:

signal:
  trigger:
  thresholds:
  timing:

entry:
  order_type:
  entry_window:
  max_spread:
  max_position_vs_adv:

exit:
  primary_exit:
  time_exit:
  stop_loss:
  catalyst_failure_exit:

cost_model:
  commission:
  spread:
  slippage:
  borrow_or_financing: none
  tax_assumption:

capacity:
  max_strategy_capital:
  max_name_capital:
  max_percent_adv:

go_criteria:
  min_net_cagr:
  min_sharpe:
  max_drawdown:
  min_events:
  baseline_to_beat:

no_go_criteria:
  leakage_found:
  post_cost_failure:
  effect_wrong_sign:
  live_paper_miss:
```

---

## 8. Go / No-Go Gates

An edge can receive real capital only if all gates pass.

1. **Published baseline exists.** The strategy is not invented from a screen.
2. **Mechanism is observable.** The forced-flow or calendar driver is identifiable before entry.
3. **Point-in-time data passes audit.** No future constituent lists, restated data, survivorship-only tickers, or post-event filtering.
4. **Walk-forward test passes.** Minimum 10 years or full available sample, with outer folds by market regime when possible.
5. **Post-cost returns survive.** Spread, slippage, commissions, and no-fill assumptions are included.
6. **Capacity survives.** Test must be reported at $100k, $250k, $500k, $1M, and strategy-specific ceiling.
7. **Paper trade passes.** At least 6 months or one complete seasonal/catalyst cycle, depending on edge.
8. **Falsification rule is clear.** Every live position has a written invalidation condition.
9. **No hidden short/derivative dependency.** If the edge needs shorting, borrow, options, or futures to work, reject for this solo program.
10. **Bandwidth is realistic.** If operating the edge requires daily manual work that crowds out the core edge, defer.

Default thresholds:

- Minimum net annualized return: 8% for core strategies, 5% for sidecar strategies.
- Minimum Sharpe: 0.8 for core strategies, 0.6 for sidecar strategies.
- Maximum drawdown: 25%.
- Minimum live/paper events: 10 for event edges; one complete tax year for seasonal edges.
- Maximum position: lower of 2% of average daily dollar volume or 5% of strategy NAV.

---

## 9. Decay and Failure Rules

An edge is downgraded to DECAYED if any two conditions hold:

1. Net return falls below the go threshold for two consecutive evaluation cycles.
2. Slippage or spread consumes more than 50% of expected gross edge.
3. Entry-window alpha moves earlier than retail can execute.
4. Event count collapses below a useful sample or capacity.
5. New academic or practitioner evidence documents crowding or disappearance.
6. The effect survives only in names below the liquidity floor.
7. Live/paper trades miss expected direction or timing despite correct data.
8. The mechanism becomes informational rather than structural.

DECAYED does not mean the phenomenon is gone. It means the phenomenon is no longer worth a solo operator's capital and bandwidth after costs.

---

## 10. Rejected and Backlog Edges

| Edge | Verdict | Reason |
|---|---|---|
| PEAD / earnings drift | DECAYED | Current public-data alpha is too fast/weak/informational |
| Pre-FOMC drift | DECAYED | Post-2015 evidence shows disappearance or very short-lived effect |
| Month-end pension/rebalancing equity effect | MARGINAL/THIN | Real mechanism, but broad liquid instruments fail the capacity-constrained solo criterion |
| ETF NAV arbitrage | REQUIRES_INSTITUTIONAL | Real arbitrage belongs to APs and market makers |
| ADR / cross-listing arbitrage | REQUIRES_INSTITUTIONAL | Needs foreign custody, FX, conversion, and often short leg |
| Generic 13F piggybacking | DECAYED/MARGINAL | 45-day lag and no short book; fresh 13D activism only |
| Short-interest reversal | REQUIRES_INSTITUTIONAL | Literature supports short side more than long-only reversal |
| FDA/PDUFA calendar trades | DECAYED | Binary informational risk, not forced-flow alpha |
| Generic CEF discount reversion | MARGINAL | Too slow without catalyst |
| Generic SEO rebound | MARGINAL | Adverse selection overwhelms simple supply-shock logic |
| Rights offerings | MARGINAL | Potentially structural, but sparse and document-specific |
| Odd-lot tenders | FEASIBLE BUT TINY | Good sidecar, inadequate capacity |

---

## 11. Final Operating Rule

The solo operator should not seek "more edges" until the current edge has clean data, clean execution, and clean falsification.

Capital deployment order:

1. Spinoff stubs only.
2. Add tax-loss/window-dressing reversal only after the spinoff process is stable.
3. Add CEF activist/tender discount compression only after the tax-loss program is paper-traded.
4. Run convertible calls as a sprint, not a strategy.
5. Track odd-lot tenders opportunistically, but do not count them as core alpha.

The correct target is not cleverness. The target is **public, structural, capacity-constrained forced flow with rules written before the trade**.
