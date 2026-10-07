"""Virtual Portfolio Builder: Streamlit UI.

Current scope (V1, steps 1-4): input tickers/names -> resolve & confirm -> fetch raw data ->
returns, risk, covariance and correlation -> Min Risk, Max Return, Max Dividend, Max Sharpe.
"""

from dataclasses import replace

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from data import (
    EXACT,
    EXCHANGES,
    NO_MATCH,
    SINGLE,
    Resolution,
    TickerData,
    fetch_ticker_data,
    resolve,
)
from frontier import efficient_frontier, frontier_check
from optimizer import (
    RISK_FREE_RATE,
    Constraints,
    dividend_data_flags,
    equal_weights,
    max_dividend_portfolio,
    max_return_portfolio,
    max_sharpe_portfolio,
    min_risk_portfolio,
    portfolio_stats,
    prepare_covariance,
)
from stats import compute_stats

MIN_TICKERS = 10  # Section 2.1

# How each included stock was matched; carried through to the output
MATCH_EXACT = "✅ Exact ticker"
MATCH_SINGLE = "✅ Single match"
MATCH_AUTO = "⚠️ Auto-picked"
MATCH_PICKED = "✅ Picked by you"

SKIP_NO_MATCH = "No match"
SKIP_BY_USER = "Skipped by you"

st.set_page_config(page_title="Virtual Portfolio Builder", layout="wide")


# In-memory caches only, so Streamlit reruns don't re-query Yahoo
@st.cache_data(ttl=3600, show_spinner=False)
def cached_resolve(query: str, exchange: str) -> Resolution:
    return resolve(query, exchange)


# Portfolio caches: keyed on exactly what each calculation depends on, so switching the
# portfolio dropdown never re-optimizes, and changing an input recomputes only what uses it.
@st.cache_data(show_spinner=False)
def cached_min_risk(cov, tickers, constraints):
    return min_risk_portfolio(cov, list(tickers), constraints)


@st.cache_data(show_spinner=False)
def cached_max_return(mu, constraints):
    return max_return_portfolio(mu, constraints)


@st.cache_data(show_spinner=False)
def cached_max_dividend(yields, constraints):
    return max_dividend_portfolio(yields, constraints)


@st.cache_data(show_spinner=False)
def cached_max_sharpe(cov, mu, risk_free_rate, constraints, compare):
    return max_sharpe_portfolio(cov, mu, risk_free_rate, constraints, compare)


@st.cache_data(show_spinner=False)
def cached_frontier(cov, mu, constraints, anchors):
    return efficient_frontier(cov, mu, constraints, anchors)


@st.cache_data(ttl=3600, show_spinner=False)
def cached_fetch(symbol: str, exchange: str, input_ticker: str, company_name: str) -> TickerData:
    return fetch_ticker_data(symbol, exchange, input_ticker, company_name)


def fmt_price(td: TickerData) -> str:
    if td.last_price is None:
        return "N/A"
    return f"{td.last_price:,.2f} {td.currency or ''}".strip()


def fmt_yield(td: TickerData) -> str:
    return "N/A" if td.ttm_dividend_yield is None else f"{td.ttm_dividend_yield:.2%}"


def render_ticker(td: TickerData, auto_picked: bool = False) -> None:
    label = f"{td.yahoo_symbol} · {td.company_name or '?'}   (input: “{td.input_ticker}”, {td.exchange})"
    if auto_picked:
        label = f"{MATCH_AUTO} · {label}"

    prices = td.prices
    with st.expander(label, expanded=False):
        for w in td.warnings:
            st.warning(w)

        cols = st.columns(7)
        cols[0].metric(
            "Last price",
            fmt_price(td),
            help=f"Latest close as of {td.last_price_date:%Y-%m-%d}. "
            "If the market is open this is the current (≈15-min delayed) price.",
        )
        cols[1].metric("Currency", td.currency or "?")
        cols[2].metric("First date", f"{prices.index[0]:%Y-%m-%d}")
        cols[3].metric("Last date", f"{prices.index[-1]:%Y-%m-%d}")
        cols[4].metric("Rows", f"{len(prices):,}")
        cols[5].metric("Missing values", int(prices.isna().sum().sum()))
        cols[6].metric(
            "TTM dividend yield",
            fmt_yield(td),
            help=(
                "Dividends paid in the last 365 days ÷ latest close. "
                f"Dividends paid: {td.ttm_dividends_paid:.4f} {td.currency or ''}"
                if td.ttm_dividends_paid is not None
                else "Dividend data unavailable."
            ),
        )

        st.dataframe(prices, width="stretch", height=350)


