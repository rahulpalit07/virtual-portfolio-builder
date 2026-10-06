"""Virtual Portfolio Builder: Streamlit UI.

Current scope (V1, steps 1-2): input tickers/names -> resolve & confirm -> fetch raw data ->
returns, risk, covariance and correlation. No optimization yet.
"""

import pandas as pd
import plotly.express as px
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
st.caption("V1 · Data, returns, risk and covariance. No optimization yet.")

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
