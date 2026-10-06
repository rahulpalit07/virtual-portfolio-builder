"""Data fetching: ticker/name resolution, historical prices and TTM dividend yield.

Per PROJECT_SPEC.md Sections 2.1 and 2.2. No returns/risk calculations live here.
"""

import logging
import re
from dataclasses import dataclass, field

import pandas as pd
import yfinance as yf

# yfinance logs a 404 for every ticker probe that doesn't exist; we report those ourselves
logging.getLogger("yfinance").setLevel(logging.CRITICAL)

EXCHANGES = ["India (NSE)", "Australia (ASX)", "USA"]

# Yahoo Finance suffix per exchange (Section 2.1)
EXCHANGE_SUFFIX = {
    "India (NSE)": ".NS",
    "Australia (ASX)": ".AX",
    "USA": "",
}

# Yahoo search `exchange` codes accepted for each exchange. BSE (.BO), US OTC (PNK),
# NYSE Arca (PCX) and Cboe (BTS) are deliberately excluded: the latter two are ETF venues.
EXCHANGE_SEARCH_CODES = {
    "India (NSE)": {"NSI"},
    "Australia (ASX)": {"ASX"},
    "USA": {"NYQ", "NYS", "NMS", "NGM", "NCM", "NAS", "ASE"},
}

# Ordinary shares only (Yahoo labels preference shares, notes, warrants and units as
# EQUITY too). Share classes like BRK-B are kept.
NON_COMMON_SUFFIX = re.compile(r"-(P[A-Z]?|WT|WS|W|RT|U|UN)$")
NON_COMMON_NAME = re.compile(r"\b(notes?|debentures?|preferred|warrants?)\b", re.IGNORECASE)
LOOKS_LIKE_TICKER = re.compile(r"^[A-Za-z0-9.\-&]{1,15}$")

SEARCH_MAX_RESULTS = 10

LOOKBACK_PERIOD = "5y"
INTERVAL = "1d"
MIN_HISTORY_YEARS = 3


@dataclass
class Candidate:
    """One possible stock match for a user's input."""

    symbol: str  # Yahoo symbol, e.g. RELIANCE.NS
    name: str
    exchange_display: str

    @property
    def label(self) -> str:
        return f"{self.symbol}: {self.name} ({self.exchange_display})"


# Resolution statuses
EXACT = "exact"  # input was a ticker that exists on the chosen exchange
SINGLE = "single"  # name search found exactly one match
MULTIPLE = "multiple"  # several matches; the user must check the pre-selected one
NO_MATCH = "none"


@dataclass
class Resolution:
    """Outcome of resolving one user input (ticker or company name) on one exchange."""

    query: str
    exchange: str
    candidates: list[Candidate] = field(default_factory=list)  # best match first
    status: str = NO_MATCH
    error: str | None = None  # set if the lookup itself failed (network etc.)
    note: str | None = None  # explains a rejected match, e.g. an ETF ticker


@dataclass
class TickerData:
    """Result of fetching one ticker. `error` is set when nothing usable came back."""

    input_ticker: str
    exchange: str
    yahoo_symbol: str
    company_name: str | None = None
    prices: pd.DataFrame = field(default_factory=pd.DataFrame)
    currency: str | None = None
    last_price: float | None = None  # latest Close in `prices`; intraday if the market is open
    last_price_date: pd.Timestamp | None = None
    ttm_dividend_yield: float | None = None  # fraction, e.g. 0.025 = 2.5%; None = unavailable
    ttm_dividends_paid: float | None = None  # per-share, in `currency`
    error: str | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.error is None


def to_yahoo_symbol(ticker: str, exchange: str) -> str:
    """Convert a user-entered ticker + exchange into the symbol Yahoo Finance expects."""
    if exchange not in EXCHANGE_SUFFIX:
        raise ValueError(f"Unknown exchange: {exchange!r}")

    symbol = ticker.strip().upper()
    suffix = EXCHANGE_SUFFIX[exchange]

    if suffix:
        # Don't double-append if the user already typed it (e.g. "RELIANCE.NS")
        if not symbol.endswith(suffix):
            symbol += suffix
    else:
        # Yahoo uses dashes for US share classes: BRK.B -> BRK-B
        symbol = symbol.replace(".", "-")

    return symbol


def _search(query: str, exchange: str) -> list[Candidate]:
    """Yahoo symbol search, filtered to ordinary shares on the chosen exchange."""
    quotes = yf.Search(
        query, max_results=SEARCH_MAX_RESULTS, news_count=0, enable_fuzzy_query=False
    ).quotes
    allowed = EXCHANGE_SEARCH_CODES[exchange]
    candidates = []
    for q in quotes:
        symbol = q.get("symbol") or ""
        name = q.get("longname") or q.get("shortname") or ""
        if q.get("quoteType") != "EQUITY" or q.get("exchange") not in allowed:
            continue
        if NON_COMMON_SUFFIX.search(symbol) or NON_COMMON_NAME.search(name):
            continue
        candidates.append(
            Candidate(symbol, name or "(name unavailable)", q.get("exchDisp") or q["exchange"])
        )
    return candidates


