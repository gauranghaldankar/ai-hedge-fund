"""yfinance-backed data layer — drop-in replacement for the financialdatasets.ai
functions in api.py, used automatically for any ticker containing a dot-suffix
exchange code (e.g. .NS for NSE India, .BO for BSE India).

Implements the same public signatures as src/tools/api.py so zero agent code
needs to change.
"""

import logging
import warnings
from datetime import datetime

import pandas as pd
import yfinance as yf

# Suppress yfinance's own HTTP-error prints (401s for restricted endpoints)
logging.getLogger("yfinance").setLevel(logging.CRITICAL)

from src.data.cache import get_cache
from src.data.models import (
    CompanyNews,
    FinancialMetrics,
    InsiderTrade,
    LineItem,
    Price,
)

logger = logging.getLogger(__name__)
warnings.filterwarnings("ignore")

_cache = get_cache()

# ── Helpers ───────────────────────────────────────────────────────────────────

def _safe(val, default=None):
    """Return None for NaN/None values; convert numpy scalars to Python natives."""
    if val is None:
        return default
    try:
        if pd.isna(val):
            return default
    except Exception:
        pass
    # numpy scalars (float64, bool_, int64, …) are not JSON-serialisable; unwrap them.
    if hasattr(val, "item"):
        return val.item()
    return val


def _row(df: pd.DataFrame, label: str):
    """Return the row Series for *label* if it exists in df.index, else None."""
    if df is None or df.empty or label not in df.index:
        return None
    return df.loc[label]


def _col_val(df: pd.DataFrame, label: str, col_idx: int = 0):
    """Return the scalar value at df.loc[label].iloc[col_idx], or None."""
    row = _row(df, label)
    if row is None or len(row) <= col_idx:
        return None
    return _safe(row.iloc[col_idx])


def _ttm_income(t: yf.Ticker) -> pd.Series:
    """TTM income statement = sum of last 4 quarters."""
    q = t.quarterly_income_stmt
    if q is None or q.empty:
        return pd.Series(dtype=float)
    cols = q.columns[:4]  # most recent 4 quarters
    return q[cols].sum(axis=1)


def _ttm_cashflow(t: yf.Ticker) -> pd.Series:
    """TTM cash flow = sum of last 4 quarters."""
    q = t.quarterly_cashflow
    if q is None or q.empty:
        return pd.Series(dtype=float)
    cols = q.columns[:4]
    return q[cols].sum(axis=1)


def _recent_balance(t: yf.Ticker) -> pd.Series:
    """Most recent quarterly balance sheet snapshot."""
    q = t.quarterly_balance_sheet
    if q is None or q.empty:
        return pd.Series(dtype=float)
    return q.iloc[:, 0]  # most recent column


def _s(series: pd.Series, label: str):
    """Safe lookup into a Series by label."""
    if series is None or label not in series.index:
        return None
    return _safe(series[label])


# ── Prices ────────────────────────────────────────────────────────────────────

def get_prices(ticker: str, start_date: str, end_date: str, api_key=None) -> list[Price]:
    cache_key = f"yf_{ticker}_{start_date}_{end_date}"
    if cached := _cache.get_prices(cache_key):
        return [Price(**p) for p in cached]

    df = yf.download(ticker, start=start_date, end=end_date,
                     auto_adjust=True, progress=False)
    if df is None or df.empty:
        logger.warning("yfinance returned no price data for %s", ticker)
        return []

    # yfinance may return MultiIndex columns when downloading a single ticker
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    prices: list[Price] = []
    for idx, row in df.iterrows():
        try:
            prices.append(Price(
                open=float(row["Open"]),
                close=float(row["Close"]),
                high=float(row["High"]),
                low=float(row["Low"]),
                volume=int(row["Volume"]),
                time=idx.strftime("%Y-%m-%dT00:00:00"),
            ))
        except Exception as e:
            logger.debug("Skipping price row for %s on %s: %s", ticker, idx, e)

    if prices:
        _cache.set_prices(cache_key, [p.model_dump() for p in prices])
    return prices


# ── Financial Metrics ─────────────────────────────────────────────────────────

