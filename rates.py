"""Risk-free rate for Max Sharpe: the selected market's 10-year government bond yield
(PROJECT_SPEC.md Section 3.4).

Pure calculations / data access, no Streamlit. Source: CNBC's quote service for all three
markets (user decision); if that fails, the value in `fallback_rates.json`, clearly marked
as a fallback. Uses only the standard library (no new packages in requirements.txt).
"""

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

CNBC_SYMBOLS = {
    "India (NSE)": "IN10Y",  # "IN10Y-IN" returns no data when requested on its own
    "Australia (ASX)": "AU10Y-AU",
    "USA": "US10Y",
}
CNBC_URL = (
    "https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol"
    "?symbols={symbol}&requestMethod=itv&noform=1&partnerId=2&fund=1&exthrs=1&output=json"
)
CNBC_PAGE = "https://www.cnbc.com/quotes/{symbol}"
FALLBACK_FILE = Path(__file__).with_name("fallback_rates.json")
FALLBACK_STALE_DAYS = 90
TIMEOUT_SECONDS = 10
PLAUSIBLE_RANGE = (0.0, 25.0)  # percent; anything outside is treated as a bad reading


@dataclass
class RiskFreeRate:
    market: str
    value: float  # fraction, e.g. 0.0721 = 7.21%
    name: str  # e.g. "India 10-year government bond yield"
    source: str
    as_of: str  # human-readable date/time of the value
    is_fallback: bool = False
    note: str | None = None  # why the fallback was used, staleness, etc.


BOND_NAMES = {
    "India (NSE)": "India 10-year government bond yield",
    "Australia (ASX)": "Australia 10-year government bond yield",
    "USA": "US 10-year Treasury yield",
}


def fetch_live(market: str) -> RiskFreeRate:
    """Fetch the 10-year yield from CNBC. Raises on any failure (network, format, value)."""
    symbol = CNBC_SYMBOLS[market]
    url = CNBC_URL.format(symbol=urllib.parse.quote(symbol))
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
        payload = json.load(resp)

    quote = payload["FormattedQuoteResult"]["FormattedQuote"][0]
    if quote.get("symbol") != symbol or quote.get("code") not in (0, "0"):
        raise ValueError(f"CNBC returned no quote for {symbol}")
    pct = float(str(quote["last"]).strip().rstrip("%"))
    if not PLAUSIBLE_RANGE[0] < pct < PLAUSIBLE_RANGE[1]:
        raise ValueError(f"implausible yield {pct}%")

    as_of = quote.get("last_time") or quote.get("last_timedate") or "unknown time"
    try:
        as_of = datetime.fromisoformat(as_of).strftime("%Y-%m-%d %H:%M %Z")
    except ValueError:
        pass
    return RiskFreeRate(
        market=market,
        value=pct / 100,
        name=BOND_NAMES[market],
        source=f"CNBC ({quote.get('name', symbol)}, {CNBC_PAGE.format(symbol=symbol)})",
        as_of=as_of,
    )


def load_fallback(market: str, reason: str, today: date | None = None) -> RiskFreeRate:
    """The fallback value from fallback_rates.json, marked as a fallback."""
    entry = json.loads(FALLBACK_FILE.read_text(encoding="utf-8"))[market]
    as_of = entry["as_of"]
    note = f"Live value unavailable ({reason}), so a stored fallback value is used."
    age = ((today or date.today()) - date.fromisoformat(as_of)).days
    if age > FALLBACK_STALE_DAYS:
        note += f" The fallback is {age} days old and may be out of date."
    return RiskFreeRate(
        market=market,
        value=float(entry["yield_percent"]) / 100,
        name=BOND_NAMES[market],
        source=f"Fallback file {FALLBACK_FILE.name} ({entry['source']})",
        as_of=as_of,
        is_fallback=True,
        note=note,
    )


def risk_free_rate(market: str) -> RiskFreeRate:
    """Live CNBC value if possible, otherwise the fallback. Never raises for a known market."""
    try:
        return fetch_live(market)
    except Exception as e:  # network errors, blocked requests, format changes, bad values
        return load_fallback(market, f"{type(e).__name__}: {e}")