st.title("Virtual Portfolio Builder")
st.caption("V1 · Data, returns, risk, covariance and four optimized portfolios.")

# ---- Step 1: input --------------------------------------------------------------
st.subheader("1. Enter stocks")
default_rows = pd.DataFrame(
    {
        "Ticker or company name": ["AAPL", "Reliance", "BHP"],
        "Exchange": ["USA", "India (NSE)", "Australia (ASX)"],
    }
)

with st.form("tickers"):
    st.write(
        f"Enter at least {MIN_TICKERS} stocks, by ticker (e.g. `RELIANCE`) or company "
        "name (e.g. `Reliance Industries`). Add rows with the **+** at the bottom of the "
        "table; select rows to delete them."
    )
    edited = st.data_editor(
        default_rows,
        num_rows="dynamic",
        width="stretch",
        hide_index=True,
        column_config={
            "Ticker or company name": st.column_config.TextColumn(required=True),
            "Exchange": st.column_config.SelectboxColumn(
                options=EXCHANGES, required=True, default="USA"
            ),
        },
    )
    resolve_clicked = st.form_submit_button("Resolve", type="primary")

if resolve_clicked:
    rows = edited.dropna(subset=["Ticker or company name", "Exchange"])
    entries = list(
        dict.fromkeys(  # drop exact duplicates, keep order
            (str(q).strip(), ex)
            for q, ex in zip(rows["Ticker or company name"], rows["Exchange"])
            if str(q).strip()
        )
    )
    if not entries:
        st.error("Please enter at least one ticker or company name.")
        st.stop()

    with st.spinner("Looking up stocks…"):
        st.session_state.resolutions = [cached_resolve(q, ex) for q, ex in entries]
    st.session_state.pop("fetched", None)

resolutions: list[Resolution] = st.session_state.get("resolutions", [])
if not resolutions:
    st.stop()


# ---- Step 2: confirm matches ----------------------------------------------------
st.subheader("2. Confirm matches")
st.caption(
    "Check that each input matched the company you meant. Where there are several "
    "matches, pick the right one from the dropdown. Untick **Include** to skip a stock. "
    "To fix a row instead, edit it in the table above and click **Resolve** again."
)

widths = [0.7, 2, 1.3, 4, 2.4]
header = st.columns(widths)
for col, title in zip(header, ["Include", "Your input", "Exchange", "Matched stock", "Status"]):
    col.markdown(f"**{title}**")

# included: (symbol, exchange, input, company name, match type)
included: list[tuple[str, str, str, str, str]] = []
skipped: list[tuple[str, str, str]] = []  # (input, exchange, reason)
for i, r in enumerate(resolutions):
    c0, c1, c2, c3, c4 = st.columns(widths, vertical_alignment="center")
    c1.write(f"“{r.query}”")
    c2.write(r.exchange)
    key = f"{i}_{r.query}_{r.exchange}"

    if r.status == NO_MATCH:
        c0.checkbox("Include", value=False, disabled=True, key=f"inc_{key}",
                    label_visibility="collapsed")
        c3.write(f"_{r.error or r.note or 'No stock found on this exchange.'}_")
        c4.write("❌ No match: will be skipped")
        skipped.append((r.query, r.exchange, SKIP_NO_MATCH))
        continue

    include = c0.checkbox("Include", value=True, key=f"inc_{key}",
                          label_visibility="collapsed")
    pick = c3.selectbox(
        f"Match for {r.query}",
        options=range(len(r.candidates)),
        format_func=lambda j, r=r: r.candidates[j].label,
        key=f"pick_{key}",
        label_visibility="collapsed",
    )

    if pick != 0:
        match = MATCH_PICKED
    elif r.status == EXACT:
        match = MATCH_EXACT
    elif r.status == SINGLE:
        match = MATCH_SINGLE
    else:
        match = MATCH_AUTO

    if not include:
        c4.write("⏭️ Skipped by you")
        skipped.append((r.query, r.exchange, SKIP_BY_USER))
        continue

    chosen = r.candidates[pick]
    # Several inputs resolving to the same stock: fetch it once, skip the later ones
    first = next((e for e in included if e[0] == chosen.symbol), None)
    if first is not None:
        reason = f"Duplicate of “{first[2]}” ({chosen.symbol})"
        c4.write(f"⏭️ {reason}: will be skipped")
        skipped.append((r.query, r.exchange, reason))
        continue

    if match == MATCH_AUTO:
        c4.write(f"⚠️ Auto-picked top of {len(r.candidates)} matches (not changed)")
    else:
        c4.write(match)
    included.append((chosen.symbol, r.exchange, r.query, chosen.name, match))