def get_financial_metrics(
    ticker: str,
    end_date: str,
    period: str = "ttm",
    limit: int = 10,
    api_key=None,
) -> list[FinancialMetrics]:
    cache_key = f"yf_fm_{ticker}_{period}_{end_date}_{limit}"
    if cached := _cache.get_financial_metrics(cache_key):
        return [FinancialMetrics(**m) for m in cached]

    t = yf.Ticker(ticker)
    info = t.info or {}

    def ig(key):
        return _safe(info.get(key))

    # debt_to_equity: yfinance returns as percentage (e.g. 185 = 185%)
    # normalise to a ratio so agents get consistent values (e.g. 1.85)
    dte_raw = ig("debtToEquity")
    dte = (dte_raw / 100.0) if dte_raw is not None else None

    metrics = FinancialMetrics(
        ticker=ticker,
        report_period=end_date,
        period=period,
        currency=ig("currency") or "INR",
        market_cap=ig("marketCap"),
        enterprise_value=ig("enterpriseValue"),
        price_to_earnings_ratio=ig("trailingPE"),
        price_to_book_ratio=ig("priceToBook"),
        price_to_sales_ratio=ig("priceToSalesTrailing12Months"),
        enterprise_value_to_ebitda_ratio=ig("enterpriseToEbitda"),
        enterprise_value_to_revenue_ratio=ig("enterpriseToRevenue"),
        free_cash_flow_yield=None,
        peg_ratio=ig("pegRatio"),
        gross_margin=ig("grossMargins"),
        operating_margin=ig("operatingMargins"),
        net_margin=ig("profitMargins"),
        return_on_equity=ig("returnOnEquity"),
        return_on_assets=ig("returnOnAssets"),
        return_on_invested_capital=None,
        asset_turnover=None,
        inventory_turnover=None,
        receivables_turnover=None,
        days_sales_outstanding=None,
        operating_cycle=None,
        working_capital_turnover=None,
        current_ratio=ig("currentRatio"),
        quick_ratio=ig("quickRatio"),
        cash_ratio=None,
        operating_cash_flow_ratio=None,
        debt_to_equity=dte,
        debt_to_assets=None,
        interest_coverage=None,
        revenue_growth=ig("revenueGrowth"),
        earnings_growth=ig("earningsGrowth"),
        book_value_growth=None,
        earnings_per_share_growth=None,
        free_cash_flow_growth=None,
        operating_income_growth=None,
        ebitda_growth=None,
        payout_ratio=ig("payoutRatio"),
        earnings_per_share=ig("trailingEps"),
        book_value_per_share=ig("bookValue"),
        free_cash_flow_per_share=None,
    )

    result = [metrics]
    _cache.set_financial_metrics(cache_key, [m.model_dump() for m in result])
    return result


# ── Line Items ────────────────────────────────────────────────────────────────

# Map from the API field names agents request → yfinance statement row labels
_INCOME_MAP = {
    "revenue": "Total Revenue",
    "gross_profit": "Gross Profit",
    "operating_income": "Operating Income",
    "operating_expense": "Operating Expense",
    "ebitda": "EBITDA",
    "ebit": "EBIT",
    "net_income": "Net Income",
    "interest_expense": "Interest Expense",
    "research_and_development": "Research And Development",
    "earnings_per_share": "Basic EPS",
    "depreciation_and_amortization": "Reconciled Depreciation",
    "gross_margin": None,    # calculated below
    "operating_margin": None,
}

_BALANCE_MAP = {
    "total_assets": "Total Assets",
    "total_liabilities": "Total Liabilities Net Minority Interest",
    "current_assets": "Current Assets",
    "current_liabilities": "Current Liabilities",
    "cash_and_equivalents": "Cash And Cash Equivalents",
    "total_debt": "Total Debt",
    "shareholders_equity": "Stockholders Equity",
    "goodwill_and_intangible_assets": "Goodwill And Other Intangible Assets",
    "intangible_assets": "Other Intangible Assets",
    "working_capital": "Working Capital",
    "book_value_per_share": None,   # calculated below
    "outstanding_shares": "Ordinary Shares Number",
    "debt_to_equity": None,         # calculated below
    "return_on_invested_capital": None,  # calculated below
}

_CASHFLOW_MAP = {
    "free_cash_flow": "Free Cash Flow",
    "capital_expenditure": "Capital Expenditure",
    "depreciation_and_amortization": "Depreciation And Amortization",
    "dividends_and_other_cash_distributions": "Common Stock Issuance",  # best proxy
    "issuance_or_purchase_of_equity_shares": "Net Common Stock Issuance",
}


