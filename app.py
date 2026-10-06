"""Virtual Portfolio Builder: Streamlit UI.

Current scope (V1, step 1): input tickers/names -> resolve & confirm -> fetch raw data -> display.
No returns, risk, covariance or optimization yet.
"""

import pandas as pd
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
st.caption("V1 · Data pipeline check: raw prices, last price and dividend yield only.")

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