if included and len(included) < MIN_TICKERS:
    st.warning(
        f"{len(included)} stock(s) included. Portfolio construction will need at least "
        f"{MIN_TICKERS}; continuing anyway for this data check."
    )

if skipped:
    st.markdown(
        f"**Will skip {len(skipped)}:** "
        + "; ".join(f"“{q}” ({ex}): {reason}" for q, ex, reason in skipped)
    )

if not included:
    st.info("No stocks are included. Tick **Include** on at least one matched row to fetch.")

label = f"Fetch {len(included)} stock{'s' if len(included) != 1 else ''}"
if skipped:
    label += f" (skipping {len(skipped)})"
fetch_clicked = st.button(label, type="primary", disabled=not included)

# ---- Step 3: fetch & display ----------------------------------------------------
if fetch_clicked:
    results: list[TickerData] = []
    progress = st.progress(0.0, text="Fetching…")
    for i, (symbol, exchange, query, name, _match) in enumerate(included, start=1):
        progress.progress(i / len(included), text=f"Fetching {symbol} ({name})…")
        results.append(cached_fetch(symbol, exchange, query, name))
    progress.empty()
    st.session_state.fetched = (included, skipped, results)

fetched = st.session_state.get("fetched")
if not fetched:
    st.stop()
if fetched[0] != included or fetched[1] != skipped:
    st.info("Your selections changed since the last fetch. Click the fetch button to refresh.")
    st.stop()

_, skipped, results = fetched
match_of = {entry[0]: entry[4] for entry in included}
ok = [r for r in results if r.ok]
failed = [r for r in results if not r.ok]

st.subheader("3. Data")
st.caption(
    f"Based on **{len(ok)}** stock(s). {len(skipped)} input(s) skipped, "
    f"{len(failed)} failed to fetch."
)

st.markdown(f"**✅ Included ({len(ok)})**")
if ok:
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Input": r.input_ticker,
                    "Ticker": r.yahoo_symbol,
                    "Company": r.company_name,
                    "Exchange": r.exchange,
                    "Match": match_of[r.yahoo_symbol],
                    "Last price": fmt_price(r),
                    "As of": f"{r.last_price_date:%Y-%m-%d}",
                    "Rows": len(r.prices),
                    "First date": f"{r.prices.index[0]:%Y-%m-%d}",
                    "Last date": f"{r.prices.index[-1]:%Y-%m-%d}",
                    "TTM dividend yield": fmt_yield(r),
                    "Warnings": len(r.warnings),
                }
                for r in ok
            ]
        ),
        width="stretch",
        hide_index=True,
    )
    if any(match_of[r.yahoo_symbol] == MATCH_AUTO for r in ok):
        st.caption(
            f"{MATCH_AUTO}: the input matched several stocks and the top match was used "
            "without being changed. Check these are the companies you meant."
        )

if skipped:
    st.markdown(f"**⏭️ Skipped ({len(skipped)})**")
    st.dataframe(
        pd.DataFrame(skipped, columns=["Input", "Exchange", "Reason"]),
        width="stretch",
        hide_index=True,
    )

