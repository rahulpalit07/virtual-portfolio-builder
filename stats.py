"""Returns, risk and covariance (PROJECT_SPEC.md Section 2.3).

Pure calculations, no Streamlit. Decisions (see CLAUDE.md):
- Daily simple returns on `Close` (price only, excl. dividends; split-adjusted by Yahoo).
- Dates aligned on the union of all exchanges' trading days; on a day an exchange was
  closed, its stocks carry their last close forward. Today's bar is used only once that
  exchange has closed for the day.
- Each stock uses all the history it has (up to the 5 years fetched); covariance and
  correlation use each pair's overlapping dates.
- Annualized with the observed number of aligned trading days per year.
"""

from dataclasses import dataclass, field
from datetime import time

import numpy as np
import pandas as pd

from data import TickerData

# Local time after which today's bar counts as a completed close (close + a short buffer)
EXCHANGE_CLOSE_LOCAL = {
    "India (NSE)": time(15, 45),  # closes 15:30 IST
    "Australia (ASX)": time(16, 20),  # closes 16:00 + closing auction
    "USA": time(16, 15),  # closes 16:00 ET
}

# "Look at this" thresholds: flagged, never excluded
MIN_HISTORY_YEARS = 3
MU_HIGH, MU_LOW = 1.0, -0.5  # annualized return above +100% / below -50%
SIGMA_HIGH = 0.8  # annualized risk above 80%
ZERO_RETURN_SHARE = 0.2  # >20% of the stock's own trading days with exactly 0% return
HIGH_CORRELATION = 0.95  # likely near-duplicates (e.g. two share classes)

TOLERANCE = 1e-9


@dataclass
class StockStats:
    symbol: str
    start: pd.Timestamp
    end: pd.Timestamp
    years: float
    observations: int  # daily returns used, on the aligned calendar
    mu: float  # annualized mean of daily simple returns
    sigma: float  # annualized standard deviation
    cagr: float  # compound annual growth of the price, for comparison with mu
    zero_return_share: float
    flags: list[str] = field(default_factory=list)


@dataclass
class Check:
    name: str
    passed: bool
    detail: str


@dataclass
class StatsResult:
    returns: pd.DataFrame  # aligned daily simple returns; NaN before a stock's history starts
    periods_per_year: float
    stocks: dict[str, StockStats]
    cov: pd.DataFrame  # annualized
    corr: pd.DataFrame
    checks: list[Check]
    high_corr_pairs: list[tuple[str, str, float]]
    dropped_in_progress: list[str]  # symbols whose still-trading bar for today was dropped


def completed_closes(td: TickerData, now: pd.Timestamp | None = None) -> tuple[pd.Series, bool]:
    """Close prices indexed by local trading date, excluding today's bar if the
    exchange hasn't closed yet. Returns (closes, dropped_today)."""
    closes = td.prices["Close"].dropna()
    tz = closes.index.tz
    now_local = (now or pd.Timestamp.now(tz="UTC")).tz_convert(tz) if tz else pd.Timestamp.now()

    dropped = False
    last = closes.index[-1]
    close_time = EXCHANGE_CLOSE_LOCAL.get(td.exchange)
    if close_time and last.date() == now_local.date() and now_local.time() < close_time:
        closes = closes.iloc[:-1]
        dropped = True

    # Align on the exchange's local calendar date
    closes.index = closes.index.tz_localize(None).normalize() if tz else closes.index.normalize()
    return closes, dropped