def _extract_period(
    t: yf.Ticker,
    line_items: list[str],
    period: str,
    col_idx: int,
) -> LineItem | None:
    """Extract one period's worth of line items from yfinance statements."""

    # Choose annual vs quarterly statements
    if period == "annual":
        inc = t.income_stmt
        bs = t.balance_sheet
        cf = t.cashflow
    else:
        # TTM: sum last 4 quarters for flows; most recent quarter for stocks
        inc = t.quarterly_income_stmt
        bs = t.quarterly_balance_sheet
        cf = t.quarterly_cashflow

    if (inc is None or inc.empty) and (bs is None or bs.empty):
        return None

    # Determine the report date from whichever statement has data
    report_date = None
    for stmt in (inc, bs, cf):
        if stmt is not None and not stmt.empty and len(stmt.columns) > col_idx:
            report_date = stmt.columns[col_idx]
            break
    if report_date is None:
        return None

    report_period = pd.Timestamp(report_date).strftime("%Y-%m-%d")

    # For TTM income/cashflow: sum last 4 quarters up to col_idx window
    if period != "annual":
        n_q = 4  # number of quarters to sum
        inc_ttm = (
            inc.iloc[:, col_idx: col_idx + n_q].sum(axis=1)
            if inc is not None and not inc.empty and len(inc.columns) > col_idx
            else pd.Series(dtype=float)
        )
        cf_ttm = (
            cf.iloc[:, col_idx: col_idx + n_q].sum(axis=1)
            if cf is not None and not cf.empty and len(cf.columns) > col_idx
            else pd.Series(dtype=float)
        )
        bs_snap = (
            bs.iloc[:, col_idx]
            if bs is not None and not bs.empty and len(bs.columns) > col_idx
            else pd.Series(dtype=float)
        )
    else:
        inc_ttm = (
            inc.iloc[:, col_idx]
            if inc is not None and not inc.empty and len(inc.columns) > col_idx
            else pd.Series(dtype=float)
        )
        cf_ttm = (
            cf.iloc[:, col_idx]
            if cf is not None and not cf.empty and len(cf.columns) > col_idx
            else pd.Series(dtype=float)
        )
        bs_snap = (
            bs.iloc[:, col_idx]
            if bs is not None and not bs.empty and len(bs.columns) > col_idx
            else pd.Series(dtype=float)
        )

    def gi(series, label):
        """Get value from series by label, return None if missing."""
        if series is None or label not in series.index:
            return None
        return _safe(series[label])

    extras: dict = {}
    for field in line_items:
        val = None

        if field in _INCOME_MAP and _INCOME_MAP[field]:
            val = gi(inc_ttm, _INCOME_MAP[field])
        elif field in _CASHFLOW_MAP and _CASHFLOW_MAP[field]:
            val = gi(cf_ttm, _CASHFLOW_MAP[field])
            # capital_expenditure is negative in yfinance; return absolute value
            if field == "capital_expenditure" and val is not None:
                val = abs(val)
        elif field in _BALANCE_MAP and _BALANCE_MAP[field]:
            val = gi(bs_snap, _BALANCE_MAP[field])

        # Calculated fields
        if field == "gross_margin":
            rev = gi(inc_ttm, "Total Revenue")
            gp = gi(inc_ttm, "Gross Profit")
            val = (gp / rev) if rev and gp else None
        elif field == "operating_margin":
            rev = gi(inc_ttm, "Total Revenue")
            oi = gi(inc_ttm, "Operating Income")
            val = (oi / rev) if rev and oi else None
        elif field == "book_value_per_share":
            eq = gi(bs_snap, "Stockholders Equity")
            sh = gi(bs_snap, "Ordinary Shares Number")
            val = (eq / sh) if eq and sh else None
        elif field == "debt_to_equity":
            debt = gi(bs_snap, "Total Debt")
            eq = gi(bs_snap, "Stockholders Equity")
            val = (debt / eq) if debt and eq else None
        elif field == "working_capital":
            ca = gi(bs_snap, "Current Assets")
            cl = gi(bs_snap, "Current Liabilities")
            val = (ca - cl) if ca is not None and cl is not None else None
        elif field == "return_on_invested_capital":
            ebit = gi(inc_ttm, "EBIT")
            ta = gi(bs_snap, "Total Assets")
            cl = gi(bs_snap, "Current Liabilities")
            if ebit and ta and cl:
                ic = ta - cl
                val = (ebit / ic) if ic else None

        extras[field] = val

    info = t.info or {}
    currency = _safe(info.get("currency")) or "INR"

    return LineItem(
        ticker=t.ticker,
        report_period=report_period,
        period=period,
        currency=currency,
        **extras,
    )


def search_line_items(
    ticker: str,
    line_items: list[str],
    end_date: str,
    period: str = "ttm",
    limit: int = 10,
    api_key=None,
) -> list[LineItem]:
    t = yf.Ticker(ticker)

    # How many periods are available?
    if period == "annual":
        n_cols = len(t.income_stmt.columns) if t.income_stmt is not None and not t.income_stmt.empty else 0
    else:
        n_cols = len(t.quarterly_income_stmt.columns) if t.quarterly_income_stmt is not None and not t.quarterly_income_stmt.empty else 0

    n_periods = min(limit, max(n_cols, 1))
    results: list[LineItem] = []

    for i in range(n_periods):
        item = _extract_period(t, line_items, period, col_idx=i)
        if item is not None:
            results.append(item)

    return results