if failed:
    st.markdown(f"**❌ Failed to fetch ({len(failed)})**")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Input": r.input_ticker,
                    "Ticker": r.yahoo_symbol,
                    "Company": r.company_name,
                    "Exchange": r.exchange,
                    "Error": r.error,
                }
                for r in failed
            ]
        ),
        width="stretch",
        hide_index=True,
    )

if ok:
    st.markdown("**Raw data per stock**")
    for r in ok:
        render_ticker(r, auto_picked=match_of[r.yahoo_symbol] == MATCH_AUTO)

# ---- Step 4: returns, risk, covariance --------------------------------------------
if not ok:
    st.stop()

st.subheader("4. Returns & risk")
res = compute_stats(ok)
by_symbol = {r.yahoo_symbol: r for r in ok}

st.caption(
    "Daily simple returns on **Close** (price only, excluding dividends). Dates are aligned "
    "across exchanges; on a day an exchange was closed, its stocks carry their last close. "
    "Each stock uses all the history it has (up to 5 years). Annualized using "
    f"**{res.periods_per_year:.0f}** aligned trading days per year."
)

currencies = sorted({r.currency or "?" for r in ok})
if len(currencies) > 1:
    st.warning(
        f"⚠️ **Mixed currencies ({', '.join(currencies)}).** Each stock's return and risk are "
        "in its own currency, with no conversion. Comparisons across exchanges are biased: "
        "returns in weaker or higher-inflation currencies look higher, and currency risk is "
        "not included. Known limitation (see CLAUDE.md)."
    )
if len({r.exchange for r in ok}) > 1:
    st.caption(
        "Note: with daily returns, correlations between stocks on *different* exchanges are "
        "understated, because the exchanges close at different times of day."
    )
if res.dropped_in_progress:
    st.caption(
        f"Market still open for {', '.join(res.dropped_in_progress)}: today's price isn't "
        "final, so the previous close is used."
    )

summary_rows = []
for symbol, s in res.stocks.items():
    td = by_symbol[symbol]
    summary_rows.append(
        {
            "Ticker": symbol,
            "Company": td.company_name,
            "Exchange": td.exchange,
            "Currency": td.currency,
            "Match": match_of[symbol],
            "Ann. return (μ)": s.mu * 100,
            "Ann. risk (σ)": s.sigma * 100,
            "Price CAGR": s.cagr * 100,
            "TTM dividend yield": (
                td.ttm_dividend_yield * 100 if td.ttm_dividend_yield is not None else None
            ),
            "History (yrs)": s.years,
            "From": f"{s.start:%Y-%m-%d}",
            "To": f"{s.end:%Y-%m-%d}",
            "Flags": f"⚠️ {len(s.flags)}" if s.flags else "",
        }
    )
pct = st.column_config.NumberColumn(format="%.1f%%")
st.dataframe(
    pd.DataFrame(summary_rows),
    width="stretch",
    hide_index=True,
    column_config={
        "Ann. return (μ)": pct,
        "Ann. risk (σ)": pct,
        "Price CAGR": st.column_config.NumberColumn(
            format="%.1f%%",
            help="Compound annual growth of the price, for comparison with μ. "
            "μ (average daily return × days/yr) is normally a little higher.",
        ),
        "TTM dividend yield": st.column_config.NumberColumn(format="%.2f%%"),
        "History (yrs)": st.column_config.NumberColumn(format="%.1f"),
    },
)

st.markdown("**Sanity checks**")
for c in res.checks:
    st.markdown(f"{'✅' if c.passed else '❌'} {c.name} · _{c.detail}_")
failed_checks = [c for c in res.checks if not c.passed]
if failed_checks:
    st.error(f"{len(failed_checks)} sanity check(s) failed. Look at these before relying on the numbers.")

