# UI Redesign: Context and Plan (handoff)

**For a Claude / Claude Code session picking up this work.** Read this file, then `PROJECT_SPEC.md` (what the product is) and `CLAUDE.md` (build history, every decision and why) before doing anything. If this file and `PROJECT_SPEC.md` ever disagree, the spec wins; if this file and `CLAUDE.md` disagree on UI matters, this file is newer (written 2026-10-08).

---

## 1. The project in one paragraph

Virtual Portfolio Builder is a Streamlit web app (Python) that turns a user's list of stocks into optimized virtual portfolios using Modern Portfolio Theory. No login, no trading. The user picks **one market per session** (India NSE, Australia ASX or USA), enters 10+ stocks by ticker or company name, confirms the matches, and the app fetches 5 years of daily prices from Yahoo Finance (yfinance), computes returns/risk/covariance, and builds **four V1 (Markowitz) portfolios**: Min Risk, Max Return, Max Dividend and Max Sharpe, plus an efficient frontier. V2 (Risk Parity) and V3 (Black-Litterman) are planned later. Live app on Streamlit Community Cloud; repo `rahulpalit07/virtual-portfolio-builder`, branch `main`. Owner: Rahul Palit.

## 2. Where things stand (2026-10-08)

- Latest pushed commit: `b74f80f` "One market per session; 10-year government bond yield as risk-free rate". Working tree clean apart from this file.
- V1 is functionally complete and tested (see `CLAUDE.md` Status). All calculations are verified (brute-force optimum checks, exact closed-form checks, theoretical bounds).
- Files:
  - `app.py`: Streamlit UI only (~960 lines). **This redesign changes this file** (plus a new theme file).
  - `data.py` (resolution + fetching), `stats.py` (returns, μ, σ, covariance), `optimizer.py` (constraints + four portfolios), `frontier.py` (efficient frontier), `rates.py` (risk-free rate = market's 10-year bond yield from CNBC, fallback in `fallback_rates.json`). **Do not change these** (see hard rules).
  - `PROJECT_SPEC.md`: authoritative spec. **Do not modify.**
  - `CLAUDE.md`: master progress document. Keep it comprehensive (never shorten it); update it at the end with the UI decisions.
- Current page order (the problem): Market → 1. Enter stocks → 2. Confirm matches → 3. Data → 4. Returns & risk → 5. Portfolios. The answer (the portfolios) appears last, below ~4 screens of data tables.

## 3. Goal of this work

Redesign the **presentation layer only** for two audiences:
1. A first-time user who wants a portfolio from their stocks.
2. A recruiter who will spend about one minute on it.

## 4. HARD RULES (non-negotiable)

1. **Do not change any calculation, optimizer, constraint, data fetch or result.** Every number the app produces must be identical before and after.
2. **Do not modify `PROJECT_SPEC.md`.**
3. `data.py`, `stats.py`, `optimizer.py`, `frontier.py`, `rates.py`, `fallback_rates.json` must show **zero diff** after every pass. All work happens in `app.py` and new presentation files (e.g. `.streamlit/config.toml`).
4. Respect the spec's existing rules, which the UI must still honour:
   - **One market per session; the user explicitly chooses it; nothing pre-selected** (spec 2.6). Switching market asks for confirmation and clears the session (already built; keep it).
   - **Out-of-market stocks are flagged and start unticked**; the user can include them (spec 2.6).
   - **The risk-free rate shown must include its value, source and as-of date, and a fallback must be stated explicitly** (spec 3.4). The fallback notice must stay prominent; it must not be hidden only in the sidebar.
5. No new packages (everything needed is already in `requirements.txt`: streamlit, plotly, pandas, jinja2…). If something seems to need a new package, stop and ask.
6. Work in passes; **stop after each pass** for the user's review; **commit locally after each pass, do not push**.

## 5. Decisions already made by the user (do not reopen)

| # | Decision |
|---|---|
| Flow | "1. Your stocks" → "2. Your portfolios" → collapsed "Under the hood". |
| Header | Replace the subtitle "V1 · Data, returns, risk, covariance and four optimized portfolios" with a plain-English one-liner. |
| Examples | **One example per market** (the cross-market example from the original brief is not allowed by the spec). Clicking an example is an explicit market choice and goes **in one click straight to results** (fill → find → build). Lists below. |
| Selector | **Segmented control** (`st.segmented_control`, available in Streamlit 1.65) instead of tabs or dropdown. Reason: tabs render all four views (and their charts) on every rerun and charts in hidden tabs can mis-size; the segmented control renders only the selected view. |
| Parallel fetching | **Yes**, done in `app.py` with threads (4–6 workers) calling the existing `data.resolve` / `data.fetch_ticker_data` functions; `data.py` unchanged. Tested 2026-10-08: ~5× faster (resolve ~7 s → ~2 s, fetch ~7–9 s → ~1–3 s for 11 stocks). Close, Dividends and dividend yield were identical to sequential fetches in 3 runs; only Yahoo's **Adj Close** column differs by ≤ 7e-7 relative in parallel (a yfinance quirk). Adj Close is **not used in any calculation** (returns use Close), so all app numbers stay identical; only the raw price tables under the hood may differ in the 7th significant digit. |
| Freeze stats | **No.** Keep current behaviour (stats recompute on rerun; if a market closes between reruns, today's price becomes final and numbers can shift slightly). |
| Theme | ~~Teal~~ **Light green** primary colour (`#4CAF50`, user decision 2026-10-08, replaces teal) via `.streamlit/config.toml`; red reserved for errors; **flags yellow**. Plain-English labels in the main view; Greek symbols (μ, σ, Σ) only under the hood. ~~The correlation heatmap keeps its red–blue scale~~ Superseded 2026-10-08: the heatmaps use purple (−1) → white → green (+1) (`PRGn`), since red now means errors only. |
| Sidebar | Holds settings (minimum stocks held, risk-free rate + its source/as-of line). Appears **only after a market is chosen**. |
| Footer | "Educational tool, not financial advice · Rahul Palit · LinkedIn (https://www.linkedin.com/in/rahul-palit/)". GitHub: use the repo URL `https://github.com/rahulpalit07/virtual-portfolio-builder` unless the user says otherwise (not yet confirmed). |
| Regression lists | The three example lists double as the fixed regression lists. |
| Stock input (2026-10-08, amendment 2) | A **text box** (`st.text_area`, ~120 px) replaces the one-column data editor, so a list can be pasted in one go. Split on **commas, semicolons, tabs and new lines, not spaces** (company names such as "Commonwealth Bank" contain spaces); entries trimmed, blanks dropped, order kept. Exact repeats are dropped before lookup (as the table did); other duplicates are handled in the matches step (first input wins). Kept: the versioned key `input_{n}`, pre-fill via `input_seed` (examples fill it as a comma-separated list), and the form, now without its border. |
| Section 1 layout (amendment 2) | Market radio and "No list handy? Try an example" + three compact buttons on **one row**; below it the text box (~60% width) with the one-sentence instruction and "Find stocks" beside it. |
| Section 1 after build (amendment 2) | Once portfolios are built, "1. Your stocks" **collapses to one line** naming the market and stock count (e.g. "1. Your stocks · Australia (ASX) · 11 stocks · click to edit"; skipped / failed-to-fetch counts added when non-zero), so the results start near the top; opening it shows the full section for editing. It stays **open** whenever the user needs to act or see something there: before results exist; a market-switch or load-example confirmation is pending; any match needs attention (unmatched, auto-picked, switched listing, out-of-market flag, duplicate): **opened once** when such a match first appears or on a build with one, after which the user can collapse it (user decision 2026-10-08, since such rows often stay unchanged and would otherwise keep it open permanently); the selections changed since the last build. One-click examples land on results with it collapsed. Results-area notices (fallback rate, failed checks, repair, mixed currency) are unaffected. |

### Example lists (verified 2026-10-08: all resolve as exact tickers, no out-of-market flags, all 11 pay dividends so Max Dividend always works)

| Market | Stocks |
|---|---|
| India (NSE) | RELIANCE, TCS, HDFCBANK, INFY, ICICIBANK, ITC, HINDUNILVR, BHARTIARTL, LT, SBIN, ASIANPAINT |
| Australia (ASX) | BHP, CBA, CSL, NAB, WBC, ANZ, WES, WOW, TLS, RIO, MQG |
| USA | AAPL, MSFT, JNJ, KO, PG, JPM, XOM, WMT, PEP, MRK, HD |

## 6. Target design

### 6.1 Tiers for every element
🟢 always visible · 🟡 one click away (expander / tooltip / sidebar) · ⚪ hidden unless something goes wrong.

| Element (current) | Tier | New presentation |
|---|---|---|
| Title + subtitle | 🟢 | Title + plain-English one-liner |
| Market radio | 🟢 | Top of "1. Your stocks", **on the same row as** the "Try an example" buttons (one per market) (amendment 2) |
| Market-switch confirmation | 🟢 when triggered | Unchanged |
| Input table + Resolve | 🟢 | ~~Same~~ **Text box** (paste many stocks; split on commas, semicolons, tabs, new lines) with the instruction and "Find stocks" beside it (amendment 2); buttons "Find stocks" and "Build portfolios" |
| *(new, amendment 2)* "1. Your stocks" after build | 🟡 | Collapsed to one line (market · stock count · click to edit); 🟢 open before results, during confirmations, once when a match needs attention (then collapsible), or when the selections changed since the last build |
| Confirm-matches rows | 🟡/🟢 | Expander "✅ N stocks matched"; **auto-expands** if any row is auto-picked, unmatched, out-of-market-flagged, switched listing, or duplicate |
| Auto-picked warning | 🟢 once | Prominent in the confirm step only; results show a small icon with a tooltip (column help) |
| "< 10 stocks" warning, "Will skip…" | 🟢 | One line under "Build portfolios" |
| "Based on N stocks" | 🟢 | Summary line, e.g. "11 stocks · 5 years of daily prices · to 7 Oct 2026" (+ skipped/failed counts if non-zero) |
| Included / Skipped / Failed tables, raw data per stock | 🟡 | Under the hood |
| Returns-method caption, portfolio rules caption, price-only caveat | 🟡 | "Methodology & limitations" expander |
| Mixed-currency / cross-exchange warnings | ⚪ | Only appear if the user includes an out-of-market stock (only possible via override now) |
| "Market still open" note | 🟡 | Under the hood |
| Returns & risk table (μ, σ, CAGR…) | 🟡 | Under the hood |
| Data sanity checks | ⚪ | Under the hood; **red banner at top of results if any fail** |
| Data-quality flags (short history, extremes, near-duplicates) | 🟡/🟢 | **One visible summary line**; details under the hood (they shape results, so not fully hidden) |
| Covariance matrix, correlation heatmap/table | 🟡 | Under the hood (correlation also stays as the Min Risk side panel) |
| Minimum stocks, risk-free rate inputs | 🟡 | Sidebar (keep the same widget keys so values aren't reset) |
| Risk-free source / as-of line | 🟢/🟡 | Sidebar + caption on the Max Sharpe view |
| **Fallback-rate warning** | 🟢 when it occurs | Prominent in results (spec requirement) |
| Rate-overridden notice, covariance-repair note, swap time-limit note | 🟢 when they occur | Visible notices near results |
| Comparison table | 🟢 | Top of results; drop the Note column; **highlight best per column** (max return/yield/Sharpe, min risk); keep "Equal weight (reference)" row; full height, no internal scrolling |
| Portfolio dropdown | 🟢 | Segmented control |
| Holdings table | 🟢 | Horizontal **bar chart** of weights (Plotly) + compact table (ticker, company, weight; Match as an icon column with tooltip) |
| "Not held (0%)" list | 🟢 | Small caption |
| Headline figures | 🟢 | Four metric cards: Expected return, Risk, Dividend yield, Sharpe ratio, with **"vs equal weight" deltas** (replacing the separate equal-weight figures) |
| Theoretical floor / Sharpe ceiling / exact optimum | 🟡 | Inside the checks expander |
| "Why this portfolio" | 🟢 | One plain-English line per portfolio |
| Dividend data flags | 🟢/🟡 | Max Dividend view: missing/implausible as warnings, non-payers as a caption |
| Side panels | 🟢 | **Unchanged**: Min Risk → correlation matrix; Max Sharpe → efficient frontier; Max Return / Max Dividend → none (full width) |
| Verification checks | 🟡 | One line "✅ All N checks passed" that expands; a red banner if any fail |
| *(new)* Methodology & limitations | 🟡 | Expander: data source & 5-year window; daily simple returns; price-only (dividends excluded); 30% cap, 2.5% floor, minimum stocks; risk-free rate = market 10-year yield (CNBC, fallback file); one market per session so one currency (no conversion; an included out-of-market stock keeps its own currency) |
| *(new)* Footer | 🟢 | See decisions table |

### 6.2 Wireframe (top to bottom)

```
SIDEBAR (only after a market is chosen)  │ MAIN
 Settings                                │ Virtual Portfolio Builder
  Minimum stocks held   [ 4 ]            │ <plain-English one-liner>
  Risk-free rate %      [ … ]            │
  ⓘ <market> 10-yr yield, CNBC,          │ ── 1. Your stocks ───────────────────────
    as of <time> (live/fallback)         │ Market: ( ) India (NSE) ( ) Australia (ASX) ( ) USA
 Methodology & limitations ▸             │ No list handy? [Try India example] [Try ASX] [Try US]
                                         │ [input table]                   [Find stocks]
                                         │ ▸ ✅ 11 stocks matched   (auto-opens on any ⚠️)
                                         │ [Build portfolios]  11 stocks · 5 y daily · to <date>
                                         │
                                         │ ── 2. Your portfolios ───────────────────
                                         │ (red banner only if a check fails; fallback /
                                         │  repair notices if any)
                                         │ Comparison table (best per column highlighted)
                                         │ [ Min Risk | Max Return | Max Dividend | Max Sharpe ]
                                         │ "Why this portfolio" line
                                         │ [Return] [Risk] [Yield] [Sharpe]  (Δ vs equal weight)
                                         │ ┌ weights bar chart + table ┬ side panel (per rules) ┐
                                         │ ▸ ✅ All N checks passed (incl. floor/ceiling/exact)
                                         │
                                         │ ── Under the hood ▸ (collapsed) ─────────
                                         │   data coverage · raw prices · returns & risk ·
                                         │   flags · sanity checks · covariance · correlation
                                         │ ▸ Methodology & limitations
                                         │ Footer
```

### 6.3 Ready for V2 and V3 without another redesign
Drive the results area from a **portfolio registry** in `app.py`: a list of entries, each with name, cached compute function, "why" line, extra figures, side-panel renderer. The comparison table, segmented control and views are generated from it. V2 (Risk Parity) = one more entry (side panel: per-stock risk contributions, per spec 4.4). V3 (Black-Litterman) = one more entry plus a "Your views" input panel inside its own view. The segmented control fits ~6 options.

## 7. Technical notes and pitfalls

- **State:** results live in `st.session_state` (`resolutions`, `fetched`); portfolios and frontier are `st.cache_data`-cached on their exact inputs, so sidebar changes recompute only portfolios and never re-fetch. Keep existing widget keys when moving widgets (e.g. the risk-free input key `rf_{market}_{value}`, `inc_*`, `pick_*`, `market_radio_{n}`, `input_{n}`), or settings/choices reset.
- **Example buttons:** fill the input table by bumping `ss.input_version` (the existing mechanism that recreates the data editor), set `ss.market` (and bump `ss.market_version` so the radio shows it), then run find + build automatically.
- **Parallel fetching:** run the plain `data.resolve` / `data.fetch_ticker_data` in a `ThreadPoolExecutor(max_workers≈6)` inside `app.py`; don't call Streamlit functions from worker threads; keep results in session state as today. Keep the one-per-stock currency lookup (`listing_currency`) cached; it can also be parallelized.
- **Tables:** set explicit heights (rows × ~35 px + header) so nothing scrolls internally or clips the first/last row.
- **Highlighting:** pandas Styler (jinja2 already listed) on `st.dataframe`.
- **Streamlit quirks seen in this project:** the dev server doesn't reliably hot-reload imported modules (restart it after editing them); the in-app browser pane is sometimes hidden, so screenshots/clicks fail: use Streamlit's `AppTest` (`streamlit.testing.v1`) to drive the real app instead; the data editor can't be typed into via `AppTest`, so set `session_state["resolutions"]` (or use the example buttons). On Windows, run Python with `PYTHONIOENCODING=utf-8` when printing symbols. Run `pyflakes` on `app.py` before testing (it caught a real name-clash bug before).

## 8. Regression check (run before Pass 1 and after every pass)

1. **Baseline, before any change:** for each of the three example lists, fetch the data once and **snapshot it to files** (pickled `TickerData` per stock + the risk-free rate per market) in a scratch folder outside the repo.
2. A harness drives `app.py` with `AppTest`, replacing the fetch and rate lookups with the snapshots, so old and new code see identical inputs (live prices and yields move during the day).
3. Record, per market: all four portfolios' **full weight vectors**, expected return, risk, dividend yield, Sharpe, the equal-weight row, the Sharpe ceiling, the risk floor, and the number of frontier points. Read numeric values, not formatted text.
4. After each pass: compare to the baseline at full precision (must be identical); confirm `git diff` shows **zero changes** to `data.py`, `stats.py`, `optimizer.py`, `frontier.py`, `rates.py`, `fallback_rates.json`, `PROJECT_SPEC.md`; run `pyflakes`.
5. Report the result to the user, commit locally (no push), stop.

## 9. Build plan (stop after each pass)

- **Pass 0: baseline.** Snapshot data and record the regression baseline from the *current* code (commit `b74f80f`). No app changes.
- **Pass 1: layout and flow.** New section order and tiers; collapsed confirm step with auto-expand rules; "Under the hood" expander; sidebar settings; segmented control; example buttons (one-click to results); parallel resolve/fetch; Methodology & limitations; footer; checks collapsed to one line (floor/ceiling/exact inside); fallback and failure notices kept prominent; table heights fixed. → Regression check, commit locally, stop for review.
- **Pass 2: charts and metric cards.** Weights bar chart + compact table; metric cards with "vs equal weight" deltas; comparison table highlighting; "why this portfolio" lines; Match icons with tooltips. → Regression check, commit locally, stop.
- **Pass 3: theme and polish.** `.streamlit/config.toml` with teal primary; plain-English labels (Greek only under the hood); wording and spacing polish. → Regression check, commit locally, stop.
- **Finish:** update `CLAUDE.md` with all UI decisions (add, don't shorten), commit locally. **Push only when the user asks.**

## 10. Open item to confirm with the user
- GitHub link in the footer: repo URL above, or leave it out. (Pass 1 uses the repo URL; not yet confirmed.)

## 11. Progress log

- **Pass 0 (baseline): DONE 2026-10-08.** Snapshot of the three example lists (taken 2026-10-07 22:51 UTC: India 10Y 7.241%, Australia 5.389%, USA 5.286%, all live) and baseline recorded from commit `b74f80f`. Baseline is deterministic (two runs identical). Tooling now lives in `tests/regression/` (see its README); data files are git-ignored, local only.
- **Pass 1 (layout and flow): DONE 2026-10-08**, committed locally as `76f9038` (not pushed). Regression: **78/78 recorded results identical**; protected files unchanged; pyflakes clean. Functional UI tests pass (`tests/regression/ui_test.py`, `ui_test2.py`). Live one-click examples reach results in 6.5–8 s.
  - What Pass 1 built: header one-liner; "1. Your stocks" (market radio + "Try an example" buttons, one per market, one click to results, confirmation before clearing work); input table; "Find stocks"; matches in an expander (auto-opens if any row is unmatched, auto-picked, switched, flagged or duplicate); auto-pick warning once above "Build portfolios (N stocks…)"; summary line; sidebar "Settings" (min stocks key `min_stocks`, risk-free rate key `rf_{market}_{value}`, source/as-of line, fallback warning, override notice); "2. Your portfolios" (failed-check / fallback / repair / mixed-currency / data-flag one-line notices; comparison table without empty Status column; `st.segmented_control` key `portfolio_view`; the four views with unchanged side panels; checks collapsed to "✅ All N checks passed" with floor / exact optimum / Sharpe ceiling inside); "Under the hood" expander with tabs (Stocks & data, Raw prices with a stock picker, Returns & risk incl. data sanity checks and flags, Covariance & correlation); Methodology & limitations expander; footer (Rahul Palit, LinkedIn, GitHub repo). Parallel resolve/currency/fetch via `ThreadPoolExecutor(6)` in `app.py` (`cached_resolve_all`, `cached_fetch_all`); `data.py` unchanged.
  - Fixed during Pass 1: the one-line data-flag summary shortened flag text badly ("only 2"); replaced by `short_flag()` labels.
  - Known: equal-weight figures are still separate metrics (become card deltas in Pass 2); auto-pick note still also appears as a caption in portfolio views (becomes an icon + tooltip in Pass 2); Plotly/primary colours still default red (Pass 3).
- **Pass 1 amendment (colours): DONE 2026-10-08** (user request after Pass 1 review). Light green replaces teal and is applied now rather than in Pass 3:
  - `.streamlit/config.toml` (new): `primaryColor = "#4CAF50"` (all buttons, radio buttons, segmented control, checkboxes, focus outlines) and `chartCategoricalColors` without red.
  - `app.py`: frontier line green; markers Min Risk blue `#1E88E5`, Max Return purple `#8E24AA`, Max Sharpe dark green `#2E7D32` (Plotly's default trace colours included red); both correlation heatmaps `RdBu` → `PRGn`.
  - Flags yellow: `flag()` wraps flag text in `:yellow[…]` (matches expander label when something needs attention; out-of-market, switched-listing, auto-picked and no-match statuses, the no-match one changed from ❌ to ⚠️ since it's a flag, not an error; failed-to-fetch in the summary line; "holds stocks outside the market" caption; mixed-currency note in Max Sharpe). `flag_cells()` shades ⚠️ cells yellow in the Match / Flags table columns (holdings, Included, Returns & risk). High-yield dividend notice `st.info` → `st.warning` (yellow). Notices that are not flags (rate overridden, covariance repair, "choose a market") stay blue.
  - Red kept only for errors: `st.error` banners, ❌ failed checks / failed to fetch; the comparison table's "failed a check" status changed from ⚠️ to ❌.
  - Verified: regression 78/78 identical, no exceptions; protected files zero diff; pyflakes clean; `ui_test.py` and `ui_test2.py` pass; checked in the browser (green buttons/radio/segmented control, purple–green heatmap, green frontier).
  - Pass 3 therefore no longer needs to add the theme file; it keeps the plain-English labels and wording/spacing polish.
- **Pass 1 amendment 2 (input and space): DONE 2026-10-08** (user request; approved, including the new section-1 behaviour after build). Goal: section 1 from about a full screen to about a quarter, pasting many stocks at once, "2. Your portfolios" near the top.
  - Input: `st.text_area` (120 px, label hidden, placeholder with the market's examples) in a borderless form, two columns (text box 3 : 2 instruction + "Find stocks"). `parse_stocks()` splits on `[,;	

]+`. `has_progress()` now reads the text box. Examples fill it via `input_seed` (comma-separated).
  - Market radio (label shortened to "Market for this session (all stocks must come from it)") and the example buttons share one row (`st.columns` + a horizontal container; buttons `width="content"`, so the market names are no longer truncated).
  - Collapsing: section 1 is a **stateful expander** (`key="section1_open"`, `on_change="rerun"`) once results exist, and a plain header + container before that. Widgets inside a closed expander still run, so the market, text box, `pick_*` and `inc_*` keep their state. Its open state is re-asserted in session state every run, because the expander's label is part of its identity in Streamlit (the label gains/loses "click to edit"). Building sets a flag and reruns so the section collapses; `ensure_section1_open()` sets a flag and reruns when a confirmation is pending, a match needs attention or the build is stale. Early exits inside the section raise `StopSection`, caught outside so methodology and footer render outside the expander. The summary line ("11 stocks · up to 5 years… · to <date>") moved to the end of section 1. Streamlit 1.65 allows the nested matches expander.
  - Measured in the browser at 1366×768: before results, section 1 runs from its header at 252 px to the bottom of "Find stocks" at 572 px (~320 px incl. header); after a one-click example, "2. Your portfolios" starts at 308 px and the comparison table (445–658 px) is fully on the first screen.
  - Verified: regression 78/78 identical, no exceptions; protected files zero diff; pyflakes clean; `ui_test.py` (labels updated to tell section 1 and the matches expander apart), `ui_test2.py` pass; new `ui_test3.py` 28/28 (parsing incl. mixed separators, blanks and names with spaces; each example → results in one click, collapsed, market named; typing + Find + Build; picks and Include survive collapse/reopen; auto-picked / unmatched rows force it open; stale build keeps it open; both confirmations with Cancel keeping everything; typed text counts as progress).
  - Different from the brief: none in behaviour. Notes: the text box is inside a form, so text typed but not yet submitted isn't seen by the app (same as the old table); the confirmations fire once the list has been submitted with "Find stocks".
  - Follow-up (user decision, same day): a match needing attention now opens section 1 **once** (when the set of such matches changes, or on a build that still has one) instead of keeping it open permanently; the user can then collapse it. Pending confirmations and a stale build still always force it open. `ui_test3.py` 29/29 (added: collapse stays collapsed while an auto-pick is unchanged); regression 78/78; pyflakes clean; protected files zero diff. Pushed to `main` with amendments 1 and 2.
- **Pass 2 (charts and metric cards): NEXT.** Weights horizontal bar chart (Plotly) + compact table; four metric cards with "vs equal weight" deltas (replace the separate equal-weight metrics and the Min Risk "risk reduction" metric); comparison table best-per-column highlighting (Styler; max return/yield/Sharpe, min risk; exclude the equal-weight reference row from "best"); one-line plain-English "why this portfolio" per view; Match shown as an icon column with tooltip (column help) instead of repeated captions.
- **Pass 3 (theme and polish): TODO.** ~~`.streamlit/config.toml` teal primary~~ (done early in light green, see Pass 1 amendment); plain-English labels in the main view (Greek symbols only under the hood); wording/spacing polish.
- **Finish: TODO.** Update `CLAUDE.md` with all UI decisions (add, never shorten); commit locally; push only when the user asks.