# ── Insider Trades ────────────────────────────────────────────────────────────

def get_insider_trades(
    ticker: str,
    end_date: str,
    start_date: str | None = None,
    limit: int = 1000,
    api_key=None,
) -> list[InsiderTrade]:
    cache_key = f"yf_it_{ticker}_{start_date or 'none'}_{end_date}_{limit}"
    if cached := _cache.get_insider_trades(cache_key):
        return [InsiderTrade(**tr) for tr in cached]

    t = yf.Ticker(ticker)
    try:
        df = t.insider_transactions
    except Exception as e:
        logger.warning("Failed to fetch insider trades for %s: %s", ticker, e)
        return []

    if df is None or df.empty:
        return []

    trades: list[InsiderTrade] = []
    for _, row in df.iterrows():
        try:
            tx_date = str(row.get("Start Date", ""))[:10] or None
            if start_date and tx_date and tx_date < start_date:
                continue
            if tx_date and tx_date > end_date:
                continue

            shares = _safe(row.get("Shares"))
            value = _safe(row.get("Value"))
            price_per_share = None
            if shares and value and shares != 0:
                try:
                    price_per_share = float(value) / float(shares)
                except Exception:
                    pass

            trades.append(InsiderTrade(
                ticker=ticker,
                issuer=None,
                name=str(row.get("Insider", "")) or None,
                title=str(row.get("Position", "")) or None,
                is_board_director=None,
                transaction_date=tx_date,
                transaction_shares=float(shares) if shares is not None else None,
                transaction_price_per_share=price_per_share,
                transaction_value=float(value) if value is not None else None,
                shares_owned_before_transaction=None,
                shares_owned_after_transaction=None,
                security_title=None,
                filing_date=tx_date or end_date,
            ))
        except Exception as e:
            logger.debug("Skipping insider trade row: %s", e)

    trades = trades[:limit]
    if trades:
        _cache.set_insider_trades(cache_key, [tr.model_dump() for tr in trades])
    return trades


# ── Company News ──────────────────────────────────────────────────────────────

def get_company_news(
    ticker: str,
    end_date: str,
    start_date: str | None = None,
    limit: int = 1000,
    api_key=None,
) -> list[CompanyNews]:
    cache_key = f"yf_cn_{ticker}_{start_date or 'none'}_{end_date}_{limit}"
    if cached := _cache.get_company_news(cache_key):
        return [CompanyNews(**n) for n in cached]

    t = yf.Ticker(ticker)
    try:
        raw_news = t.news or []
    except Exception as e:
        logger.warning("Failed to fetch news for %s: %s", ticker, e)
        return []

    news_list: list[CompanyNews] = []
    for item in raw_news:
        try:
            # yfinance 1.x wraps content in item['content']
            content = item.get("content", item)
            title = content.get("title", "")
            pub_date = content.get("pubDate", content.get("displayTime", ""))
            article_date = pub_date[:10] if pub_date else ""

            if start_date and article_date and article_date < start_date:
                continue
            if article_date and article_date > end_date:
                continue

            provider = content.get("provider", {})
            source = (
                provider.get("displayName", "")
                if isinstance(provider, dict)
                else str(provider)
            )
            url = (
                (content.get("canonicalUrl") or {}).get("url", "")
                or (content.get("clickThroughUrl") or {}).get("url", "")
                or ""
            )

            news_list.append(CompanyNews(
                ticker=ticker,
                title=title,
                author=None,
                source=source or "Yahoo Finance",
                date=article_date or end_date,
                url=url,
                sentiment=None,
            ))
        except Exception as e:
            logger.debug("Skipping news item: %s", e)

    news_list = news_list[:limit]
    if news_list:
        _cache.set_company_news(cache_key, [n.model_dump() for n in news_list])
    return news_list


# ── Market Cap ────────────────────────────────────────────────────────────────

def get_market_cap(ticker: str, end_date: str, api_key=None) -> float | None:
    t = yf.Ticker(ticker)
    info = t.info or {}
    return _safe(info.get("marketCap"))


# ── DataFrame helpers (same as api.py) ───────────────────────────────────────

def prices_to_df(prices: list[Price]) -> "pd.DataFrame":
    import pandas as pd
    df = pd.DataFrame([p.model_dump() for p in prices])
    if df.empty:
        return df
    df["Date"] = pd.to_datetime(df["time"])
    df.set_index("Date", inplace=True)
    for col in ["open", "close", "high", "low", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df.sort_index(inplace=True)
    return df


def get_price_data(ticker: str, start_date: str, end_date: str, api_key=None) -> "pd.DataFrame":
    return prices_to_df(get_prices(ticker, start_date, end_date, api_key=api_key))