def compute_stats(stocks: list[TickerData], now: pd.Timestamp | None = None) -> StatsResult:
    closes: dict[str, pd.Series] = {}
    dropped_in_progress = []
    for td in stocks:
        s, dropped = completed_closes(td, now)
        closes[td.yahoo_symbol] = s
        if dropped:
            dropped_in_progress.append(td.yahoo_symbol)

    # Union of all trading dates; carry each stock's last close over days its exchange
    # was shut. ffill never fills before a stock's first price, so shorter histories
    # stay NaN until they start.
    prices = pd.DataFrame(closes).sort_index().ffill()
    returns = prices.pct_change()
    returns = returns.iloc[1:]

    span_years = (prices.index[-1] - prices.index[0]).days / 365.25
    periods_per_year = len(returns) / span_years if span_years > 0 else 252.0

    stock_stats: dict[str, StockStats] = {}
    for symbol, s in closes.items():
        r = returns[symbol].dropna()
        years = (s.index[-1] - s.index[0]).days / 365.25
        own = s.pct_change().dropna()  # on the stock's own trading days
        st = StockStats(
            symbol=symbol,
            start=s.index[0],
            end=s.index[-1],
            years=years,
            observations=len(r),
            mu=r.mean() * periods_per_year,
            sigma=r.std() * np.sqrt(periods_per_year),
            cagr=(s.iloc[-1] / s.iloc[0]) ** (1 / years) - 1 if years > 0 else np.nan,
            zero_return_share=(own == 0).mean() if len(own) else np.nan,
        )
        if years < MIN_HISTORY_YEARS:
            st.flags.append(
                f"Only {years:.1f} years of history (spec asks for 3–5). Its statistics, and "
                "its covariance with other stocks, use this shorter period only."
            )
        if st.mu > MU_HIGH:
            st.flags.append(f"Very high annualized return ({st.mu:.0%}).")
        if st.mu < MU_LOW:
            st.flags.append(f"Very low annualized return ({st.mu:.0%}).")
        if st.sigma > SIGMA_HIGH:
            st.flags.append(f"Very high annualized risk ({st.sigma:.0%}).")
        if st.zero_return_share > ZERO_RETURN_SHARE:
            st.flags.append(
                f"{st.zero_return_share:.0%} of trading days had exactly 0% return: "
                "possibly thinly traded or stale prices."
            )
        stock_stats[symbol] = st

    # Pairwise over overlapping dates (pandas default)
    cov = returns.cov() * periods_per_year
    corr = returns.corr()

    sigmas = pd.Series({k: v.sigma for k, v in stock_stats.items()})[cov.index]
    checks = _sanity_checks(cov, corr, sigmas)

    symbols = list(corr.index)
    high_corr_pairs = [
        (a, b, corr.loc[a, b])
        for i, a in enumerate(symbols)
        for b in symbols[i + 1 :]
        if corr.loc[a, b] > HIGH_CORRELATION
    ]

    return StatsResult(
        returns=returns,
        periods_per_year=periods_per_year,
        stocks=stock_stats,
        cov=cov,
        corr=corr,
        checks=checks,
        high_corr_pairs=high_corr_pairs,
        dropped_in_progress=dropped_in_progress,
    )


def _sanity_checks(cov: pd.DataFrame, corr: pd.DataFrame, sigmas: pd.Series) -> list[Check]:
    checks = []
    c = cov.to_numpy()

    asym = np.abs(c - c.T).max() if c.size else 0.0
    checks.append(Check(
        "Covariance matrix is symmetric",
        asym <= TOLERANCE,
        f"Largest asymmetry: {asym:.2e}",
    ))

    diag_gap = np.abs(np.diag(c) - sigmas.to_numpy() ** 2).max() if c.size else 0.0
    checks.append(Check(
        "Covariance diagonal equals each stock's variance (σ²)",
        diag_gap <= TOLERANCE,
        f"Largest difference: {diag_gap:.2e}",
    ))

    k = corr.to_numpy()
    lo, hi = np.nanmin(k), np.nanmax(k)
    in_range = (lo >= -1 - TOLERANCE) and (hi <= 1 + TOLERANCE)
    checks.append(Check(
        "All correlations are between −1 and 1",
        bool(in_range),
        f"Range: {lo:.3f} to {hi:.3f}",
    ))

    missing = int(np.isnan(c).sum())
    checks.append(Check(
        "Every pair of stocks has overlapping history",
        missing == 0,
        "All pairs overlap" if missing == 0 else f"{missing} matrix entries could not be computed",
    ))

    if missing == 0 and c.size:
        min_eig = float(np.linalg.eigvalsh(c).min())
        # Relative tolerance: tiny negative eigenvalues are floating-point noise
        ok = min_eig >= -1e-10 * max(np.abs(c).max(), 1.0)
        checks.append(Check(
            "Covariance matrix is positive semi-definite (no combination has negative risk)",
            ok,
            f"Smallest eigenvalue: {min_eig:.2e}"
            + ("" if ok else ". Can happen when histories differ in length; step 3 must repair it."),
        ))

    return checks