flagged = [s for s in res.stocks.values() if s.flags]
if flagged or res.high_corr_pairs:
    st.markdown("**Flagged for you to look at** (still included)")
    for s in flagged:
        st.warning(f"**{s.symbol}** ({by_symbol[s.symbol].company_name}): " + " ".join(s.flags))
    for a, b, x in res.high_corr_pairs:
        st.warning(
            f"**{a}** and **{b}** have correlation {x:.3f}: they move almost identically "
            "(e.g. two share classes of one company)."
        )
else:
    st.success("No stocks flagged: all returns, risks and histories are within normal ranges.")

st.markdown("**Covariance matrix (annualized)**")
st.dataframe(res.cov.style.format("{:.4f}"), width="stretch")

st.markdown("**Correlation matrix**")
n = len(res.corr)
fig = px.imshow(
    res.corr,
    text_auto=".2f",
    zmin=-1,
    zmax=1,
    color_continuous_scale="RdBu",
    aspect="auto",
)
fig.update_layout(height=max(300, 45 * n + 120), margin=dict(l=0, r=0, t=10, b=0))
st.plotly_chart(fig, width="stretch")
with st.expander("Correlation matrix as a table"):
    st.dataframe(res.corr.style.format("{:.3f}"), width="stretch")

# ---- Step 5: Portfolios (Min Risk, Max Return, Max Dividend, Max Sharpe) ---------------
st.subheader("5. Portfolios")
defaults = Constraints()
st.caption(
    "Four portfolios built from the stocks above, each a separate 100% allocation. Rules for "
    f"all of them: weights sum to 100%, no short-selling, each stock either 0% or between "
    f"{defaults.min_weight:.1%} and {defaults.max_weight:.0%}."
)

tickers = list(res.cov.index)
floor_count = defaults.stocks_needed_for_cap
ctrl_left, ctrl_right = st.columns(2)
min_stocks = ctrl_left.number_input(
    "Minimum number of stocks held",
    min_value=floor_count,
    max_value=max(floor_count, min(len(tickers), defaults.max_stocks_for_floor)),
    value=max(floor_count, min(defaults.min_stocks, len(tickers))),
    step=1,
    help=f"With a {defaults.max_weight:.0%} cap, at least {floor_count} stocks are always "
    "needed to reach 100%, so the minimum can't go lower than that.",
)
rf_pct = ctrl_right.number_input(
    "Risk-free rate for Max Sharpe (% per year)",
    min_value=0.0,
    max_value=50.0,
    value=RISK_FREE_RATE * 100,
    step=0.25,
    format="%.2f",
    help="Used for every Sharpe ratio shown. Default 4%: a placeholder roughly between "
    "US, Australian and Indian short-term rates; set it to a current rate.",
)
risk_free_rate = rf_pct / 100
constraints = replace(defaults, min_stocks=int(min_stocks))

# Shared by every portfolio: repaired once, used for both optimizing and the displayed figures
prepared = prepare_covariance(res.cov)
if prepared.note:
    st.info(prepared.note)
cov = prepared.cov

mu = pd.Series({s: v.mu for s, v in res.stocks.items()})[tickers]
yields = pd.Series({s: by_symbol[s].ttm_dividend_yield for s in tickers}, dtype=float)

with st.spinner("Building portfolios…"):
    mr = cached_min_risk(cov, tuple(tickers), constraints)
    mx = cached_max_return(mu, constraints)
    md = cached_max_dividend(yields, constraints)
    compare = {name: r.weights for name, r in (("Min Risk", mr), ("Max Return", mx)) if r.ok}
    ms = cached_max_sharpe(cov, mu, risk_free_rate, constraints, compare)
    anchors = {name: r.weights for name, r in (("Min Risk", mr), ("Max Sharpe", ms), ("Max Return", mx)) if r.ok}
    frontier = (
        cached_frontier(cov, mu, constraints, anchors)
        if "Min Risk" in anchors and "Max Return" in anchors
        else None
    )

portfolios = {"Min Risk": mr, "Max Return": mx, "Max Dividend": md, "Max Sharpe": ms}


def stats_of(weights: pd.Series) -> dict[str, float]:
    return portfolio_stats(weights, mu, cov, yields, risk_free_rate)


