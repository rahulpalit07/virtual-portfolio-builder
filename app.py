"""Virtual Portfolio Builder: Streamlit UI (presentation only; all calculations live in
data.py, stats.py, optimizer.py, frontier.py and rates.py).

Page flow (UI redesign, see UI_REDESIGN_PLAN.md): 1. Your stocks (market, input, matches,
build) -> 2. Your portfolios (comparison + one portfolio at a time) -> Under the hood
(data, returns & risk, matrices, sanity checks) -> Methodology & limitations -> footer.
"""

import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from data import (
    EXACT,
    EXCHANGES,
    MULTIPLE,
    NO_MATCH,
    SINGLE,
    Resolution,
    TickerData,
    fetch_ticker_data,
    listing_currency,
    market_of_exchange,
    out_of_market_reasons,
    resolve,
)
from frontier import efficient_frontier, frontier_check
from optimizer import (
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
from rates import risk_free_rate as fetch_risk_free_rate
from stats import compute_stats

MIN_TICKERS = 10  # Section 2.1

# How each included stock was matched; carried through to the output
MATCH_EXACT = "✅ Exact ticker"
MATCH_SINGLE = "✅ Single match"
MATCH_AUTO = "⚠️ Auto-picked"
MATCH_PICKED = "✅ Picked by you"
MATCH_SWITCHED = "⚠️ Switched listing"  # another market's ticker was typed; selected market's listing used
MATCH_OUTSIDE = "⚠️ Outside market (included by you)"

SKIP_NO_MATCH = "No match"
SKIP_BY_USER = "Skipped by you"

MARKET_EXAMPLES = {
    "India (NSE)": ("RELIANCE", "Reliance Industries"),
    "Australia (ASX)": ("BHP", "Commonwealth Bank"),
    "USA": ("AAPL", "Microsoft"),
}

# One-click examples: 11 well-known stocks per market, verified 2026-10-08 to resolve as exact
# tickers with no out-of-market flags, all paying dividends (so Max Dividend always works).
EXAMPLE_STOCKS = {
    "India (NSE)": ["RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "ITC", "HINDUNILVR",
                    "BHARTIARTL", "LT", "SBIN", "ASIANPAINT"],
    "Australia (ASX)": ["BHP", "CBA", "CSL", "NAB", "WBC", "ANZ", "WES", "WOW", "TLS", "RIO", "MQG"],
    "USA": ["AAPL", "MSFT", "JNJ", "KO", "PG", "JPM", "XOM", "WMT", "PEP", "MRK", "HD"],
}

PARALLEL_WORKERS = 6  # concurrent Yahoo requests; kept modest to avoid rate limits

AUTHOR = "Rahul Palit"
LINKEDIN_URL = "https://www.linkedin.com/in/rahul-palit/"
GITHUB_URL = "https://github.com/rahulpalit07/virtual-portfolio-builder"

st.set_page_config(page_title="Virtual Portfolio Builder", layout="wide")


# ---- Caches (in memory only) -------------------------------------------------------------
def parallel_map(fn, items: list) -> list:
    """Run `fn` over `items` in threads, keeping order. Only plain (non-Streamlit) functions."""
    with ThreadPoolExecutor(max_workers=PARALLEL_WORKERS) as ex:
        return list(ex.map(fn, items))


@st.cache_data(ttl=3600, show_spinner=False)
def cached_resolve_all(queries: tuple, market: str) -> tuple[list[Resolution], dict]:
    """Resolve every input in parallel, plus each candidate listing's currency."""
    resolutions = parallel_map(lambda q: resolve(q, market), list(queries))
    symbols = sorted({c.symbol for r in resolutions for c in r.candidates})
    return resolutions, dict(zip(symbols, parallel_map(listing_currency, symbols)))


@st.cache_data(ttl=3600, show_spinner=False)
def cached_fetch_all(items: tuple) -> list[TickerData]:
    """Fetch every stock in parallel. `items`: (symbol, listing market, input, company name)."""
    return parallel_map(lambda it: fetch_ticker_data(*it), list(items))


# Portfolio caches: keyed on exactly what each calculation depends on, so switching the
# portfolio view never re-optimizes, and changing an input recomputes only what uses it.
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
def cached_currency(symbol: str) -> str | None:
    return listing_currency(symbol)


@st.cache_data(ttl=3600, show_spinner=False)
def cached_risk_free_rate(market: str):
    return fetch_risk_free_rate(market)


# ---- Small display helpers ------------------------------------------------------------------
def fmt_price(td: TickerData) -> str:
    if td.last_price is None:
        return "N/A"
    return f"{td.last_price:,.2f} {td.currency or ''}".strip()


def fmt_yield(td: TickerData) -> str:
    return "N/A" if td.ttm_dividend_yield is None else f"{td.ttm_dividend_yield:.2%}"


def fit_height(rows: int) -> int:
    """Table height that shows every row with no internal scrolling."""
    return 38 + 35 * max(rows, 1)


# Colours (user decision 2026-10-08): accents light green (theme primary in
# .streamlit/config.toml), red only for errors, flags yellow.
GREEN = "#4CAF50"
CHART_COLORS = {"Min Risk": "#1E88E5", "Max Return": "#8E24AA", "Max Sharpe": "#2E7D32"}
CORR_SCALE = "PRGn"  # purple (−1) → white (0) → green (+1); no red, which means "error" here
FLAG_CELL = "background-color: rgba(250, 202, 43, 0.28)"  # yellow, readable in light and dark


def flag(text: str) -> str:
    """Markdown for a flag: yellow text."""
    return f":yellow[{text}]"


TRANSPARENT = dict(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")  # Plotly on the page background

# Match status as a narrow icon column in the holdings table (meaning in the column's tooltip)
MATCH_ICON = {
    MATCH_EXACT: "✅", MATCH_SINGLE: "✅", MATCH_PICKED: "✅",
    MATCH_AUTO: "⚠️", MATCH_SWITCHED: "🔁", MATCH_OUTSIDE: "🌐",
}
FLAG_ICONS = ("⚠️", "🔁", "🌐")
MATCH_HELP = (
    "How the stock was matched. ✅ matched (exact ticker, single match or picked by you). "
    "⚠️ auto-picked from several matches: check it's the company you meant. "
    "🔁 you typed another market's ticker; this market's listing is used. "
    "🌐 outside the selected market, included by you."
)


def flag_cells(df: pd.DataFrame, columns: list[str]):
    """Styler that shades flagged cells (text starting with ⚠️, 🔁 or 🌐) yellow in `columns`."""
    cols = [c for c in columns if c in df.columns]
    return df.style.map(lambda v: FLAG_CELL if str(v).startswith(FLAG_ICONS) else "", subset=cols)


# ---- Portfolio presentation (one entry per portfolio: V2 / V3 add an entry) --------------------
# What each portfolio does + the kind of investor who'd look for it (describes investor types;
# not a recommendation). User copy, 2026-10-08.
WHY_THIS_PORTFOLIO = {
    "Min Risk": "The steadiest mix your stocks allow: it combines them so that overall ups and "
    "downs are as small as possible. *For a cautious investor who cares more about a smooth "
    "ride than about the highest return.*",
    "Max Return": "Leans as hard as the rules allow into the stocks with the highest historical "
    "returns. *For a growth-seeking investor with a long horizon who can live with big swings "
    "and a concentrated portfolio.*",
    "Max Dividend": "Leans into the stocks that paid the most in dividends over the last 12 "
    "months. *For an income-focused investor who wants regular cash payouts more than price "
    "growth.*",
    "Max Sharpe": "The best trade-off: the most expected return for each unit of risk taken. "
    "*For an investor who wants growth but wants every bit of risk to be worth it.*",
}
EQUAL_WEIGHT_ROW = "Equal weight (reference)"
# Metric cards: (stats key, label, kind, delta colouring vs equal weight, help). "inverse" for
# risk: lower than equal weight is green. Dividend yield: higher is green (my choice; user may change).
CARD_SPECS = [
    ("expected_return", "Expected return", "pct", "normal",
     "Weighted average of each stock's historical annual return. The line below compares it "
     "with an equal share in all {n} stocks."),
    ("risk", "Risk", "pct", "inverse",
     "Annual volatility of the portfolio (standard deviation of returns); lower is steadier. "
     "The line below compares it with an equal share in all {n} stocks."),
    ("dividend_yield", "Dividend yield", "pct", "normal",
     "Weighted dividends paid over the last 12 months. The line below compares it with an "
     "equal share in all {n} stocks."),
    ("sharpe", "Sharpe ratio", "num", "normal",
     "(Expected return − risk-free rate {rf:.2%}) ÷ risk: return per unit of risk. The line "
     "below compares it with an equal share in all {n} stocks."),
]
# Comparison table: best value per column (higher or lower is better), compared at the shown precision
BEST_IS = {"Expected return": "max", "Risk": "min", "Dividend yield": "max", "Sharpe ratio": "max"}
SHOWN_DECIMALS = {"Expected return": 2, "Risk": 2, "Dividend yield": 2, "Sharpe ratio": 3}
BEST_CELL = "background-color: #B9E4BB; font-weight: 700"  # light green, readable on the light blue page
# Donut slices: no red (red means errors / worse than equal weight), no yellow (flags); adjacent
# colours contrast in hue and lightness
DONUT_COLORS = ["#2E7D32", "#1E88E5", "#8E24AA", "#00ACC1", "#7CB342", "#3949AB",
                "#00897B", "#6D4C41", "#81D4FA", "#546E7A", "#BA68C8", "#A5D6A7"]
DONUT_ROTATION = 270  # first slice starts at 9 o'clock


def best_rows(table: pd.DataFrame, eligible: list[int]) -> dict[str, list[int]]:
    """Row positions holding the best value in each compared column, among `eligible` rows
    (never the equal-weight reference). Values are compared as numbers rounded to the shown
    precision, so everything that displays as the best (ties) is highlighted."""
    best = {}
    for col, how in BEST_IS.items():
        if col not in table.columns:
            continue
        values = pd.to_numeric(table.loc[eligible, col], errors="coerce").round(SHOWN_DECIMALS[col]).dropna()
        if values.empty:
            continue
        target = values.max() if how == "max" else values.min()
        best[col] = list(values.index[values == target])
    return best


def highlight_best(table: pd.DataFrame, best: dict[str, list[int]]):
    """Styler with the best cells filled light green. Number formats come from column_config,
    which takes precedence over the Styler, so they are unchanged."""
    styles = pd.DataFrame("", index=table.index, columns=table.columns)
    for col, idx in best.items():
        styles.loc[idx, col] = BEST_CELL
    return table.style.apply(lambda _t: styles, axis=None)


def render_methodology() -> None:
    c = Constraints()
    with st.expander("Methodology & limitations"):
        st.markdown(
            f"""
- **Data:** daily prices for up to the last 5 years and the last 12 months of dividends, from
  Yahoo Finance (unofficial, free data). One market per session: India (NSE), Australia (ASX)
  or USA.
- **Returns and risk:** daily simple returns on the closing price, **price only (dividends
  excluded)**, annualized. Expected return is the historical average; risk is the
  historical volatility; the covariance matrix captures how stocks move together.
- **Portfolios (Modern Portfolio Theory):** Min Risk, Max Return, Max Dividend and Max
  Sharpe, each a separate 100% allocation. Rules for all of them: no short-selling, each stock
  either 0% or between **{c.min_weight:.1%} and {c.max_weight:.0%}**, and at least
  **{c.min_stocks}** stocks held (adjustable in the sidebar).
- **Risk-free rate** (for Sharpe ratios): the selected market's 10-year government bond
  yield, fetched live from CNBC; a stored fallback value (with its date) is used and clearly
  marked if the live fetch fails. You can override it in the sidebar.
- **Currency:** one market per session, so all stocks share one currency. No currency
  conversion is applied: if you choose to include a stock from another market, its returns
  stay in its own currency.
- **Limitations:** past returns don't predict future returns; historical averages are noisy;
  dividends are left out of returns; data comes from free, unofficial sources.
"""
        )


def render_footer() -> None:
    st.divider()
    st.caption(
        f"Educational tool, not financial advice. · Built by {AUTHOR} · "
        f"[LinkedIn]({LINKEDIN_URL}) · [GitHub]({GITHUB_URL})"
    )


def finish() -> None:
    """End the page early (nothing more to show yet), keeping methodology and footer."""
    render_methodology()
    render_footer()
    st.stop()


# ---- Header ----------------------------------------------------------------------------------
st.title("Virtual Portfolio Builder")
if st.session_state.pop("scroll_to_top", False):  # after "Start a new analysis"
    st.html(
        "<script>window.scrollTo(0, 0); document.querySelectorAll("
        "'[data-testid=\"stMain\"], [data-testid=\"stAppViewContainer\"], section.main')"
        ".forEach(e => e.scrollTo(0, 0));</script>",
        unsafe_allow_javascript=True,
    )
st.markdown(
    "Enter the stocks you're interested in and get four optimized portfolios, built with "
    "Nobel Prize-winning portfolio theory: lowest risk, highest return, highest dividend "
    "income and best return for the risk."
)

# ---- Session state & market selection (one market per session, PROJECT_SPEC.md 2.6) --------
ss = st.session_state
ss.setdefault("market", None)
ss.setdefault("market_version", 0)  # bumped to reset the market radio to ss.market
ss.setdefault("input_version", 0)  # bumped to clear (or pre-fill) the input table
PROGRESS_KEYS = ("resolutions", "fetched", "listing_currencies")


def input_key() -> str:
    return f"input_{ss.input_version}"


def parse_stocks(text: str | None) -> list[str]:
    """Split pasted input on commas, semicolons, tabs and new lines (not spaces: company names
    such as "Commonwealth Bank" contain them); trim, drop blanks, keep the order entered."""
    return [p.strip() for p in re.split(r"[,;\t\r\n]+", text or "") if p.strip()]


def has_progress() -> bool:
    typed = bool(parse_stocks(ss.get(input_key())))
    return typed or bool(ss.get("input_seed")) or any(k in ss for k in PROGRESS_KEYS)


def clear_progress() -> None:
    """Wipe the session's progress: entered stocks and all results (user decision)."""
    for k in list(ss.keys()):
        if k in PROGRESS_KEYS or k.startswith(("inc_", "pick_")) or (
            k.startswith("input_") and k != "input_version"
        ):
            del ss[k]
    ss.pop("input_seed", None)
    ss.pop("portfolio_view", None)
    ss.pop("s1_attention_seen", None)
    ss.pop("pending_reset", None)
    ss.input_version += 1


def load_example(market_name: str) -> None:
    """Start over with the market's example list, then find and build automatically."""
    clear_progress()
    ss.pop("pending_example", None)
    ss.market = market_name
    ss.market_version += 1
    ss.input_seed = EXAMPLE_STOCKS[market_name]
    ss.auto_run = True


def start_new_analysis() -> None:
    """Back to the very beginning (user decision 2026-10-08; confirmed first): everything
    clear_progress() wipes, plus the market choice (nothing pre-selected, spec 2.6), the sidebar
    settings, any pending confirmation and section 1's collapsed state. Data caches stay warm."""
    clear_progress()
    for k in list(ss.keys()):
        if k in ("min_stocks", "pending_example", "pending_reset", "section1_open") or k.startswith(("rf_", "s1_")):
            del ss[k]
    ss.market = None
    ss.market_version += 1  # a fresh market radio with nothing selected
    ss.scroll_to_top = True


def request_example(market_name: str) -> None:
    if has_progress():
        ss.pending_example = market_name  # loading an example clears the session: confirm first
    else:
        load_example(market_name)


# Section 1 collapses to one line once portfolios are built (user decision 2026-10-08), so the
# results start near the top. It is a stateful expander: widgets inside a closed expander still
# run, so the market, text box, picks and Include choices keep their state. It is forced open
# whenever the user needs to act or see something there (ensure_section1_open).
S1_KEY = "section1_open"
if ss.pop("s1_open_next", False):
    ss[S1_KEY] = True
if ss.pop("s1_collapse_next", False):
    ss[S1_KEY] = False
section1_collapsible = bool(ss.get("fetched"))


class StopSection(Exception):
    """Ends section 1 early; the page then finishes outside the section's container."""


def ensure_section1_open() -> None:
    """Open the collapsed section (takes effect on an immediate rerun)."""
    if section1_collapsible and not ss.get(S1_KEY):
        ss.s1_open_next = True
        st.rerun()


def section1_label() -> str:
    _inc, skipped_before, results_before = ss.fetched
    n_ok = sum(1 for r in results_before if r.ok)
    label = f"**1. Your stocks** · {ss.market} · {n_ok} stock{'s' if n_ok != 1 else ''}"
    if skipped_before:
        label += f" · {len(skipped_before)} skipped"
    if len(results_before) > n_ok:
        label += " · " + flag(f"⚠️ {len(results_before) - n_ok} failed to fetch")
    return label + ("" if ss.get(S1_KEY) else " · click to edit")


if section1_collapsible:
    ss[S1_KEY] = ss.get(S1_KEY, False)  # re-asserted every run, so a label change can't reset it
    section1 = st.expander(section1_label(), key=S1_KEY, on_change="rerun")
else:
    st.header("1. Your stocks")
    section1 = st.container()

try:
    with section1:
        market_col, example_col = st.columns([1, 1.25], vertical_alignment="bottom")
        market_choice = market_col.radio(
            "Market for this session (all stocks must come from it)",
            EXCHANGES,
            index=EXCHANGES.index(ss.market) if ss.market else None,
            horizontal=True,
            key=f"market_radio_{ss.market_version}",
        )
        with example_col.container(horizontal=True, vertical_alignment="center", gap="small"):
            st.markdown("No list handy? **Try an example:**", width="content")
            for m in EXCHANGES:
                st.button(m, key=f"example_{m}", on_click=request_example, args=(m,), width="content")

        if ss.get("pending_example"):
            pending = ss.pending_example
            st.warning(
                f"Load the **{pending}** example? This clears everything in this session: the "
                "stocks you entered and all results."
            )
            b1, b2, _ = st.columns([1.3, 1.3, 3])
            b1.button(f"Load {pending} example and clear", type="primary", on_click=load_example, args=(pending,))
            b2.button("Cancel", on_click=lambda: ss.pop("pending_example", None))
            ensure_section1_open()
            raise StopSection

        if market_choice is None:
            st.info("Choose a market to start: India (NSE), Australia (ASX) or USA, or try an example.")
            raise StopSection

        if ss.market is None:
            ss.market = market_choice
        elif market_choice != ss.market:
            if has_progress():
                st.warning(
                    f"Switch the market from **{ss.market}** to **{market_choice}**? This clears "
                    "everything in this session: the stocks you entered and all results."
                )
                b1, b2, _ = st.columns([1.3, 1.3, 3])
                if b1.button(f"Switch to {market_choice} and clear", type="primary"):
                    clear_progress()
                    ss.market = market_choice
                    ss.market_version += 1
                    st.rerun()
                if b2.button(f"Cancel, stay on {ss.market}"):
                    ss.market_version += 1
                    st.rerun()
                ensure_section1_open()
                raise StopSection
            ss.market = market_choice

        market = ss.market

        # Sidebar (shown once a market is chosen); settings appear after portfolios are built
        st.sidebar.header("Settings")
        if not ss.get("fetched"):
            st.sidebar.caption("Settings appear here once your portfolios are built.")

        # ---- Input --------------------------------------------------------------------------------
        ticker_eg, name_eg = MARKET_EXAMPLES[market]
        seed = ss.get("input_seed") or []
        with st.form("tickers", border=False):
            box_col, side_col = st.columns([3, 2])
            box_col.text_area(
                "Your stocks",
                value=", ".join(seed),
                height=120,
                key=input_key(),
                placeholder=f"e.g. {ticker_eg}, {name_eg}, …",
                label_visibility="collapsed",
            )
            side_col.markdown(
                f"Enter at least {MIN_TICKERS} **{market}** stocks, by ticker (e.g. `{ticker_eg}`) "
                f"or company name (e.g. `{name_eg}`), separated by commas or new lines."
            )
            resolve_clicked = side_col.form_submit_button("Find stocks", type="primary")

        auto_run = ss.pop("auto_run", False)
        if resolve_clicked or auto_run:
            # Exact repeats are dropped here (as before); other duplicates are handled in the matches
            queries = seed if auto_run else list(dict.fromkeys(parse_stocks(ss.get(input_key()))))
            if not queries:
                st.error("Please enter at least one ticker or company name.")
                raise StopSection

            with st.spinner(f"Looking up {len(queries)} stocks on {market}…"):
                ss.resolutions, ss.listing_currencies = cached_resolve_all(tuple(queries), market)
            ss.pop("fetched", None)
            ss.auto_build = auto_run

        resolutions: list[Resolution] = ss.get("resolutions", [])
        if not resolutions:
            raise StopSection


        def currency_of(symbol: str) -> str | None:
            known = ss.get("listing_currencies") or {}
            return known[symbol] if symbol in known else cached_currency(symbol)


        # ---- Confirm matches (collapsed unless something needs attention) ----------------------------
        def needs_attention() -> list[str]:
            """Rows to look at before building: unmatched, auto-picked, switched, flagged, duplicates."""
            notes, seen = [], set()
            for i, r in enumerate(resolutions):
                if r.status == NO_MATCH:
                    notes.append(r.query)
                    continue
                pick = min(ss.get(f"pick_{i}_{r.query}", 0), len(r.candidates) - 1)
                chosen = r.candidates[pick]
                if (
                    (r.status == MULTIPLE and pick == 0)
                    or r.switched
                    or out_of_market_reasons(chosen, market, currency_of(chosen.symbol))
                    or chosen.symbol in seen
                ):
                    notes.append(r.query)
                seen.add(chosen.symbol)
            return notes


        attention = needs_attention()
        # Open once when a match needing attention first appears (or on a build with one), then
        # let the user collapse it: such rows often stay as they are (user decision 2026-10-08)
        if attention and ss.get("s1_attention_seen") != tuple(attention):
            ss.s1_attention_seen = tuple(attention)
            ensure_section1_open()
        n_found = sum(1 for r in resolutions if r.status != NO_MATCH)
        matches_label = (
            flag(f"⚠️ {n_found} of {len(resolutions)} found · {len(attention)} need your attention")
            if attention
            else f"✅ {n_found} stocks matched"
        )

        # included: (symbol, listing market, input, company name, match type)
        included: list[tuple[str, str, str, str, str]] = []
        skipped: list[tuple[str, str]] = []  # (input, reason)
        with st.expander(matches_label, expanded=bool(attention)):
            st.caption(
                f"Check that each input matched the company you meant on **{market}**. Where there "
                "are several matches, pick the right one from the dropdown. Untick **Include** to skip "
                "a stock. Stocks that don't look like they belong to this market are flagged and start "
                "unticked; tick them to include them anyway. To fix an input instead, edit it in the "
                "box above and click **Find stocks** again."
            )
            widths = [0.7, 2, 4, 3.4]
            header = st.columns(widths)
            for col, title in zip(header, ["Include", "Your input", "Matched stock", "Status"]):
                col.markdown(f"**{title}**")

            for i, r in enumerate(resolutions):
                c0, c1, c3, c4 = st.columns(widths, vertical_alignment="center")
                c1.write(f"“{r.query}”")
                key = f"{i}_{r.query}"

                if r.status == NO_MATCH:
                    c0.checkbox("Include", value=False, disabled=True, key=f"inc_{key}",
                                label_visibility="collapsed")
                    c3.write(f"_{r.error or r.note or f'No stock found on {market}.'}_")
                    c4.write(flag("⚠️ No match: will be skipped"))
                    skipped.append((r.query, SKIP_NO_MATCH))
                    continue

                pick = c3.selectbox(
                    f"Match for {r.query}",
                    options=range(len(r.candidates)),
                    format_func=lambda j, r=r: r.candidates[j].label,
                    key=f"pick_{key}",
                    label_visibility="collapsed",
                )
                chosen = r.candidates[pick]
                reasons = out_of_market_reasons(chosen, market, currency_of(chosen.symbol))
                # Flagged listings start unticked (user decision); ticking one is the override
                include = c0.checkbox("Include", value=not reasons, key=f"inc_{key}_{chosen.symbol}",
                                      label_visibility="collapsed")

                if reasons:
                    match = MATCH_OUTSIDE
                elif r.switched:
                    match = MATCH_SWITCHED
                elif pick != 0:
                    match = MATCH_PICKED
                elif r.status == EXACT:
                    match = MATCH_EXACT
                elif r.status == SINGLE:
                    match = MATCH_SINGLE
                else:
                    match = MATCH_AUTO

                if reasons:
                    flag_text = f"⚠️ Outside {market}: " + "; ".join(reasons)
                    if not include:
                        c4.write(flag(f"{flag_text}. Not included; tick to include anyway."))
                        skipped.append((r.query, f"Outside {market} ({'; '.join(reasons)})"))
                        continue
                    c4.write(flag(f"{flag_text}. **Included by you.**"))
                elif not include:
                    c4.write("⏭️ Skipped by you")
                    skipped.append((r.query, SKIP_BY_USER))
                    continue

                # Several inputs resolving to the same stock: fetch it once, skip the later ones
                first = next((e for e in included if e[0] == chosen.symbol), None)
                if first is not None:
                    reason = f"Duplicate of “{first[2]}” ({chosen.symbol})"
                    c4.write(f"⏭️ {reason}: will be skipped")
                    skipped.append((r.query, reason))
                    continue

                if match == MATCH_SWITCHED:
                    c4.write(flag(
                        f"⚠️ You entered {r.entered.symbol} ({r.entered.exchange_display}); using the "
                        f"{market} listing instead (its price and currency)."
                    ))
                elif match == MATCH_AUTO:
                    c4.write(flag(f"⚠️ Auto-picked top of {len(r.candidates)} matches (not changed)"))
                elif match != MATCH_OUTSIDE:
                    c4.write(match)
                listing_market = market_of_exchange(chosen.exchange_code) or market
                included.append((chosen.symbol, listing_market, r.query, chosen.name, match))

        auto_picked = [e for e in included if e[4] == MATCH_AUTO]
        if auto_picked:
            st.warning(
                f"⚠️ {len(auto_picked)} stock(s) were auto-picked from several possible matches: "
                + ", ".join(f"“{e[2]}” → {e[0]} ({e[3]})" for e in auto_picked)
                + ". Check them in the matches above."
            )
        if included and len(included) < MIN_TICKERS:
            st.caption(
                f"{len(included)} stock(s) included. The spec asks for at least {MIN_TICKERS}; "
                "portfolios are still built."
            )
        if skipped:
            st.caption(
                f"**Will skip {len(skipped)}:** "
                + "; ".join(f"“{q}”: {reason}" for q, reason in skipped)
            )
        if not included:
            st.info("No stocks are included. Tick **Include** on at least one matched row to build.")

        build_label = f"Build portfolios ({len(included)} stock{'s' if len(included) != 1 else ''}"
        build_label += f", skipping {len(skipped)})" if skipped else ")"
        build_clicked = st.button(build_label, type="primary", disabled=not included)
        if ss.pop("auto_build", False) and included:
            build_clicked = True

        if build_clicked:
            with st.spinner(f"Fetching 5 years of prices for {len(included)} stocks…"):
                results = cached_fetch_all(tuple((s, ex, q, n) for s, ex, q, n, _m in included))
            ss.fetched = (included, skipped, results)
            ss.s1_collapse_next = True  # results start near the top: collapse section 1
            ss.pop("s1_attention_seen", None)  # ...but reopen once if a match still needs attention
            st.rerun()

        fetched = ss.get("fetched")
        if not fetched:
            raise StopSection
        if fetched[0] != included or fetched[1] != skipped:
            ensure_section1_open()
            st.info("Your selections changed since the last build. Click **Build portfolios** to refresh.")
            raise StopSection
except StopSection:
    finish()

_, skipped, results = fetched
match_of = {entry[0]: entry[4] for entry in included}
ok = [r for r in results if r.ok]
failed = [r for r in results if not r.ok]
if not ok:
    st.error("No price data could be fetched for the included stocks.")
    finish()

res = compute_stats(ok)
by_symbol = {r.yahoo_symbol: r for r in ok}
currencies = sorted({r.currency or "?" for r in ok})
latest = max(r.prices.index[-1] for r in ok)
summary = f"**{len(ok)} stocks** · up to 5 years of daily prices · to {latest:%d %b %Y}"
if skipped:
    summary += f" · {len(skipped)} skipped"
if failed:
    summary += " · " + flag(f"⚠️ {len(failed)} failed to fetch ({', '.join(r.yahoo_symbol for r in failed)})")
section1.caption(summary)

# ---- Settings (sidebar) ---------------------------------------------------------------------
defaults = Constraints()
tickers = list(res.cov.index)
floor_count = defaults.stocks_needed_for_cap
min_stocks = st.sidebar.number_input(
    "Minimum number of stocks held",
    min_value=floor_count,
    max_value=max(floor_count, min(len(tickers), defaults.max_stocks_for_floor)),
    value=max(floor_count, min(defaults.min_stocks, len(tickers))),
    step=1,
    key="min_stocks",
    help=f"With a {defaults.max_weight:.0%} cap, at least {floor_count} stocks are always "
    "needed to reach 100%, so the minimum can't go lower than that.",
)
# Risk-free rate: the market's 10-year government bond yield (Section 3.4), user-overridable
rf_info = cached_risk_free_rate(market)
rf_pct = st.sidebar.number_input(
    "Risk-free rate for Max Sharpe (% per year)",
    min_value=0.0,
    max_value=50.0,
    value=round(rf_info.value * 100, 3),
    step=0.25,
    format="%.3f",
    key=f"rf_{market}_{rf_info.value}",  # resets to the fetched value if it changes
    help=f"Defaults to the {rf_info.name}. Used for every Sharpe ratio shown. You can "
    "override it.",
)
risk_free_rate = rf_pct / 100
rf_overridden = abs(rf_pct - round(rf_info.value * 100, 3)) > 1e-9
rf_line = (
    f"**Risk-free rate:** {rf_info.name} **{rf_info.value:.3%}** · Source: {rf_info.source} "
    f"· As of: {rf_info.as_of}"
)
if rf_info.is_fallback:
    st.sidebar.warning(f"⚠️ **Fallback value in use.** {rf_info.note}\n\n{rf_line}")
else:
    st.sidebar.caption(f"{rf_line} (live)")
if rf_overridden:
    st.sidebar.info(f"Overridden by you: **{rf_pct:.3f}%** is used.")
constraints = replace(defaults, min_stocks=int(min_stocks))

# Shared by every portfolio: repaired once, used for both optimizing and the displayed figures
prepared = prepare_covariance(res.cov)
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


# ---- 2. Your portfolios -----------------------------------------------------------------------
st.header("2. Your portfolios")

failed_data_checks = [c for c in res.checks if not c.passed]
if failed_data_checks:
    st.error(
        f"❌ {len(failed_data_checks)} data sanity check(s) failed: "
        + "; ".join(c.name for c in failed_data_checks)
        + ". Look at these under the hood before relying on the numbers."
    )
if rf_info.is_fallback:
    st.warning(f"⚠️ **Fallback risk-free rate in use.** {rf_info.note}\n\n{rf_line}")
if prepared.note:
    st.info(prepared.note)
if len(currencies) > 1:
    st.warning(
        f"⚠️ **Mixed currencies ({', '.join(currencies)}).** You included stocks from outside "
        f"{market}. Each stock's return and risk are in its own currency, with no conversion, "
        "so comparisons between them are biased."
    )
def short_flag(flag: str) -> str:
    """A few words for a stats flag (the full text is shown under the hood)."""
    if "history" in flag:
        return "short history"
    if "0% return" in flag:
        return "possibly stale prices"
    if "risk" in flag:
        return "very high risk"
    if "return" in flag:
        return "extreme return"
    return "unusual data"


flagged = [s for s in res.stocks.values() if s.flags]
if flagged or res.high_corr_pairs:
    parts = [f"{s.symbol} ({', '.join(dict.fromkeys(short_flag(f) for f in s.flags))})" for s in flagged]
    parts += [f"{a} & {b} move almost identically" for a, b, _x in res.high_corr_pairs]
    st.warning("⚠️ Data worth a look: " + "; ".join(parts) + ". Details under the hood.")

# Comparison of all four (plus equal weight as a reference). The equal-weight figures computed
# here also give every metric card its "vs equal weight" delta, so cards and table always agree.
ew_stats = stats_of(equal_weights(tickers))
pstats_of = {name: stats_of(r.weights) for name, r in portfolios.items() if r.weights is not None}

st.subheader("Comparison")
rows = []
for name, r in portfolios.items():
    if r.weights is None:
        rows.append({"Portfolio": name, "Status": "Not available (see below)"})
        continue
    s = pstats_of[name]
    rows.append({
        "Portfolio": name,
        "Expected return": s["expected_return"] * 100,
        "Risk": s["risk"] * 100,
        "Dividend yield": s["dividend_yield"] * 100,
        "Sharpe ratio": s["sharpe"],
        "Stocks held": len(r.held),
        "Status": "❌ failed a check" if r.error else "",
    })
rows.append({
    "Portfolio": EQUAL_WEIGHT_ROW,
    "Expected return": ew_stats["expected_return"] * 100,
    "Risk": ew_stats["risk"] * 100,
    "Dividend yield": ew_stats["dividend_yield"] * 100,
    "Sharpe ratio": ew_stats["sharpe"],
    "Stocks held": len(tickers),
    "Status": "",
})
comparison = pd.DataFrame(rows)
# Best per column among the portfolios that were built and passed their checks
eligible = [i for i, r in enumerate(portfolios.values()) if r.weights is not None and not r.error]
best = best_rows(comparison, eligible)
if not comparison["Status"].astype(bool).any():
    comparison = comparison.drop(columns="Status")
pct2 = st.column_config.NumberColumn(format="%.2f%%")
st.dataframe(
    highlight_best(comparison, best),
    width="stretch",
    hide_index=True,
    height=fit_height(len(comparison)),
    column_config={
        "Expected return": pct2,
        "Risk": pct2,
        "Dividend yield": pct2,
        "Sharpe ratio": st.column_config.NumberColumn(format="%.3f"),
    },
)
st.caption(
    "Green = best in each column (highest return, yield and Sharpe ratio; lowest risk). "
    f"Sharpe ratio = (expected return − risk-free rate {risk_free_rate:.2%}) ÷ risk. "
    "Expected returns are historical and price-only (dividends excluded)."
)

choice = st.segmented_control(
    "Portfolio", list(portfolios), default="Min Risk", key="portfolio_view",
    label_visibility="collapsed",
) or "Min Risk"
result = portfolios[choice]
st.markdown(WHY_THIS_PORTFOLIO[choice])


def donut_chart(held: pd.Series) -> go.Figure:
    """Held weights as a donut, largest first, clockwise, labels outside the ring. The ring
    starts at 9 o'clock, so the thin floor-sized slices (last) end on the left side, where
    their labels stack vertically instead of overlapping."""
    labels = list(held.index)
    fig = go.Figure(go.Pie(
        labels=labels,
        values=held.to_numpy() * 100,
        hole=0.55,
        sort=False,
        direction="clockwise",
        rotation=DONUT_ROTATION,
        marker=dict(colors=[DONUT_COLORS[i % len(DONUT_COLORS)] for i in range(len(labels))],
                    line=dict(color="white", width=1.5)),
        texttemplate="%{label} %{value:.2f}%",
        textposition="outside",
        automargin=True,  # room for the outside labels, so none is clipped in a narrow column
        outsidetextfont=dict(size=12),
        customdata=[by_symbol[s].company_name for s in labels],
        hovertemplate="<b>%{label}</b><br>%{customdata}<br>Weight %{value:.2f}%<extra></extra>",
    ))
    fig.update_layout(
        showlegend=False,
        height=380,
        margin=dict(l=20, r=20, t=40, b=40),
        annotations=[dict(text=f"<b>{len(labels)}</b><br>stocks held", x=0.5, y=0.5,
                          showarrow=False, font=dict(size=16))],
        **TRANSPARENT,
    )
    return fig


def render_holdings(r, side_by_side: bool) -> tuple[pd.Series, list[str]]:
    """Donut + compact table: side by side in the full-width views, stacked in the narrow
    left column of the views with a side panel."""
    held = r.held
    st.markdown(f"**{choice} portfolio ({len(held)} of {len(tickers)} stocks held)**")
    chart_slot, table_slot = st.columns([1, 1]) if side_by_side else (st.container(), st.container())
    chart_slot.plotly_chart(donut_chart(held), width="stretch", key=f"donut_{choice}")
    with table_slot:
        st.dataframe(
            flag_cells(pd.DataFrame(
                [
                    {
                        "Ticker": s,
                        "Company": by_symbol[s].company_name,
                        "Weight": w * 100,
                        "Match": MATCH_ICON.get(match_of[s], match_of[s]),
                    }
                    for s, w in held.items()
                ]
            ), ["Match"]),
            width="stretch",
            hide_index=True,
            height=fit_height(len(held)),
            column_config={
                # In the narrow column a long company name would overflow into a horizontal
                # scrollbar; cap it there (the full name is in the donut's hover)
                "Company": st.column_config.TextColumn(width=None if side_by_side else 150),
                "Weight": st.column_config.NumberColumn(format="%.2f%%", width="small"),
                "Match": st.column_config.TextColumn(width="small", help=MATCH_HELP),
            },
        )
        excluded = [s for s in tickers if s not in held.index]
        if excluded:
            st.caption("Not held (0%): " + ", ".join(excluded))
        render_notes(held)
    return held, excluded


def delta_text(diff: float, kind: str) -> tuple[str, bool]:
    """Difference from equal weight as shown on a card ("+2.31 pts vs equal weight"), and
    whether it is zero at the shown precision (then it is shown neutral: grey, no arrow)."""
    number = f"{diff * 100:+.2f}" if kind == "pct" else f"{diff:+.3f}"
    zero = float(number) == 0
    if zero:
        number = number.lstrip("+-")
    return f"{number}{' pts' if kind == 'pct' else ''} vs equal weight", zero


def render_cards(pstats: dict[str, float]) -> None:
    """Four metric cards, each with its difference from the equal-weight portfolio: green =
    better than equal weight (lower is better for risk), red = worse (user decision)."""
    for col, (key, label, kind, colouring, help_text) in zip(st.columns(4), CARD_SPECS):
        value = f"{pstats[key]:.2%}" if kind == "pct" else f"{pstats[key]:.3f}"
        text, zero = delta_text(pstats[key] - ew_stats[key], kind)
        col.metric(
            label, value, delta=text,
            delta_color="off" if zero else colouring,
            delta_arrow="off" if zero else "auto",
            help=help_text.format(rf=risk_free_rate, n=len(tickers)),
        )


def render_notes(held: pd.Series) -> None:
    if any(np.isnan(v) for v in yields[held.index]):
        st.caption("Stocks with no dividend data are counted as 0% in the portfolio yield.")
    outside = [s for s in held.index if match_of[s] == MATCH_OUTSIDE]
    if outside:
        st.caption(flag(f"⚠️ Holds stocks outside {market} that you chose to include: {', '.join(outside)}."))


def render_checks(checks, proof: list[tuple[str, str, str]] = (), notes: list[str] = ()) -> None:
    """One collapsed line ("All N checks passed"); opens automatically if any check fails.
    `proof`: (label, value, explanation) figures such as the theoretical floor; `notes`:
    technical explanations kept out of the main view."""
    applicable = [c for c in checks if c.applicable]
    failed = [c for c in applicable if not c.passed]
    if failed:
        st.error(f"❌ {len(failed)} of {len(applicable)} checks failed. Don't rely on this portfolio.")
        label = f"❌ {len(failed)} of {len(applicable)} checks failed: details"
    else:
        label = f"✅ All {len(applicable)} checks passed"
    with st.expander(label, expanded=bool(failed)):
        for note in notes:
            st.caption(note)
        for name, value, explanation in proof:
            st.markdown(f"**{name}: {value}** · _{explanation}_")
        for c in checks:
            icon = "➖" if not c.applicable else ("✅" if c.passed else "❌")
            st.markdown(f"{icon} {c.name} · _{c.detail}_")


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
            "crash or a currency mismatch. Still included; untick it in the matches to "
            "exclude it: " + ", ".join(f"{s} ({y:.1%})" for s, y in flags.implausible)
        )
    if flags.high:
        st.warning(
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
        name="Efficient frontier", line=dict(width=3, color=GREEN),
        hovertemplate="Risk %{x:.2f}%<br>Return %{y:.2f}%<extra>Frontier</extra>",
    ))
    fig.add_trace(go.Scatter(
        x=vols * 100, y=mu.to_numpy() * 100, mode="markers+text", text=tickers,
        textposition="top center", name="Individual stocks", marker=dict(size=8, color="gray"),
        hovertemplate="%{text}<br>Risk %{x:.2f}%<br>Return %{y:.2f}%<extra></extra>",
    ))
    for label, symbol, size in (("Min Risk", "diamond", 14), ("Max Return", "square", 12), ("Max Sharpe", "star", 20)):
        row = fr.anchors[fr.anchors.label == label]
        if row.empty:
            continue
        fig.add_trace(go.Scatter(
            x=row.risk * 100, y=row.expected_return * 100, mode="markers", name=label,
            marker=dict(symbol=symbol, size=size, color=CHART_COLORS[label],
                        line=dict(width=1, color="black")),
            hovertemplate=f"{label}<br>Risk %{{x:.2f}}%<br>Return %{{y:.2f}}%<extra></extra>",
        ))
    fig.update_layout(
        xaxis_title="Annual risk (%)",
        yaxis_title="Annual expected return (%)",
        height=520,
        margin=dict(l=0, r=0, t=70, b=0),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        **TRANSPARENT,
    )
    return fig