def _direct_ticker_candidate(symbol: str, exchange: str) -> tuple[Candidate | None, str | None]:
    """Fallback for tickers Yahoo's search doesn't surface: check the symbol trades.

    Returns (candidate, note); note explains a rejection, e.g. the ticker is an ETF.
    """
    t = yf.Ticker(symbol)
    if t.history(period="5d").empty:
        return None, None
    try:
        info = t.info
    except Exception:
        info = {}
    quote_type = info.get("quoteType")
    if quote_type and quote_type != "EQUITY":
        return None, f"{symbol} is not a stock (Yahoo type: {quote_type}); only stocks are supported."
    name = info.get("longName") or info.get("shortName")
    return Candidate(symbol, name or "(name unavailable, verify this ticker)", exchange), None


def resolve(query: str, exchange: str) -> Resolution:
    """Resolve a ticker or company name to candidate stocks on the chosen exchange.

    Never raises; lookup failures are reported in `Resolution.error`.
    """
    query = query.strip()
    result = Resolution(query=query, exchange=exchange)
    if not query:
        result.error = "Empty input."
        return result

    try:
        candidates = _search(query, exchange)

        # If the input could be a ticker, make sure that exact ticker is considered
        exact = None
        if LOOKS_LIKE_TICKER.match(query):
            symbol = to_yahoo_symbol(query, exchange)
            exact = next((c for c in candidates if c.symbol == symbol), None)
            if exact is None and symbol != query:
                # e.g. "cba" -> also search "CBA.AX"
                exact = next((c for c in _search(symbol, exchange) if c.symbol == symbol), None)
            if exact is None:
                exact, result.note = _direct_ticker_candidate(symbol, exchange)
    except Exception as e:  # network/HTTP problems
        result.error = f"Lookup failed: {type(e).__name__}: {e}"
        return result

    if exact is not None:
        candidates = [exact] + [c for c in candidates if c.symbol != exact.symbol]

    # Drop duplicate symbols, keeping rank order
    seen: set[str] = set()
    result.candidates = [c for c in candidates if not (c.symbol in seen or seen.add(c.symbol))]

    if exact is not None:
        result.status = EXACT
    elif len(result.candidates) == 1:
        result.status = SINGLE
    elif result.candidates:
        result.status = MULTIPLE
    return result


def _ttm_dividend_yield(prices: pd.DataFrame) -> tuple[float | None, float | None]:
    """Sum of dividends paid in the last 365 days / latest close.

    Returns (yield, dividends_paid). A stock that paid nothing returns (0.0, 0.0);
    (None, None) means the data needed to compute it was missing.
    """
    if "Dividends" not in prices.columns or prices["Close"].dropna().empty:
        return None, None

    last_date = prices.index[-1]
    window = prices.loc[prices.index > last_date - pd.Timedelta(days=365), "Dividends"]
    paid = float(window.fillna(0).sum())
    latest_close = float(prices["Close"].dropna().iloc[-1])
    if latest_close <= 0:
        return None, None
    return paid / latest_close, paid


def fetch_ticker_data(
    symbol: str, exchange: str, input_ticker: str = "", company_name: str | None = None
) -> TickerData:
    """Fetch ~5 years of daily prices, last price and TTM dividend yield for one stock.

    `symbol` is an already-resolved Yahoo symbol (see `resolve`). Never raises for bad
    tickers or network problems; the problem is reported in `TickerData.error` so the
    caller can carry on with the remaining tickers.
    """
    result = TickerData(
        input_ticker=input_ticker or symbol,
        exchange=exchange,
        yahoo_symbol=symbol,
        company_name=company_name,
    )

    if not symbol:
        result.error = "Empty ticker."
        return result

    try:
        yf_ticker = yf.Ticker(symbol)
        # auto_adjust=False keeps both raw Close and Adj Close visible
        prices = yf_ticker.history(
            period=LOOKBACK_PERIOD, interval=INTERVAL, auto_adjust=False
        )
    except Exception as e:  # yfinance surfaces network/HTTP failures as assorted exceptions
        result.error = f"Fetch failed: {type(e).__name__}: {e}"
        return result

    if prices is None or prices.empty:
        result.error = (
            f"No data found for '{symbol}'. Check the ticker and the selected exchange."
        )
        return result

    result.prices = prices

    closes = prices["Close"].dropna()
    if not closes.empty:
        result.last_price = float(closes.iloc[-1])
        result.last_price_date = closes.index[-1]

    try:
        result.currency = yf_ticker.fast_info.get("currency")
    except Exception:
        result.warnings.append("Could not determine trading currency.")

    result.ttm_dividend_yield, result.ttm_dividends_paid = _ttm_dividend_yield(prices)
    if result.ttm_dividend_yield is None:
        result.warnings.append("Dividend data unavailable; TTM yield could not be computed.")

    history_years = (prices.index[-1] - prices.index[0]).days / 365.25
    if history_years < MIN_HISTORY_YEARS:
        result.warnings.append(
            f"Only {history_years:.1f} years of history available "
            f"(spec asks for {MIN_HISTORY_YEARS}–5 years)."
        )

    return result