# Comparison of all four (plus equal weight as a reference)
st.markdown("**Comparison**")
rows = []
for name, r in portfolios.items():
    if r.weights is None:
        rows.append({"Portfolio": name, "Stocks held": None, "Note": "Not available (see below)"})
        continue
    s = stats_of(r.weights)
    rows.append({
        "Portfolio": name,
        "Expected return": s["expected_return"] * 100,
        "Risk (σ)": s["risk"] * 100,
        "Dividend yield": s["dividend_yield"] * 100,
        "Sharpe ratio": s["sharpe"],
        "Stocks held": len(r.held),
        "Note": "⚠️ failed a check" if r.error else "",
    })
s = stats_of(equal_weights(tickers))
rows.append({
    "Portfolio": "Equal weight (reference)",
    "Expected return": s["expected_return"] * 100,
    "Risk (σ)": s["risk"] * 100,
    "Dividend yield": s["dividend_yield"] * 100,
    "Sharpe ratio": s["sharpe"],
    "Stocks held": len(tickers),
    "Note": "",
})
pct2 = st.column_config.NumberColumn(format="%.2f%%")
st.dataframe(
    pd.DataFrame(rows),
    width="stretch",
    hide_index=True,
    column_config={
        "Expected return": pct2,
        "Risk (σ)": pct2,
        "Dividend yield": pct2,
        "Sharpe ratio": st.column_config.NumberColumn(format="%.3f"),
    },
)
st.caption(
    f"Sharpe ratio = (expected return − {risk_free_rate:.2%}) ÷ risk. "
    + (f"Returns are in {', '.join(currencies)} without conversion. " if len(currencies) > 1 else "")
    + "Expected returns are price-only (dividends excluded)."
)

choice = st.selectbox("Show portfolio", list(portfolios), index=0)
result = portfolios[choice]


def render_holdings(r) -> tuple[pd.Series, list[str]]:
    held = r.held
    st.markdown(f"**{choice} portfolio ({len(held)} of {len(tickers)} stocks held)**")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Ticker": s,
                    "Weight": w * 100,
                    "Company": by_symbol[s].company_name,
                    "Exchange": by_symbol[s].exchange,
                    "Match": match_of[s],
                }
                for s, w in held.items()
            ]
        ),
        width="stretch",
        hide_index=True,
        column_config={"Weight": st.column_config.NumberColumn(format="%.2f%%")},
    )
    excluded = [s for s in tickers if s not in held.index]
    if excluded:
        st.caption("Not held (0%): " + ", ".join(excluded))
    return held, excluded


def metric_slots(count: int, per_row: int) -> list:
    """`count` metric slots laid out `per_row` to a row (2 in the narrow side-panel views)."""
    slots = []
    while len(slots) < count:
        slots.extend(st.columns(per_row))
    return slots[:count]


def render_main_stats(pstats: dict[str, float], per_row: int = 4) -> None:
    m1, m2, m3, m4 = metric_slots(4, per_row)
    m1.metric("Expected return", f"{pstats['expected_return']:.2%}",
              help="Weighted sum of each stock's annualized return (μ).")
    m2.metric("Risk (σ)", f"{pstats['risk']:.2%}", help="√(wᵀΣw), annualized.")
    m3.metric("Dividend yield", f"{pstats['dividend_yield']:.2%}",
              help="Weighted TTM dividend yield.")
    m4.metric("Sharpe ratio", f"{pstats['sharpe']:.3f}",
              help=f"(Expected return − risk-free rate {risk_free_rate:.2%}) ÷ risk.")


def render_notes(held: pd.Series) -> None:
    if any(np.isnan(v) for v in yields[held.index]):
        st.caption("Stocks with no dividend data are counted as 0% in the portfolio yield.")
    if any(match_of[s] == MATCH_AUTO for s in held.index):
        st.caption(f"{MATCH_AUTO}: check these holdings are the companies you meant.")
    if len(currencies) > 1:
        st.caption(
            "⚠️ Mixed currencies: the expected return combines returns in "
            f"{', '.join(currencies)} without conversion."
        )


