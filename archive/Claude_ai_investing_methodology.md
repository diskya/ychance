# Methodology: AI as a "Variant Perception Engine"

Your framing matters: commodity AI trading (factor mining, sentiment scores, alt-data scraping) is already a crowded graveyard. Alpha half-life on novel alt-data has collapsed from ~36 months to ~18. The edge is no longer **information** — it's **synthesis, second-order belief modeling, and reflexivity**. Here's the approach I'd actually build around.

## Core thesis

AI's real, non-commoditized edge over humans is **holding more variables in working memory, across more domains, for longer causal chains.** A good analyst tracks ~7 variables in one industry. An LLM can trace "Indonesian nickel export rule → CAM cathode margin → EV OEM gross margin → auto ABS spreads → regional bank exposure" in one pass. That's not "prediction" — it's **structured synthesis nobody is bothering to do because it's tedious.**

The sibling edge is **modeling belief**: not "what is fair value" but "what does the market currently believe, where is that wrong, and what will they believe next." This is the Soros / Druckenmiller / Steinhardt tradition — variant perception — now operationalizable because LLMs can read and structure consensus at scale.

## The seven pillars

**1. Explicit consensus mapping before any idea generation.**
Before hunting signals, have the AI build a structured map of what the market currently believes: sell-side estimates, implied probabilities from options, positioning (CFTC, 13F deltas, dealer gamma), narrative cluster analysis on Bloomberg/Twitter/earnings transcripts. You are not looking for "good companies" — you are looking for the **delta between consensus and your reconstructed truth.** No delta, no trade.

**2. Long causal-chain reasoning across domains.**
The durable edge is stitching together signals that live in different worlds: a regulatory filing in Jakarta, a shipping manifest out of Rotterdam, a Reddit thread, a Fed dot plot, a patent grant. Ask the LLM to produce a **causal graph with explicit transmission mechanisms and time lags** between a given catalyst and a tradeable instrument. Humans give up at chain length 3; the machine doesn't. Most "obvious in retrospect" trades live at chain length 4-6.

**3. Reflexivity / narrative-ignition detection.**
Stop trying to predict fundamentals; track **the narrative lifecycle**. Stories have a phase transition: niche → specialist media → Bloomberg headline → CNBC → retail. The AI's job is to detect stories at phase 1-2 and identify the *structural reasons* a story will or won't ignite (does it have a villain? a number? a chart that fits on a tweet?). Per Shiller: viral economic narratives move prices before fundamentals. Enter pre-ignition, exit at peak velocity, not peak price.

**4. Second-order reaction-function modeling.**
Instead of "what will the CPI print be," ask: *given* a print of X, what does each market tribe do next? Systematic CTAs flip at what level? Risk-parity deleverages where? Dealers flip from short-gamma to long-gamma at what SPX level? Vol-control funds add or cut? Passive rebalance dates? This is the highest-ROI question an LLM can answer well, because it requires holding 10+ participant models in parallel — something humans can't, but where rules are mostly public.

**5. Forced-flow hunting.**
Some flows are non-discretionary and therefore *knowable*: index rebalances, benchmark-relative managers dumping underperformers at quarter-end, margin-call cascades, tax-loss selling, lockup expirations, M&A arb unwinds, bond-index duration drift, SOFR-related collateral shifts. AI is ideal for maintaining a live calendar of structural, price-insensitive flows and the liquidity conditions that amplify them.