if result.weights is None:
    st.error(f"Couldn't build the {choice} portfolio. {result.error}")
    if choice == "Max Dividend":
        render_dividend_flags()
else:
    for note in result.notes:
        st.info(note)
    if result.error:
        st.error(f"{result.error} The portfolio below should not be relied on.")

    render_cards(pstats_of[choice])

    if choice == "Min Risk":
        left, right = st.columns([1, 1.2])
        with left:
            held, excluded = render_holdings(result, side_by_side=False)
        with right:
            st.markdown("**Correlation matrix** (held stocks first, by weight)")
            order = list(held.index) + excluded
            corr_sorted = res.corr.loc[order, order]
            fig = px.imshow(
                corr_sorted,
                text_auto=".2f",
                zmin=-1,
                zmax=1,
                color_continuous_scale=CORR_SCALE,
                aspect="auto",
            )
            fig.update_layout(height=max(300, 40 * len(order) + 120), margin=dict(l=0, r=0, t=10, b=0),
                              **TRANSPARENT)
            st.plotly_chart(fig, width="stretch", key="corr_min_risk")
            st.caption(
                "Min Risk favours stocks with low risk and low correlation to the others "
                "(paler cells), since those lower the portfolio's overall risk."
            )
        render_checks(result.checks, [(
            "Theoretical floor", f"{result.lower_bound_risk:.2%}",
            f"lowest possible risk if the {constraints.min_weight:.1%} minimum and the "
            "minimum-stock rules didn't exist. The true best portfolio under all the rules lies "
            "between this and the optimized risk; a small gap means the result is essentially "
            "optimal.",
        )])

    elif choice in ("Max Return", "Max Dividend"):
        label = "expected return" if choice == "Max Return" else "dividend yield"
        if choice == "Max Dividend":
            render_dividend_flags()
        render_holdings(result, side_by_side=True)
        render_checks(
            result.checks,
            [(
                f"Exact optimum {label}", f"{result.exact_value:.2%}",
                "worked out directly: hold the top stocks, give each the 2.5% floor, then fill the "
                "best ones up to the 30% cap. The optimizer must match it.",
            )],
            notes=[
                f"Why so concentrated: maximizing {label} is a linear goal, so the optimizer fills "
                f"the best stocks up to the {constraints.max_weight:.0%} cap; the minimum-stock rule "
                f"brings in further stocks at the {constraints.min_weight:.1%} floor, and one stock "
                "takes whatever is left over. This concentration is expected, not a bug."
            ],
        )

    else:  # Max Sharpe
        left, right = st.columns([1, 1.2])
        with left:
            render_holdings(result, side_by_side=False)
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
        st.caption(
            f"Risk-free rate {risk_free_rate:.3%}: "
            + ("your override. " if rf_overridden else f"the {rf_info.name}"
               + (" (fallback value). " if rf_info.is_fallback else ". "))
            + (flag(f"⚠️ The included stocks are priced in {', '.join(currencies)}; this single "
               f"{market} rate is applied to all of them.") + " " if len(currencies) > 1 else "")
            + "Expected returns are price-only (dividends excluded), which understates Sharpe "
            "ratios for dividend payers."
        )
        checks = list(result.checks)
        if frontier is not None:
            checks.append(frontier_check(frontier, result.risk, result.expected_return))
        render_checks(checks, [(
            "Theoretical ceiling",
            f"{result.ceiling_sharpe:.3f}" if result.ceiling_sharpe is not None else "n/a",
            f"highest possible Sharpe ratio if the {constraints.min_weight:.1%} minimum and the "
            "minimum-stock rules didn't exist (solved exactly). The true best portfolio under "
            "all the rules lies between the optimized Sharpe and this.",
        )])