def render_checks(checks) -> None:
    st.markdown("**Verification checks**")
    for c in checks:
        icon = "✅" if c.passed else "❌"
        if not c.applicable:
            icon = "➖"
        st.markdown(f"{icon} {c.name} · _{c.detail}_")
    failed = [c for c in checks if c.applicable and not c.passed]
    if failed:
        st.error(f"{len(failed)} check(s) failed. Don't rely on this portfolio.")


def render_dividend_flags() -> None:
    flags = dividend_data_flags(yields)
    if flags.missing:
        st.warning(
            "No dividend data, counted as 0% and so left out of this portfolio: "
            + ", ".join(flags.missing)
        )
    if flags.out_of_range:
        st.error(
            "Yield outside 0–100% (likely a unit or data error), left out of this portfolio: "
            + ", ".join(f"{s} ({y:.0%})" for s, y in flags.out_of_range)
        )
    if flags.implausible:
        st.warning(
            "Implausibly high yield (above 15%): possibly a one-off special dividend, a price "
            "crash or a currency mismatch. Still included; untick it in Confirm matches to "
            "exclude it: " + ", ".join(f"{s} ({y:.1%})" for s, y in flags.implausible)
        )
    if flags.high:
        st.info(
            "High yield (8–15%), worth checking: "
            + ", ".join(f"{s} ({y:.1%})" for s, y in flags.high)
        )
    if flags.non_payers:
        st.caption(
            "Paid no dividend in the last 12 months (not eligible for this portfolio): "
            + ", ".join(flags.non_payers)
        )


def frontier_chart(fr, ms_result) -> go.Figure:
    vols = np.sqrt(np.clip(np.diag(cov.to_numpy()), 0, None))
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=fr.curve.risk * 100, y=fr.curve.expected_return * 100, mode="lines",
        name="Efficient frontier", line=dict(width=3),
        hovertemplate="Risk %{x:.2f}%<br>Return %{y:.2f}%<extra>Frontier</extra>",
    ))
    fig.add_trace(go.Scatter(
        x=vols * 100, y=mu.to_numpy() * 100, mode="markers+text", text=tickers,
        textposition="top center", name="Individual stocks", marker=dict(size=8, color="gray"),
        hovertemplate="%{text}<br>Risk %{x:.2f}%<br>Return %{y:.2f}%<extra></extra>",
    ))
    for label, symbol, size in (("Min Risk", "diamond", 14), ("Max Return", "square", 12), ("Max Sharpe", "star", 20)):
        row = fr.curve[fr.curve.label == label]
        if row.empty:
            continue
        fig.add_trace(go.Scatter(
            x=row.risk * 100, y=row.expected_return * 100, mode="markers", name=label,
            marker=dict(symbol=symbol, size=size, line=dict(width=1, color="black")),
            hovertemplate=f"{label}<br>Risk %{{x:.2f}}%<br>Return %{{y:.2f}}%<extra></extra>",
        ))
    fig.update_layout(
        xaxis_title="Annualized risk (σ, %)",
        yaxis_title="Annualized expected return (μ, %)",
        height=520,
        margin=dict(l=0, r=0, t=70, b=0),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
    )
    return fig


if result.weights is None:
    st.error(f"Couldn't build the {choice} portfolio. {result.error}")
    if choice == "Max Dividend":
        render_dividend_flags()
    st.stop()

for note in result.notes:
    st.info(note)
if result.error:
    st.error(f"{result.error} The portfolio below should not be relied on.")

pstats = stats_of(result.weights)

