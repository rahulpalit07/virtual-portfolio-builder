"""Data fetching: ticker/name resolution, historical prices and TTM dividend yield.

Per PROJECT_SPEC.md Sections 2.1, 2.2 and 2.6. One market per session: every input is
resolved against the selected market only, and anything that doesn't look like it belongs
to that market (another exchange, another currency, another market's ticker suffix) is
flagged by `out_of_market_reasons`. No returns/risk calculations live here.
"""

import logging
import re
from dataclasses import dataclass, field

import pandas as pd
import yfinance as yf

# yfinance logs a 404 for every ticker probe that doesn't exist; we report those ourselves
logging.getLogger("yfinance").setLevel(logging.CRITICAL)

EXCHANGES = ["India (NSE)", "Australia (ASX)", "USA"]  # the markets a session can choose

# Each market's trading currency; a listing priced in anything else is flagged (Section 2.6)
MARKET_CURRENCY = {
    "India (NSE)": "INR",
    "Australia (ASX)": "AUD",
    "USA": "USD",
}

# Yahoo Finance ticker suffixes of exchanges. Typing one that isn't the selected market's
# (e.g. RELIANCE.BO or BHP.AX in a USA session) means a listing outside the market. US share
# classes like BRK.B use single letters that aren't in this set, so they're unaffected.
KNOWN_SUFFIXES = {
    "NS", "BO", "AX", "L", "TO", "V", "CN", "NE", "HK", "T", "SS", "SZ", "KS", "KQ", "TW",
    "TWO", "SI", "JK", "KL", "BK", "NZ", "DE", "F", "SG", "MU", "DU", "HM", "BE", "PA", "AS",
    "BR", "LS", "MI", "MC", "SW", "VI", "ST", "OL", "CO", "HE", "IR", "WA", "PR", "AT", "IS",
    "TA", "JO", "SA", "MX", "BA", "SN", "IL", "QA", "SR", "CA", "XC",
}

# Yahoo Finance suffix per market (Section 2.1)
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
    exchange_code: str = ""  # Yahoo exchange code, e.g. NSI, BSE, ASX, NYQ

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
    # Set when the input was another market's ticker (e.g. RELIANCE.BO in an India session):
    # the listing that was typed, and whether the same company's listing on the selected
    # market was found and offered instead (user decision: use the selected exchange's
    # price and currency).
    entered: Candidate | None = None
    switched: bool = False


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


def foreign_suffix(ticker: str, market: str) -> str | None:
    """The exchange suffix of `ticker` if it belongs to an exchange other than the selected
    market's (e.g. "BO" for RELIANCE.BO in an India session), else None."""
    m = re.match(r"^.+\.([A-Za-z]{1,3})$", ticker.strip())
    if not m:
        return None
    suffix = m.group(1).upper()
    if suffix in KNOWN_SUFFIXES and f".{suffix}" != EXCHANGE_SUFFIX[market]:
        return suffix
    return None


def to_yahoo_symbol(ticker: str, exchange: str) -> str:
    """Convert a user-entered ticker + market into the symbol Yahoo Finance expects.
    Another market's ticker (e.g. BHP.AX in a USA session) is kept as typed."""
    if exchange not in EXCHANGE_SUFFIX:
        raise ValueError(f"Unknown exchange: {exchange!r}")

    symbol = ticker.strip().upper()
    suffix = EXCHANGE_SUFFIX[exchange]

    if foreign_suffix(symbol, exchange):
        return symbol
    if suffix:
        # Don't double-append if the user already typed it (e.g. "RELIANCE.NS")
        if not symbol.endswith(suffix):
            symbol += suffix
    else:
        # Yahoo uses dashes for US share classes: BRK.B -> BRK-B
        symbol = symbol.replace(".", "-")

    return symbol