**6. Base-rate rigor (Tetlock discipline).**
Every idea gets an **outside view first, inside view second.** "Historical base rate of similar setups" → then adjust. This is the superforecaster move that almost no discretionary investor does consistently and that LLMs are uniquely good at (they've read more analogs than any human). Write ideas as probability distributions, not point targets. Track calibration; kill the sources of ideas that are systematically overconfident.

**7. Adversarial self-challenge.**
Every long idea must survive a structured red-team pass: what does the smartest bear believe, what would falsify this in the next 30 days, who is on the other side and why. Run this as a separate LLM pass with an adversarial prompt, not the same one that generated the idea. This single discipline kills ~60% of ideas and is where most "AI investment agent" projects fail — they confirm rather than challenge.

## Daily operating loop

1. **Morning:** Consensus refresh — what changed in sell-side estimates, positioning, implied vols, narrative clusters overnight.
2. **Scan:** Long-chain causal sweep across a watchlist of structural themes (e.g., "grid capacity," "semi capex cycle," "GLP-1 second-order").
3. **Filter:** Only ideas where *consensus delta × catalyst proximity × asymmetry* clears a threshold.
4. **Red-team:** Adversarial pass. Kill or proceed.
5. **Size by base rate + path:** Position size = f(edge, odds of being right on timing, pain tolerance before thesis invalidates).
6. **Journal the prediction, not the P&L.** Track calibration — were 70%-confidence calls right 70% of the time? This is the only way to know if the edge is real vs. lucky.

## What to deliberately not do

- Don't build a sentiment scoring pipeline (commoditized, decays fast).
- Don't fine-tune price-prediction models on OHLCV (information is in the tape everyone sees).
- Don't run multi-agent "Buffett / Munger / Soros personas" — cute demo, no edge; they regress to mean.
- Don't trust backtests on anything narrative-driven (regime-dependent, overfits trivially).
- Don't add speed / HFT — you lose. The edge is on the 3-day to 3-month horizon where humans underreact to structural change and AI can outwork them.

## How you'll know it's working

Not by P&L (too noisy short-term). By **calibration drift** and **idea differentiation**: are your 70% calls right 70%? Are your theses demonstrably different from sell-side? Can you name the counterparty on every trade and why they're wrong? If not, you don't have edge — you have exposure.

## The real unlock

The unconventional part isn't any one pillar — it's **refusing to use AI as a faster analyst** and instead using it as **(a) a synthesizer across domains no human bothers with, and (b) a model of other participants' beliefs.** Most AI-investing work conflates these with "predict the price." The price is the wrong target. The **delta between consensus and reality**, and **the reaction function of the crowd to new information**, is the target. Get those right and P&L follows.

## Sources

- [Permutable AI — narrative-based macro trading](https://beststartup.co.uk/how-uk-startup-permutable-ai-is-redefining-macro-news-trading-intelligence/)
- [Alpha decay and crowded alt-data](https://www.exegy.com/alpha-decay/)
- [Not All Factors Crowd Equally (arxiv 2025)](https://arxiv.org/html/2512.11913v1)
- [Soros reflexivity — Capital Gains](https://capitalgains.thediff.co/p/george-soros-theory-reflexivity)
- [Reflexivity & second-level thinking](https://thinksquared.substack.com/p/reflexivity-and-second-level-thinking)
- [Druckenmiller — Macro Ops lessons](https://macro-ops.com/lessons-from-a-trading-great-stanley-druckenmiller/)
- [Variant Perception — five dimensions (CFA)](https://blogs.cfainstitute.org/investor/2015/11/27/the-five-dimensions-of-variant-perception/)
- [Variant Perception & market consensus — Macro Ops](https://macro-ops.com/variant-perception-and-how-the-market-is-always-wrong/)
- [Shiller — Narrative Economics (NBER)](https://www.nber.org/papers/w23075)
- [Tetlock Superforecasting — base rates](https://www.cultivatelabs.com/posts/superforecasting-everything-has-a-base-rate)
- [Superforecasting a bear market — Integrating Investor](https://integratinginvestor.com/superforecasting-a-bear-market/)
- [Gamma exposure & dealer positioning](https://www.cheddarflow.com/blog/what-is-gamma-exposure-an-in-depth-analysis-for-traders/)
- [LLMs in equity markets (Frontiers 2025)](https://www.frontiersin.org/journals/artificial-intelligence/articles/10.3389/frai.2025.1608365/full)
- [CFA — Unstructured data and AI](https://rpc.cfainstitute.org/sites/default/files/-/media/documents/article/industry-research/unstructured-data-and-ai.pdf)
- [AI forecasting benchmark — Metaculus](https://www.metaculus.com/aib/)
