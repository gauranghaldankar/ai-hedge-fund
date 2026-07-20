# Indian Market Data Sources — Library Evaluation

## Summary

| Library | Status | Useful For | Not Useful For |
|---|---|---|---|
| **nselib** | ✅ Working | Price/volume, corporate actions (dividends/splits/buybacks), event calendar, short selling, deliverable positions | Financial statements, free cash flow |
| **bseindia** | ❌ Broken | Nothing currently — `all_listed_securities()` returns parse error | Everything |
| **mcxlib** | ❌ Broken | Commodity prices (gold, crude, etc.) — MCX API URL returned 404 | Everything until MCX fixes their API |

---

## nselib — What Works

### 1. Corporate Actions (dividends, splits, buybacks, rights)
```python
from nselib import capital_market
df = capital_market.corporate_actions_for_equity(
    from_date='01-01-2020', to_date='20-07-2026'
)
# Filter by symbol column
sgfin_actions = df[df['symbol'] == 'SGFIN']
```
**Returns:** `symbol`, `exDate`, `subject` (e.g. "Dividend - Rs 4.50 Per Share"), `recDate`, `bcStartDate`, `bcEndDate`, `isin`

**Fills gap:** Dividends ✅, Splits ✅, Buybacks ✅, Rights issues ✅

**Finding for SGFIN:** No corporate actions found → confirms yfinance's `payout_ratio=0` and no dividend history. Company is not returning cash to shareholders.

---

### 2. Event Calendar (board meetings, earnings dates, AGMs)
```python
df = capital_market.event_calendar_for_equity(
    from_date='01-01-2026', to_date='20-07-2026'
)
sgfin_events = df[df['symbol'] == 'SGFIN']
```
**Returns:** `symbol`, `company`, `purpose`, `bm_desc` (full board meeting description), `date`

**Fills gap:** Earnings announcement dates ✅, AGM dates ✅, NCD modifications ✅

**Finding for SGFIN:** Board met on 14-Jul-2026 to approve Q1 FY2027 results — very recent. Also approved NCD modifications (Feb 2026) confirming active debt management.

---

### 3. Price & Volume Data
```python
# Basic OHLCV
df = capital_market.price_volume_data(
    symbol='SGFIN', from_date='01-01-2026', to_date='20-07-2026'
)
# With deliverable quantity (institutional activity signal)
df = capital_market.price_volume_and_deliverable_position_data(
    symbol='SGFIN', from_date='01-01-2026', to_date='20-07-2026'
)
```
**Returns (deliverable version):** `Date`, `OpenPrice`, `HighPrice`, `LowPrice`, `ClosePrice`, `TotalTradedQuantity`, `DeliverableQty`, `%DlyQttoTradedQty`

**Fills gap:** Deliverable % (institutional vs speculative trading) ✅ — a signal yfinance does not provide. High deliverable % = more genuine buying/selling conviction.

**Finding for SGFIN (recent):**
| Date | Close | Deliverable % |
|---|---|---|
| 17-Jul-2026 | ₹631 | 47% |
| 16-Jul-2026 | ₹646 | 35% |
| 15-Jul-2026 | ₹626 | 17% |

15-Jul saw 4.3M shares traded (vs ~0.3M normal) at only 17% deliverable → mostly intraday/speculative volume spike.

---

### 4. Short Selling Data
```python
df = capital_market.short_selling_data(
    from_date='01-07-2026', to_date='20-07-2026'
)
```
**Returns:** `Date`, `Symbol`, `SecurityName`, `Quantity`

**Fills gap:** Short interest ✅ — no SGFIN short selling reported (low institutional short interest).

---

## Data Gaps That NONE of These Libraries Fill

| Gap | What's Needed | Alternative |
|---|---|---|
| **Free Cash Flow** | Quarterly P&L + cash flow statement | NSE XBRL filings (direct download), Screener.in scrape, Tickertape API |
| **Management Buybacks (quantified)** | Share repurchase amounts | Corporate actions `subject` field mentions buybacks but not amounts |
| **Outstanding shares history** | Quarterly share count | BSE filings, company annual reports |
| **Insider trade values** | SEBI SAST/PIT disclosures | SEBI website scrape (no public API) |
| **R&D spend** | Income statement breakdown | NSE XBRL / annual reports only |

---

## Recommendation: How to Integrate into yf_api.py

Use `nselib` as a **supplementary layer** after yfinance — only called when yfinance returns `None` for specific fields:

```python
# Proposed pattern in yf_api.py (not yet implemented)
def _nse_corporate_actions(symbol: str) -> dict:
    """Return dividend history and buyback events from NSE."""
    from nselib import capital_market
    # Strip .NS suffix for NSE queries
    nse_symbol = symbol.replace('.NS', '').replace('.BO', '')
    df = capital_market.corporate_actions_for_equity(
        from_date='01-01-2015', to_date=datetime.today().strftime('%d-%m-%Y')
    )
    if df is None or df.empty:
        return {}
    rows = df[df['symbol'] == nse_symbol]
    dividends = rows[rows['subject'].str.contains('Dividend', case=False, na=False)]
    buybacks  = rows[rows['subject'].str.contains('Buy.?back', case=False, na=False)]
    return {
        'has_dividend_history': not dividends.empty,
        'last_dividend': dividends.iloc[0]['subject'] if not dividends.empty else None,
        'has_buyback': not buybacks.empty,
    }
```

**Fields this would fix in the agent analysis:**
- `cashflow_analysis.score` — "Company pays dividends" → currently always 0 for SGFIN (correctly, since no dividends confirmed)
- `management_analysis.score` — "Company buying back shares" → currently 0 due to missing data; NSE confirms no buybacks either
- Deliverable % → new signal for `technical_analyst` (institutional conviction)

---

## mcxlib — When It's Fixed

MCX (Multi Commodity Exchange) is relevant for companies with commodity exposure (metals, energy, agri). SGFIN is a finance company — **mcxlib is not relevant for SGFIN**. It would be relevant for commodity-heavy companies (e.g. HINDUNILVR.NS for agri, ONGC.NS for crude).

When MCX fixes their API, mcxlib provides:
- Live commodity prices (`get_market_watch`)
- Historical commodity data (`get_historical_data`)
- Option chains for commodities (`get_option_chain`)
- Put/call ratios (`get_put_call_ratio`)