# ---- Under the hood (collapsed) -----------------------------------------------------------------
st.header("Under the hood")
with st.expander("Data, returns & risk, matrices and sanity checks", expanded=False):
    t_data, t_raw, t_returns, t_matrices = st.tabs(
        ["Stocks & data", "Raw prices", "Returns & risk", "Covariance & correlation"]
    )

    with t_data:
        st.markdown(f"**✅ Included ({len(ok)})**")
        included_df = pd.DataFrame(
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
        )
        st.dataframe(flag_cells(included_df, ["Match"]), width="stretch", hide_index=True, height=fit_height(len(included_df)))
        if skipped:
            st.markdown(f"**⏭️ Skipped ({len(skipped)})**")
            st.dataframe(pd.DataFrame(skipped, columns=["Input", "Reason"]), width="stretch",
                         hide_index=True, height=fit_height(len(skipped)))
        if failed:
            st.markdown(f"**❌ Failed to fetch ({len(failed)})**")
            st.dataframe(
                pd.DataFrame([
                    {"Input": r.input_ticker, "Ticker": r.yahoo_symbol, "Company": r.company_name,
                     "Exchange": r.exchange, "Error": r.error}
                    for r in failed
                ]),
                width="stretch", hide_index=True, height=fit_height(len(failed)),
            )
        if res.dropped_in_progress:
            st.caption(
                f"Market still open for {', '.join(res.dropped_in_progress)}: today's price isn't "
                "final, so the previous close is used."
            )

    with t_raw:
        pick_raw = st.selectbox(
            "Stock", [r.yahoo_symbol for r in ok],
            format_func=lambda s: f"{s} · {by_symbol[s].company_name}",
        )
        td = by_symbol[pick_raw]
        for w in td.warnings:
            st.warning(w)
        cols = st.columns(7)
        cols[0].metric("Last price", fmt_price(td),
                       help=f"Latest close as of {td.last_price_date:%Y-%m-%d}. If the market "
                       "is open this is the current (≈15-min delayed) price.")
        cols[1].metric("Currency", td.currency or "?")
        cols[2].metric("First date", f"{td.prices.index[0]:%Y-%m-%d}")
        cols[3].metric("Last date", f"{td.prices.index[-1]:%Y-%m-%d}")
        cols[4].metric("Rows", f"{len(td.prices):,}")
        cols[5].metric("Missing values", int(td.prices.isna().sum().sum()))
        cols[6].metric(
            "TTM dividend yield", fmt_yield(td),
            help=(
                "Dividends paid in the last 365 days ÷ latest close. "
                f"Dividends paid: {td.ttm_dividends_paid:.4f} {td.currency or ''}"
                if td.ttm_dividends_paid is not None else "Dividend data unavailable."
            ),
        )
        st.dataframe(td.prices, width="stretch", height=350)

    with t_returns:
        st.caption(
            "Daily simple returns on **Close** (price only, excluding dividends). Dates are "
            "aligned across exchanges; on a day an exchange was closed, its stocks carry their "
            "last close. Each stock uses all the history it has (up to 5 years). Annualized "
            f"using **{res.periods_per_year:.0f}** aligned trading days per year."
        )
        if len({r.exchange for r in ok}) > 1:
            st.caption(
                "Note: with daily returns, correlations between stocks on *different* exchanges "
                "are understated, because the exchanges close at different times of day."
            )
        summary_rows = []
        for symbol, s in res.stocks.items():
            td = by_symbol[symbol]
            summary_rows.append({
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
            })
        pct = st.column_config.NumberColumn(format="%.1f%%")
        st.dataframe(
            flag_cells(pd.DataFrame(summary_rows), ["Match", "Flags"]),
            width="stretch",
            hide_index=True,
            height=fit_height(len(summary_rows)),
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
        st.markdown("**Data sanity checks**")
        for c in res.checks:
            st.markdown(f"{'✅' if c.passed else '❌'} {c.name} · _{c.detail}_")
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

    with t_matrices:
        st.markdown("**Covariance matrix (Σ, annualized)**")
        st.dataframe(res.cov.style.format("{:.4f}"), width="stretch", height=fit_height(len(res.cov)))
        st.markdown("**Correlation matrix**")
        n = len(res.corr)
        fig = px.imshow(res.corr, text_auto=".2f", zmin=-1, zmax=1,
                        color_continuous_scale=CORR_SCALE, aspect="auto")
        fig.update_layout(height=max(300, 45 * n + 120), margin=dict(l=0, r=0, t=10, b=0), **TRANSPARENT)
        st.plotly_chart(fig, width="stretch", key="corr_full")
        st.dataframe(res.corr.style.format("{:.3f}"), width="stretch", height=fit_height(n))

# Starting over clears everything, so it asks first, like the market-switch and example
# confirmations (user decision 2026-10-08)
if ss.get("pending_reset"):
    st.warning(
        "Start a new analysis? This clears everything in this session: the market, the stocks "
        "you entered, all results and your settings."
    )
    b1, b2, _ = st.columns([1.3, 1.3, 3])
    b1.button("Start over and clear", type="primary", on_click=start_new_analysis)
    b2.button("Cancel, keep my results", on_click=lambda: ss.pop("pending_reset", None))
else:
    st.button("Start a new analysis", icon=":material/restart_alt:",
              on_click=lambda: ss.update(pending_reset=True),
              help="Clears the market, your stocks, all results and the settings, and starts "
              "again from the top. Asks you to confirm first.")
render_methodology()
render_footer()
