# SGFIN.NS — Hedge Fund Analysis
**Date:** 2026-07-19
**Model:** Google Gemini 3.1 Flash Lite
**Analysts:** All 19

---

## Input Data (via yfinance)

### Financial Metrics (TTM)
| Metric | Value |
|---|---|
| Market Cap | ₹41.59 billion |
| Enterprise Value | ₹66.19 billion |
| Revenue (TTM) | ₹3.94 billion |
| Net Income (TTM) | ₹1.53 billion |
| EPS (TTM) | ₹25.86 |
| Operating Margin | 92.1% |
| Gross Margin | 99.4% |
| Net Margin | 39.0% |
| ROE | 10.5% |
| Debt-to-Equity | 1.85 |
| Current Ratio | 1.35 |
| P/E Ratio | 23.75 |
| P/B Ratio | 2.82 |
| Revenue Growth (YoY) | 101.4% |
| Earnings Growth (YoY) | 119.3% |
| Payout Ratio | 0% (no dividends) |
| Book Value/Share | ₹223.73 |

### Historical Net Income (TTM periods)
| Period | Net Income |
|---|---|
| 2025-03-31 | ₹237.9M |
| 2025-06-30 | ₹483.1M |
| 2025-12-31 | ₹807.8M |
| 2026-03-31 | ₹1,230.5M |
| 2026-06-30 | ₹1,529.4M |

**Net Income CAGR (4 years): ~59%**

### Balance Sheet (latest quarter)
| Item | Value |
|---|---|
| Total Assets | ₹41.73 billion |
| Total Liabilities | ₹27.13 billion |
| Current Assets | ₹35.41 billion |
| Current Liabilities | ₹26.30 billion |
| Shareholders' Equity | ₹14.60 billion |

### Data Gaps
- Free cash flow: **not available** via yfinance for this ticker
- Dividends: **nil** (payout ratio = 0%)
- Share buyback/issuance history: **not available**

---

## Deterministic Scoring (Rakesh Jhunjhunwala Agent)

| Category | Score | Details |
|---|---|---|
| Profitability | 6/8 | ROE 10.5% (decent), Op margin 92% (excellent), EPS CAGR 57% (high) |
| Growth | 7/7 | Revenue CAGR 64%, Income CAGR 59%, consistent every period |
| Balance Sheet | 1/4 | Debt ratio 0.65 (moderate), Current ratio 1.35 (weak) |
| Cash Flow | 0/3 | FCF data unavailable; no dividends |
| Management | 0/2 | No buyback/issuance data |
| **Total** | **14/24 (58%)** | |

### Intrinsic Value (DCF)
- Growth rate capped: 20% (from 59% historical)
- Quality score: ~0.53 → medium quality
- Discount rate: 15%, Terminal multiple: 15×
- **Intrinsic Value: ₹28.0 billion**
- **Market Cap: ₹41.5 billion**
- **Margin of Safety: −32.6%** (overvalued)

---

## Agent Signals

| Agent | Signal | Confidence | Key Reasoning |
|---|---|---|---|
| Technical Analyst | NEUTRAL | 15% | ADX 25.5 (mild trend), RSI 57 neutral, high volatility (39% annualised) |
| Fundamentals Analyst | BEARISH | 75% | ROE/margin data N/A in metrics endpoint; P/E 23.7 and P/B 2.8 moderately elevated |
| Sentiment Analyst | BULLISH | 100% | 15 insider buys, 0 insider sells — strong insider conviction |
| Valuation Analyst | BEARISH | 78% | Residual income value ₹12.4B vs market cap ₹41.5B (−70% gap); DCF: no FCF periods available |
| Cathie Wood | NEUTRAL | 45% | Revenue growth 98% and 96% gross margins are impressive but no R&D data; negative FCF limits conviction |
| Bill Ackman | BEARISH | 95% | Negative FCF = wealth-destruction machine; D/E >1 signals poor financial discipline; no dividends or buybacks |
| Mohnish Pabrai | BEARISH | 95% | No positive FCF → not a business, a science project; D/E 1.85 is fragility; no margin of safety |
| Ben Graham | BEARISH | 90% | Current price ₹636 vs Graham Number ₹338 (−46.8% MoS); current ratio 1.35 below 2.0 threshold; no dividend record |
| Phil Fisher | BEARISH | 75% | ROE 8.7% inadequate for growth rate; D/E 1.85 + negative FCF = structural weakness; P/E 32.5 leaves no margin for error |
| Peter Lynch | BULLISH | 75% | PEG 0.84 (GARP sweet spot); strong insider buying; high-margin business with 10-bagger potential if FCF turns positive |
| Stanley Druckenmiller | NEUTRAL | 65% | 102% revenue growth + 15 insider buys vs D/E 1.85 + no FCF; asymmetric risk not yet met |
| Charlie Munger | BEARISH | 30% | Negative FCF, high leverage, zero predictability — reckless gamble |
| Warren Buffett | NEUTRAL | 40% | Insufficient fundamental data to assess moat or valuation |
| Aswath Damodaran | NEUTRAL | 10% | Cannot build reliable DCF; D/E 1.9 increases cost of capital; no ROIC history |
| Rakesh Jhunjhunwala | BEARISH | 85% | MoS −32%; debt ratio 0.65 + current ratio 1.35; ROE 10.5% mediocre; no FCF visibility |
| Michael Burry | BEARISH | 85% | FCF and EV/EBIT unavailable; net debt + opacity = unacceptable downside risk |
| Nassim Taleb | BEARISH | 75% | D/E 1.85 is a fragility trap; low vol signals complacency; leverage is ruinous |
| News Sentiment | BULLISH | 96.5% | 3 of 3 recent headlines classified bullish by LLM |
| Growth Analyst | — | — | Ran to completion; signal included in portfolio aggregation |

**Vote tally: 10 BEARISH · 3 BULLISH · 5 NEUTRAL**

---

## Trading Decision

| Field | Value |
|---|---|
| Action | **SHORT** |
| Quantity | 22 shares |
| Confidence | 88% |
| Reasoning | Strong consensus from value-investing agents overrides short-term sentiment spikes |

## Portfolio Summary

| Ticker | Action | Qty | Confidence | Bullish | Bearish | Neutral |
|---|---|---|---|---|---|---|
| SGFIN.NS | SHORT | 22 | 88% | 3 | 10 | 5 |

---

## Notes

- **Data source:** yfinance (auto-routed for `.NS` suffix; financialdatasets.ai is US-only)
- **LLM:** Google Gemini 3.1 Flash Lite (primary); fallback chain: OpenRouter free → local Ollama `qwen3.5:9b`
- **FCF data gap:** yfinance does not return free cash flow for SGFIN.NS, causing cash flow and valuation scores to be understated. Some agents (Bill Ackman, Cathie Wood) inferred negative FCF from balance sheet trends rather than direct FCF data.
- **Insider data:** 15 buy trades, 0 sells — the only strong bullish signal across all agents. Worth monitoring.
- **The bullish case in brief:** PEG 0.84, explosive revenue/earnings growth, dominant gross margins (99%), heavy insider buying.
- **The bearish case in brief:** Overvalued vs DCF intrinsic value (−33%), high leverage (D/E 1.85), weak liquidity (1.35), no FCF, no dividends, ROE only 10.5%.