if choice == "Min Risk":
    left, right = st.columns([1, 1.2])
    with left:
        held, excluded = render_holdings(result)
        render_main_stats(pstats, per_row=2)
        m5, m6, m7 = metric_slots(3, 2)
        m5.metric("Equal-weight risk", f"{result.equal_weight_risk:.2%}",
                  help=f"An equal share in all {len(tickers)} stocks, for comparison.")
        m6.metric("Risk reduction", f"{result.equal_weight_risk - pstats['risk']:.2%}",
                  help="Equal-weight risk minus optimized risk.")
        m7.metric("Theoretical floor", f"{result.lower_bound_risk:.2%}",
                  help=f"Lowest possible risk if the {constraints.min_weight:.1%} minimum and the "
                  "minimum-stock rules didn't exist. The true best portfolio under all the rules "
                  "lies between this and the optimized risk; a small gap means the result is "
                  "essentially optimal.")
        render_notes(held)
    with right:
        st.markdown("**Correlation matrix** (held stocks first, by weight)")
        order = list(held.index) + excluded
        corr_sorted = res.corr.loc[order, order]
        fig = px.imshow(
            corr_sorted,
            text_auto=".2f",
            zmin=-1,
            zmax=1,
            color_continuous_scale="RdBu",
            aspect="auto",
        )
        fig.update_layout(height=max(300, 40 * len(order) + 120), margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig, width="stretch", key="corr_min_risk")
        st.caption(
            "Min Risk favours stocks with low risk and low correlation to the others "
            "(paler cells), since those lower the portfolio's overall risk."
        )
    render_checks(result.checks)

elif choice in ("Max Return", "Max Dividend"):
    label = "expected return" if choice == "Max Return" else "dividend yield"
    if choice == "Max Dividend":
        render_dividend_flags()
    held, _ = render_holdings(result)
    render_main_stats(pstats)
    m5, m6, _ = st.columns(3)
    m5.metric(f"Equal-weight {label}", f"{result.equal_weight_value:.2%}",
              help=f"An equal share in all {len(tickers)} stocks, for comparison.")
    m6.metric(f"Exact optimum {label}", f"{result.exact_value:.2%}",
              help="Worked out directly: hold the top stocks, give each the 2.5% floor, then "
              "fill the best ones up to the 30% cap. The optimizer must match it.")
    st.caption(
        f"Maximizing {label} is a linear goal, so the optimizer fills the best stocks up to "
        f"the {constraints.max_weight:.0%} cap; the minimum-stock rule brings in further stocks "
        f"at the {constraints.min_weight:.1%} floor, and one stock takes whatever is left over. "
        "This concentration is expected, not a bug."
    )
    render_notes(held)
    render_checks(result.checks)

else:  # Max Sharpe
    st.caption(
        f"⚠️ One risk-free rate ({risk_free_rate:.2%}) is applied to every stock, although "
        + (f"the portfolio mixes {', '.join(currencies)} stocks whose home rates differ. "
           if len(currencies) > 1 else "home interest rates differ between markets. ")
        + "Expected returns are price-only (dividends excluded), which understates Sharpe "
        "ratios for dividend payers."
    )
    left, right = st.columns([1, 1.2])
    with left:
        held, _ = render_holdings(result)
        render_main_stats(pstats, per_row=2)
        m5, m6 = metric_slots(2, 2)
        m5.metric("Equal-weight Sharpe", f"{result.equal_weight_sharpe:.3f}",
                  help=f"An equal share in all {len(tickers)} stocks, for comparison.")
        m6.metric(
            "Theoretical ceiling",
            f"{result.ceiling_sharpe:.3f}" if result.ceiling_sharpe is not None else "n/a",
            help=f"Highest possible Sharpe ratio if the {constraints.min_weight:.1%} minimum and "
            "the minimum-stock rules didn't exist (solved exactly). The true best portfolio "
            "under all the rules lies between the optimized Sharpe and this.",
        )
        render_notes(held)
    with right:
        st.markdown("**Efficient frontier** (same rules as the portfolios)")
        if frontier is not None:
            st.plotly_chart(frontier_chart(frontier, result), width="stretch", key="frontier")
            st.caption(
                f"Lowest-risk portfolio for each target return, under the same {constraints.max_weight:.0%} "
                f"cap, {constraints.min_weight:.1%} floor and minimum-stock rules "
                f"({frontier.points_solved} of {frontier.points_requested} swept points solved). "
                "The curve runs from Min Risk (left end) to Max Return (top end); Max Sharpe "
                "is the point with the best return per unit of risk."
            )
    checks = list(result.checks)
    if frontier is not None:
        checks.append(frontier_check(frontier, result.risk, result.expected_return))
    render_checks(checks)