def _search(query: str, exchange: str | None) -> list[Candidate]:
    """Yahoo symbol search, filtered to ordinary shares on the chosen market's exchange
    (`exchange=None`: any exchange, used only to identify another market's ticker)."""
    quotes = yf.Search(
        query, max_results=SEARCH_MAX_RESULTS, news_count=0, enable_fuzzy_query=False
    ).quotes
    allowed = EXCHANGE_SEARCH_CODES[exchange] if exchange else None
    candidates = []
    for q in quotes:
        symbol = q.get("symbol") or ""
        name = q.get("longname") or q.get("shortname") or ""
        if q.get("quoteType") != "EQUITY" or (allowed is not None and q.get("exchange") not in allowed):
            continue
        if NON_COMMON_SUFFIX.search(symbol) or NON_COMMON_NAME.search(name):
            continue
        candidates.append(Candidate(
            symbol, name or "(name unavailable)", q.get("exchDisp") or q["exchange"], q.get("exchange", "")
        ))
    return candidates


def market_of_exchange(exchange_code: str) -> str | None:
    """The market (one of EXCHANGES) a Yahoo exchange code belongs to, or None."""
    return next((m for m, codes in EXCHANGE_SEARCH_CODES.items() if exchange_code in codes), None)


def listing_currency(symbol: str) -> str | None:
    """Trading currency of a listing (one quick Yahoo request), or None if unknown."""
    try:
        return yf.Ticker(symbol).fast_info.get("currency")
    except Exception:
        return None


def out_of_market_reasons(candidate: Candidate, market: str, currency: str | None) -> list[str]:
    """Why a listing doesn't look like it belongs to the selected market (empty if it does).

    User decision: a company counts as in-market when the listing used is on the selected
    exchange and priced in its currency (so e.g. Infosys's NYSE listing is fine in a USA
    session); the company's home country is not checked.
    """
    reasons = []
    if candidate.exchange_code and candidate.exchange_code not in EXCHANGE_SEARCH_CODES[market]:
        if candidate.exchange_code == "BSE":
            where = "BSE (not supported; India means NSE only)"
        elif candidate.exchange_display and candidate.exchange_display != candidate.exchange_code:
            where = f"{candidate.exchange_display} ({candidate.exchange_code})"
        else:
            where = candidate.exchange_code
        reasons.append(f"listed on {where}")
    if foreign_suffix(candidate.symbol, market) or (
        EXCHANGE_SUFFIX[market] and not candidate.symbol.endswith(EXCHANGE_SUFFIX[market])
    ):
        reasons.append(f"{candidate.symbol} is not a ticker for {market}")
    if currency and currency != MARKET_CURRENCY[market]:
        reasons.append(f"priced in {currency}, not {MARKET_CURRENCY[market]}")
    return reasons


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
    return Candidate(
        symbol,
        name or "(name unavailable, verify this ticker)",
        info.get("fullExchangeName") or info.get("exchange") or exchange,
        info.get("exchange", ""),
    ), None


def _resolve_other_market_ticker(result: Resolution, symbol: str, market: str) -> Resolution:
    """Input is another market's ticker (e.g. RELIANCE.BO in an India session). Identify it,
    then offer the same company's listing on the selected market if one exists (user
    decision: use the selected exchange's price and currency); otherwise offer the typed
    listing itself, which the app flags as outside the market."""
    listing = next((c for c in _search(symbol, None) if c.symbol == symbol), None)
    if listing is None:
        listing, result.note = _direct_ticker_candidate(symbol, symbol)
    if listing is None:
        result.note = result.note or f"{symbol} wasn't found on any exchange."
        return result
    result.entered = listing

    same_company = []
    if not listing.name.startswith("(name unavailable"):
        same_company = _search(listing.name, market)
    if same_company:
        result.candidates = same_company
        result.switched = True
        result.status = SINGLE if len(same_company) == 1 else MULTIPLE
    else:
        result.candidates = [listing]
        result.status = EXACT
    return result


def resolve(query: str, exchange: str) -> Resolution:
    """Resolve a ticker or company name to candidate stocks on the selected market.

    Never raises; lookup failures are reported in `Resolution.error`.
    """
    query = query.strip()
    result = Resolution(query=query, exchange=exchange)
    if not query:
        result.error = "Empty input."
        return result

    if LOOKS_LIKE_TICKER.match(query) and foreign_suffix(query, exchange):
        try:
            return _resolve_other_market_ticker(result, query.upper(), exchange)
        except Exception as e:  # network/HTTP problems
            result.error = f"Lookup failed: {type(e).__name__}: {e}"
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
