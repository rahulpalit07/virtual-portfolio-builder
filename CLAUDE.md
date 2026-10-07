# CLAUDE.md: Build Progress

Read `PROJECT_SPEC.md` first; it defines *what* the product is. This file is the master record of *where the build is*: what's built, what was tested, every decision made (and why), known limitations and what's next. Keep it comprehensive; update it at the end of every step.

## Run it
```bash
python -m venv .venv
.venv/Scripts/python -m pip install streamlit yfinance pandas plotly scipy
.venv/Scripts/python -m streamlit run app.py
```
(Only the packages needed so far are installed locally; `numpy` and `jinja2` come in as dependencies. `PyPortfolioOpt` and `riskparityportfolio` in `requirements.txt` are for later steps.)
Note: Streamlit does not hot-reload `data.py`/`stats.py`/`optimizer.py`/`frontier.py` reliably. Restart the server after editing them.

## File structure
- `app.py`: Streamlit UI (input → resolve/confirm → fetch → display → returns & risk → portfolios: comparison table + dropdown for Min Risk / Max Return / Max Dividend / Max Sharpe). Only calls functions and displays results; no calculations. Holds the `st.cache_data` wrappers for each portfolio and the frontier (`cached_min_risk`, `cached_max_return`, `cached_max_dividend`, `cached_max_sharpe`, `cached_frontier`).
- `data.py`: ticker/name resolution + data fetching (yfinance). No Streamlit imports. Key functions: `to_yahoo_symbol`, `resolve`, `fetch_ticker_data`.
  - 2026-10-07 (one market per session): `MARKET_CURRENCY`, `KNOWN_SUFFIXES` (other exchanges' Yahoo suffixes), `foreign_suffix(ticker, market)`, `out_of_market_reasons(candidate, market, currency)` (exchange / ticker-suffix / currency checks), `listing_currency(symbol)`, `market_of_exchange(code)`. `Candidate.exchange_code`; `Resolution.entered` / `.switched` (another market's ticker was typed and the same company's listing on the selected market is offered instead).
- `stats.py`: daily returns, annualized μ and σ, covariance, correlation, sanity checks and flags. Pure calculations, no Streamlit. Key functions: `completed_closes` (drops today's bar if the exchange is still open), `compute_stats` (returns a `StatsResult`).
- `optimizer.py`: portfolio optimization (scipy). Pure calculations, no Streamlit. Contents:
  - **Constraint parameters, the single place to change them:** `MAX_WEIGHT = 0.30`, `MIN_WEIGHT = 0.025`, `MIN_STOCKS = 4`, wrapped in the `Constraints` dataclass (with derived `stocks_needed_for_cap` = 4, `max_stocks_for_floor` = 40, `min_held`).
  - `optimize(objective, tickers, constraints)`: **generic** constraint handling (feasibility check, lower bound, drop-and-re-solve, swap improvement, verification). Later portfolios only supply a new `Objective` (function + gradient). **Sign convention: it always minimizes**; maximizing portfolios pass a negated objective and negate `objective_value` / `lower_bound` back for display (documented in `Objective`).
  - `prepare_covariance(cov)` → `PreparedCovariance(cov, repaired, note)`: **shared step, run once** before any portfolio; repairs Σ if it isn't positive semi-definite. Every optimizer and every displayed portfolio figure must use `prepared.cov`.
  - `min_risk_portfolio(cov, tickers, constraints)` → `MinRiskResult` (weights, risk, lower-bound risk, equal-weight risk, checks, notes). Expects the prepared matrix.
  - Helpers: `feasibility_error`, `verify_constraints`, `nearest_psd`, `portfolio_stats` (weighted return, risk, weighted yield, and Sharpe if a risk-free rate is passed), `sharpe_ratio`, `equal_weights`, `equal_weight_is_valid`.
  - `app.py` builds per-run constraints with `dataclasses.replace(Constraints(), min_stocks=...)`, so any rule added to `Constraints` later is carried over automatically.
  - Step 4 additions: `RISK_FREE_RATE = 0.04` (named default); `optimize(..., extra=[...], swaps=True)` accepts extra constraints (e.g. a target return for the frontier) and can skip the swap step; `SWAP_TIME_LIMIT = 5.0` s caps the swap step (a note is shown if hit); `max_return_portfolio(mu, constraints)` and `max_dividend_portfolio(yields, constraints)` → `LinearResult` (value, equal-weight value, exact value); `exact_linear_optimum(values, constraints)` (closed-form answer for linear goals, used to verify); `dividend_data_flags(yields)` → `DividendFlags` (thresholds `HIGH_YIELD = 0.08`, `IMPLAUSIBLE_YIELD = 0.15`); `max_sharpe_portfolio(cov, mu, risk_free_rate, constraints, compare)` → `MaxSharpeResult` (Sharpe, return, risk, ceiling, equal-weight Sharpe); `sharpe_ceiling(...)` (exact best Sharpe without the floor/count rules).
- `frontier.py`: efficient frontier under the same rules (pure calculations, no Streamlit). `efficient_frontier(cov, mu, constraints, anchors)` → `Frontier` (curve incl. the actual portfolios, swept points, points solved); `frontier_check(frontier, risk, return)` → `Check`. Settings: `FRONTIER_POINTS = 20`, `FRONTIER_TOLERANCE = 0.001` (0.1 percentage point of risk). Chose a separate file because the sweep is display/verification logic built on the optimizer; Max Sharpe doesn't depend on it, so there are no circular imports.
  - 2026-10-07: `Frontier` also keeps `anchors` (the actual portfolios as their own table). Bug fix: when two portfolios coincide (e.g. Max Sharpe = Max Return), the curve keeps only one label for that point, so `frontier_check` and the chart markers now read `anchors` instead of curve labels.
- `rates.py` (2026-10-07): risk-free rate = the selected market's 10-year government bond yield. `risk_free_rate(market)` → `RiskFreeRate` (value, name, source, as-of, is_fallback, note). Live from CNBC's quote service (`CNBC_SYMBOLS`: India `IN10Y`, Australia `AU10Y-AU`, USA `US10Y`); on any failure, the value from `fallback_rates.json`, marked as a fallback with the reason (and "may be out of date" if older than `FALLBACK_STALE_DAYS = 90`). Standard library only (`urllib`, `json`): no new packages.
- `fallback_rates.json` (2026-10-07): the fallback document (user decision): one entry per market with `yield_percent`, `as_of` and `source`, plus an `_about` note on how to update it. Values recorded from CNBC on 2026-10-07: India 7.214%, Australia 5.413%, USA 5.309%. **Update by hand** when stale and note it here.
- `requirements.txt`: what Streamlit Cloud installs (see Deployment).
- `.gitignore`: see Deployment.

## Status

### V1 (Markowitz)
- [x] **Step 1: Data pipeline.** Complete, tested and confirmed working for **NSE, ASX and USA** (2026-10-06):
  - Input by **exact ticker or company name** on any of the three exchanges, resolved via Yahoo symbol search.
  - **Confirm matches** step: dropdown of matches per input, Include checkbox per row, auto-pick flag for ambiguous names, skip/ignore unresolved rows without blocking.
  - **Historical prices**: 5 years of daily OHLCV, both Close and Adj Close, shown raw per stock.
  - **Last price** (with "as of" date) and **TTM dividend yield** per stock.
  - Clear **Included / Skipped / Failed to fetch** lists in the output.
  - Tested with: AAPL, Apple, Tesla, Alphabet, BRK.B, Ford (USA); Reliance, RELIANCE, Reliance Industries, Bharti Airtel, Tata (NSE); BHP, CBA, Commonwealth Bank, Woolworths (ASX); plus no-match (`xyzqwerty`, `xxxya`), ETF (`SPY`) and duplicate (Apple + AAPL) cases.
  - Deployed to Streamlit Cloud and confirmed matching local (2026-10-06).
- [x] **Step 2: Returns, risk, covariance and correlation** (PROJECT_SPEC.md Section 2.3). Complete, tested and confirmed working for **NSE, ASX and USA** (2026-10-06). All calculations live in `stats.py`; `app.py` displays them in section "4. Returns & risk":
  - **Periodic returns**: daily simple returns per stock (on `Close`, aligned across exchanges; see decisions).
  - **Annualized expected return (μ)** per stock: annualized mean of daily returns (raw historical mean, used directly in V1 per the spec).
  - **Annualized risk (σ)** per stock: annualized standard deviation of daily returns.
  - **Annualized covariance matrix (Σ)** across all included stocks, shown as a table (4 decimals).
  - **Correlation matrix** (not required by the spec; for sanity-checking), shown as a heatmap plus a table.
  - **Summary table** per stock: ticker, company, exchange, currency, Match flag, μ, σ, price CAGR, TTM dividend yield, history length (years), from/to dates, flag count.
  - **On-screen sanity checks** (✅/❌, with an error banner if any fail): covariance symmetric; covariance diagonal equals each stock's σ²; all correlations within [−1, 1]; every pair of stocks has overlapping history; covariance positive semi-definite (no combination of stocks has negative risk).
  - **Flags** (shown under "Flagged for you to look at"; stocks stay included): < 3 years of history; μ > +100% or < −50%; σ > 80%; > 20% of the stock's own trading days with exactly 0% return (thin trading/stale prices); any pair with correlation > 0.95 (near-duplicates, e.g. two share classes).
  - **Notices**: ⚠️ mixed-currency warning when included stocks span more than one currency; note that cross-exchange correlations are understated when stocks span exchanges; note when today's price isn't final yet for a still-open market.
  - Tested with AAPL, GOOG, GOOGL, RDDT (2.5 yrs), RELIANCE.NS, INFY.NS, SWIGGY.NS (1.9 yrs), BHP.AX, CBA.AX: all sanity checks pass; RDDT/SWIGGY flagged for short history, RDDT for σ 81%, GOOG/GOOGL flagged at correlation 0.997. Sample values: AAPL μ 20.9% σ 28.0%; RELIANCE.NS μ 2.5% σ 22.1%; BHP.AX μ 16.6% σ 26.4%.
  - Deployment check on Streamlit Cloud: pending after the step 2 push.
- [x] **Step 3: Min Risk portfolio** (Global Minimum Variance, PROJECT_SPEC.md Section 3.2). Built and tested locally (2026-10-06). Optimization in `optimizer.py`; `app.py` displays it in section "5. Min Risk portfolio":
  - **Objective:** minimize wᵀΣw using the annualized covariance matrix Σ from step 2 (not the correlation matrix: risk needs volatilities as well as correlations; agreed with user).
  - **Constraints:** weights sum to 100%; no short-selling; each stock either exactly 0% or held between 2.5% and 30%; at least 4 stocks held (default; **user-adjustable number input**, which can't go below 4 because the 30% cap needs 4 stocks to reach 100%, and can't exceed the number of included stocks or 40).
  - **Display:** portfolio table (held stocks only, sorted by weight: ticker, weight %, company, exchange, Match flag) + "Not held (0%)" list; metrics: expected return (weighted μ), risk (√wᵀΣw), dividend yield (weighted), equal-weight risk, risk reduction, theoretical floor (lower bound); correlation heatmap alongside with held stocks first by weight; mixed-currency and auto-picked notes.
  - **Verification checks on screen** (✅/❌, ➖ when not applicable, error banner if any fail): weights sum to 100%; no negative weights; no weight above 30%; no held weight below 2.5%; at least the minimum number held; optimized risk ≤ equal-weight risk (shows both).
  - **Feasibility:** clear message instead of a portfolio when the rules can't be met (e.g. "3 stock(s) available, but with a 30% cap per stock, at least 4 stocks are needed to reach 100%. Add more stocks.").
  - **Tested (scripted, against brute-force exact optimum = solving every allowed set of held stocks):** 12 mixed NSE/ASX/USA stocks (σ 8.7146%, 11 held), 12 US stocks (σ 12.0242%, 8 held), 11 volatile stocks incl. short-history RDDT/SWIGGY (σ 24.8438%, 10 held), each at min 4 and 6, plus 12 US stocks with min 9/10/11 (count rule binding): **all 9 cases match the exact optimum**, all checks pass. Edge cases: 3 stocks → feasibility message; min = all stocks → all held (smallest exactly 2.5%); min 41 → message; deliberately broken (non-PSD) Σ → repaired with a note. Speed: ~0.3 s for 20 stocks, ~1 s for 35.
  - **Tested in the browser:** AAPL, Reliance, BHP, JNJ, KO, PG → JNJ 24.29%, KO 20.96%, RELIANCE.NS 20.41%, BHP.AX 15.41%, PG 12.24%, AAPL 6.69%; σ 11.20% vs equal-weight 11.61%; expected return 9.66%; yield 2.09%; all 6 checks pass; min-stocks control works (capped at 6 = stocks available).
  - Deployment check on Streamlit Cloud: pending after the step 3 push.
- [x] **Step 4: Max Return, Max Dividend and Max Sharpe portfolios + dropdown + efficient frontier** (PROJECT_SPEC.md Sections 3.1, 3.3, 3.4). Built and tested locally (2026-10-07). Section "5. Portfolios" in `app.py`:
  - **Controls:** minimum number of stocks held (default 4, shared by all four portfolios) and risk-free rate (% per year, default 4%, used for every Sharpe ratio shown).
  - **Comparison table** (user asked for it): every portfolio plus "Equal weight (reference)": expected return, risk, dividend yield, Sharpe ratio, stocks held, note (e.g. "Not available", "⚠️ failed a check").
  - **Dropdown** ("Show portfolio"): Min Risk (default) / Max Return / Max Dividend / Max Sharpe. All four portfolios and the frontier are computed once and cached; switching is instant.
  - **Every portfolio shows:** holdings table (ticker, weight %, company, exchange, Match flag; held only, by weight), "Not held (0%)" list, expected return, risk, dividend yield, Sharpe ratio, its equal-weight comparison number, verification checks.
  - **Min Risk:** unchanged results (proved: identical weights to step 3's code on the same inputs) and unchanged layout (correlation matrix alongside), plus the Sharpe ratio; figures now shown 2 per row in the narrow left column so they aren't truncated.
  - **Max Return / Max Dividend:** no side panel. Extra figures: equal-weight value and exact optimum; caption explaining the expected 30/30/30/10-style concentration. Max Dividend also shows dividend data flags.
  - **Max Sharpe:** efficient frontier chart alongside (Plotly; x = annualized risk %, y = annualized expected return %; frontier curve, each stock as a labelled point, Min Risk ◆ at the left end, Max Return ■ at the top end, Max Sharpe ★). Extra figures: equal-weight Sharpe, theoretical ceiling. Caption that one risk-free rate is applied across INR/AUD/USD stocks and that price-only μ understates Sharpe for dividend payers.
  - **Checks:** all portfolios: sum 100%, no negatives, ≤ 30%, held ≥ 2.5%, ≥ minimum held. Max Return / Max Dividend: ≥ equal-weight value; matches the exact optimum. Max Sharpe: ≥ equal-weight, Min Risk and Max Return Sharpe ratios; ≤ theoretical ceiling; on or left of the frontier.
  - **Tested (scripted):** 12 mixed NSE/ASX/USA stocks and 11 volatile stocks, minimum 4 and 5. Max Return and Max Dividend matched the exact optimum every time (e.g. 30/30/30/10 at min 4; 30/30/30/7.5/2.5 at min 5). **Max Sharpe matched a brute-force search over every allowed set of held stocks** (0.8646 = 0.8646; 1.4347 = 1.4347) and the theoretical ceiling. Frontier: 18/18 swept points solved; Max Sharpe 0.01–0.04 points left of the swept curve. Edge cases: only 4 dividend payers with minimum 5 → "Not enough stocks pay dividends…" error; risk-free rate above every achievable return → clear error; dividend flags for missing, non-payer, high (10%), implausible (30%) and out-of-range (250%) values. Timing for 12 stocks: all four portfolios + frontier ≈ 0.7 s.
  - **Tested in the browser** (AAPL, Reliance, BHP, JNJ, KO, PG; rf 4%): Min Risk 6 held, σ 11.20%, Sharpe 0.504; Max Return AAPL/BHP.AX/KO 30% + JNJ 10%, 15.54% (= exact); Max Dividend BHP.AX/PG/KO 30% + JNJ 10%, yield 2.96% (= exact); Max Sharpe AAPL 30%, BHP.AX 29.37%, JNJ 24.47%, KO 16.15%, Sharpe 0.828 (= ceiling), 0.20 points left of the swept frontier; equal weight Sharpe 0.573. All checks pass in all four views; switching the dropdown is instant; changing rf to 5% recomputed Max Sharpe (Sharpe 0.757 = ceiling).
  - Deployment check on Streamlit Cloud: pending after the step 4 push.
  - Committed and pushed as `8cae675` (2026-10-07).
- [x] **Scope change: spec updated (2026-10-07)**, committed and pushed as `c5901d2`. `PROJECT_SPEC.md` requires one market per session and the selected market's 10-year government bond yield as the Max Sharpe risk-free rate (see "Scope change 2026-10-07" below).
- [x] **Scope change: IMPLEMENTED and tested locally (2026-10-07).** Not yet committed at the time of writing.
  - **Market selection** at the very top: radio India (NSE) / Australia (ASX) / USA, **nothing pre-selected**; the rest of the app appears only after a choice. Switching market when anything has been entered or computed shows a warning with "Switch to X and clear" / "Cancel, stay on Y"; confirming **wipes the session** (input table, matches, fetched data, results); Cancel keeps everything.
  - **Input table** has one column ("Ticker or company name"), starts empty, with market-specific examples in the instructions. Every input is resolved against the selected market only.
  - **Out-of-market flags** in Confirm matches (user decision: based on the listing's exchange, ticker suffix and currency, *not* the company's home country): e.g. "⚠️ Outside USA: listed on NSE (NSI); RELIANCE.NS is not a ticker for USA; priced in INR, not USD". **Flagged rows start unticked**; ticking = override ("Included by you"; Match type `⚠️ Outside market (included by you)`, carried into all outputs and noted in portfolio views). Skipped flagged rows are listed with their reasons.
  - **Another market's ticker** (e.g. `RELIANCE.BO` in India, `BHP.L` in Australia, `BHP.AX` in USA): if the same company is listed on the selected market, that listing is offered instead ("⚠️ You entered BHP.AX (Australian); using the USA listing instead (its price and currency)", Match type `⚠️ Switched listing`); otherwise the typed listing is offered and flagged.
  - **Risk-free rate** = the market's 10-year yield from CNBC, pre-filled in the (still overridable) input; shown as "Risk-free rate: <name> <value> · Source · As of … (live)"; a yellow "⚠️ Fallback value in use" box with the reason if the live fetch failed; an "overridden by you" notice when the user changes it. Max Sharpe caption names the rate used.
  - **Mixed-currency / cross-exchange notices** now appear only if the user overrides a flag and includes a stock from another market (each stock's actual listing market is recorded via `market_of_exchange`, so exchange close-times stay correct for such stocks).
  - `optimizer.py` and `stats.py` unchanged: Min Risk, Max Return and Max Dividend logic untouched (decision 6).
  - **Tests (Streamlit `AppTest`, driving the real `app.py`; the browser pane was hidden so screenshots weren't usable):**
    - Start: no market selected, "Choose a market to start" shown.
    - India session (Reliance, TCS, Infosys, ITC, HDFC Bank, RELIANCE.BO, BHP.AX, Apple): Reliance etc. resolve on NSE; RELIANCE.BO → switched to RELIANCE.NS → duplicate of "Reliance"; BHP.AX flagged (3 reasons), unticked; Apple → no match on NSE. Ticking BHP.AX → "Included by you", Fetch 6; mixed AUD/INR warnings appear; unticking → no mixed-currency warning. Live rate India 10Y 7.25% (CNBC, with timestamp); override to 6.5% → notice. Switch to USA → warning; Cancel keeps market and data; Confirm → market USA, all progress cleared. No exceptions, no failed checks.
    - Australia session (BHP, CBA, Woolworths, CSL, Telstra, Wesfarmers, ResMed, BHP.L, AAPL): all resolve on ASX (ResMed RMD.AX not flagged: ASX listing, AUD); BHP.L → switched to BHP.AX → duplicate; AAPL → no match. Live rate 5.413%. All four portfolio views: no failed checks.
    - USA session (AAPL, Microsoft, JNJ, KO, PG, Infosys, BHP.AX, RELIANCE.NS, CBAUF): Infosys → INFY (NYSE, USD, not flagged); BHP.AX → switched to BHP (NYSE); RELIANCE.NS and CBAUF (OTC) flagged, unticked. Live rate 5.307%. All four portfolio views: no failed checks.
    - `rates.py`: all three markets live; forced CNBC failure → fallback with reason; stale fallback (145 days) → "may be out of date".
    - Regression: step 4 scripted tests all pass (Max Sharpe = brute force, exact optima, frontier check).
  - **Bugs found and fixed during testing:** (1) confirming a market switch crashed (the clean-up deleted its own `input_version` counter); (2) frontier check failed when Max Sharpe = Max Return (see `frontier.py` note); (3) a name clash (`risk_free_rate` variable vs imported function) that would have crashed the cached yield lookup, caught by `pyflakes` before running.
  - Deployment check on Streamlit Cloud: pending after the push (watch for CNBC being blocked from Streamlit's servers: the app would then show the fallback notice).
- [ ] **Next:** commit + push the implementation; deployment check of steps 2–4 + the scope change on Streamlit Cloud; then V2 (Risk Parity).

### V2 (Risk Parity): not started
### V3 (Black-Litterman): not started

## Decisions log

### Input and ticker resolution
- **Ticker mapping**: NSE → `.NS`, ASX → `.AX`, USA → plain. Input is uppercased/trimmed; the suffix is not added twice if typed; US dots become dashes (`BRK.B` → `BRK-B`).
- **Ticker-or-name input** (`data.resolve`): Yahoo symbol search (`yf.Search`), filtered to the selected exchange (NSE=`NSI`; ASX=`ASX`; USA=NYSE/NASDAQ/NYSE American). If the input looks like a ticker, the exact symbol is also checked (second search, then a direct price check) and ranked first.
- **Excluded from matches**: ETFs/funds/futures (user decision: **no ETFs for now**), BSE (`.BO`), US OTC, NYSE Arca/Cboe (ETF venues), preference shares/notes/warrants/units (`-P?`, `-WT`, …).

### Confirm matches step (user decisions)
- Two-step flow (**option B**): *Resolve* shows every input with a dropdown of matches (top match pre-selected), resolved ticker + full company name.
- **Never blocks on unresolved rows:**
  - Each row has an **Include** checkbox (matched rows ticked by default; no-match rows unticked + disabled, "will be skipped"). Unticking = skip, and it's reversible.
  - Ambiguous rows **auto-pick the top match with a flag**. Match types: `✅ Exact ticker` / `✅ Single match` / `⚠️ Auto-picked` / `✅ Picked by you`. The flag clears only when the user picks a *different* option (Streamlit can't detect re-selecting the same one). **Keep this Match flag visible in later portfolio output too** (already carried into the step 2 summary table).
  - The Fetch button is enabled whenever ≥1 stock is included and states the counts ("Fetch 6 stocks (skipping 2)"), with the skipped inputs + reasons listed above it.
  - Duplicate matches: the first input wins; later ones are skipped with reason "Duplicate of …".
  - Fixing a row = edit the input table and Resolve again; choices on unchanged rows are kept. Skipping never removes the row from the input table.
- **Output** shows three separate lists: **Included** (with Match column), **Skipped** (no match / skipped by you / duplicate) and **Failed to fetch** (matched but no price data). Raw data is shown for included stocks only.
- **< 10 stocks**: warning only (based on the included count). Enforce once the optimizer exists.

### Data
- **Lookback**: `period="5y"`, `interval="1d"`. Stocks with < 3 years of history are kept, with a warning.
- **Price columns**: fetched with `auto_adjust=False`, so both `Close` and `Adj Close` are kept. Returns use `Close` (see step 2 decisions).
- **Last price**: latest `Close` from the already-fetched daily history (no separate live call; matches `fast_info.last_price`, ~15-min delayed intraday). Shown with its "as of" date in the Included table and per-stock header, not as a repeated column in the history table.
- **TTM dividend yield**: computed ourselves = dividends paid in the last 365 days (history's `Dividends` column) ÷ latest `Close`. yfinance's `info["dividendYield"]` is not used: its units changed in 2025 and the endpoint is slow/rate-limited.
  - Paid nothing → `0.0` (shown 0.00%). Data missing → `None` (shown N/A).
- **Invalid tickers**: yfinance returns an empty frame (no exception) → reported as a per-stock error; other stocks still proceed.
- **Caching**: `st.cache_data(ttl=3600)` in memory only for both resolve and fetch; no disk/DB storage (spec 2.2). Step 2 stats are recomputed on each run (fast; not cached).

### Returns and covariance (step 2, user decisions 2026-10-06)
- **Daily vs weekly vs monthly → daily** (user choice). I recommended weekly because daily returns understate cross-exchange correlations (see Known limitations); monthly gives only ~60 data points over 5 years, too few for a stable covariance matrix of 10–20 stocks. The spec (Section 2.2) lists daily (preferred) or monthly; weekly would have been a deviation.
- **Simple vs log → simple.** Portfolio return = weighted sum of simple returns, which the optimizer relies on; that doesn't hold for log returns.
- **Price**: `Close` = **price excluding dividends** (user choice; I had recommended Adj Close for total return). Yahoo's Close is split-adjusted (verified on NVDA's 10:1 split, June 2024, no jump). Consequence: dividend days show as small price drops, so μ for high-yield stocks is understated by roughly their yield (e.g. BHP ~4%/yr).
- **Date alignment** (user choice: "use the last closing price for each exchange, previous day or current day close"): union of all exchanges' trading dates; on a day an exchange was closed, its stocks carry their last close forward (0% return that day). **Today's bar is used only once that exchange has closed** (NSE 15:45 IST, ASX 16:20 AEST/AEDT, US 16:15 ET, i.e. close + buffer); before that, the previous close is used. Each exchange's prices are aligned on its own local calendar date. Rejected: keeping only dates where all exchanges traded (drops ~10% of days and still leaves the timezone problem).
- **History length** (user choice): each stock uses all the history it has, up to the 5 years fetched. μ/σ use the stock's own period; covariance/correlation use each pair's overlapping dates (pandas pairwise). Stocks with < 3 years are flagged, not excluded. Rejected: truncating every stock to the shortest history (throws away data for all), or excluding short-history stocks (user wants them used).
- **Annualization factor**: × observed aligned trading days per year (~259 with three exchanges, since the union calendar has more days than one exchange's 252; using 252 would understate annual figures by ~3%). μ = mean daily return × factor; σ = daily std × √factor; Σ = daily covariance × factor.
- **Price CAGR** is shown next to μ: μ (arithmetic) is normally a little higher (e.g. AAPL 20.9% vs 18.6%); that's expected, not a bug.
- **Flag thresholds** (my defaults, accepted): μ > +100% or < −50%; σ > 80%; > 20% zero-return days; correlation > 0.95; history < 3 years (spec minimum). Flags never exclude a stock.
- **Display**: μ, σ, CAGR, yield as % (1–2 decimals); covariance to 4 decimals; correlation heatmap with Plotly (red = negative, blue = positive, −1 to 1).

### Min Risk portfolio (step 3, user decisions 2026-10-06)
- **Constraint values (decided by user, do not change without asking):** max 30% per stock; held stocks at least 2.5% (otherwise exactly 0%); minimum 4 stocks held by default, user can change it in the UI. **Note:** PROJECT_SPEC.md Section 2.4 says the default minimum is 5 and the user may lower it; 4 is the user's chosen default (within what the spec allows). With a 30% cap, 4 is also the mathematical minimum, so the count rule only matters if the user raises it.
- **Method (user decision: option B, drop-and-re-solve with scipy):**
  1. Solve without the 2.5% floor (bounds 0–30%). This also gives the **lower bound** (theoretical floor) shown on screen.
  2. Drop the smallest position below 2.5%, re-solve; repeat (never dropping below the minimum count).
  3. Solve once more with every remaining stock bounded 2.5%–30%.
  4. **Swap improvement:** try replacing each held stock with each excluded one; keep any swap that lowers the objective; repeat (max 10 passes). Added after testing showed steps 1–3 alone were 0.01–0.02 percentage points of σ off the exact optimum when the minimum-count rule binds; with swaps, all test cases match the exact optimum.
  - Solver: `scipy.optimize.minimize`, SLSQP, `ftol=1e-15`, analytic gradient, starts from equal weights.
  - Rejected: (A) exact mixed-integer solver via `cvxpy` + SCIP (`pyscipopt`): exact, both install locally, but adds packages and doesn't carry over to Max Sharpe (the Sharpe transformation breaks the 2.5% rule); (C) brute force: exact but only feasible up to ~12–14 stocks.
- **Failure handling:** every solve checks the solver's success flag and independently verifies bounds and the 100% sum (tolerance 0.0001%); on failure it retries once from a different starting point; if it still fails, an error is shown and **no portfolio is displayed**. Weights below 1e-9 are cleaned to exactly 0 before verification. If the final weights break any rule, the portfolio is shown with an error banner saying not to rely on it.
- **Covariance repair:** if Σ is not positive semi-definite (possible with different history lengths), negative eigenvalues are clipped to 0 (nearest PSD matrix), with a note on screen. Done once in `prepare_covariance`, shared by all portfolios.
  - **Bug fixed before reuse (2026-10-06):** originally the repair happened inside `min_risk_portfolio` while `app.py` computed the displayed portfolio figures from the *unrepaired* matrix, so the shown risk could differ from the optimizer's when a repair was needed (test on a deliberately broken matrix: shown σ 25.26% vs optimizer σ 25.34%). Now both use `prepared.cov` (both 25.336633%). Never occurred with real data.
- **Pre-reuse cleanup (2026-10-06), checked before step 4:** constraint values live only in the named settings; constraint handling (`optimize`) is separate from the Min Risk objective; `app.py` copies constraint defaults as a whole (`dataclasses.replace`) instead of field by field; the minimize-only sign convention is documented. After these changes all brute-force tests still match exactly and the browser result is unchanged.
- **Equal-weight comparison:** equal share across all included stocks. Only a valid benchmark if equal weight obeys the rules itself (between `min_held` and 40 stocks); otherwise the check shows ➖ "Not applicable" with the reason.
- **Lower bound / theoretical floor:** the relaxed problem (no 2.5% floor, no count rule) can't be beaten by any valid portfolio, so the true optimum lies between it and the result. On real lists the gap was 0.00–0.01 points; on random 20–35-stock matrices ~0.1–0.2 points (the relaxation isn't always tight, which doesn't by itself mean the result is suboptimal).
- **Dividend yield:** stocks with no dividend data count as 0% in the portfolio's weighted yield (noted on screen).
- **Expected return** uses step 2's μ (price-only, local currency), so the mixed-currency caveat applies and is shown next to it.
- **10-stock minimum (spec Section 2.1):** still a warning only (user decision); the feasibility check blocks the cases that can't work.
- **Recomputes automatically** when the minimum-stocks number changes (no extra button).

### Max Return, Max Dividend, Max Sharpe (step 4, user decisions 2026-10-07)
- **Same rules as Min Risk, from the same settings** (`Constraints`): 30% cap, 2.5% floor, minimum 4 stocks by default (user confirmed 4, not the 5 mentioned in the step 4 brief). Only the objective changes; all go through `optimize` (drop-and-re-solve + swaps).
- **Max Return / Max Dividend are linear goals**, so the optimum fills the best stocks to the cap, the minimum-count rule brings in further stocks at the floor and one stock takes the remainder (min 4 → 30/30/30/10; min 5 → 30/30/30/7.5/2.5). User confirmed this is the intended behaviour. Because the optimum can be worked out directly (`exact_linear_optimum`: hold the top `min_held` stocks, floor each, fill in order to the cap), every result is checked against it.
- **Max Dividend uses dividend-paying stocks only** (user decision). Stocks with missing dividend data count as 0% = non-payers. If fewer than the minimum number of stocks pay dividends, it shows an error ("Not enough stocks pay dividends to build this portfolio…") and no portfolio. (My earlier idea of a tiny lower-risk tie-break for zero-yield filler stocks was dropped as no longer needed; all objectives are exactly as specified.)
- **Dividend data quality:** yields are fractions computed in `data.py` as dividends ÷ price from the same Yahoo history, so a percent/fraction mix-up can't occur by construction. Flags shown in the Max Dividend view: missing (counted 0%, excluded); outside 0–100% (unit/data error, excluded); above 15% "implausible" (kept, with a warning to untick it in Confirm matches if wrong); 8–15% "high, worth checking" (kept); non-payers listed.
- **Max Sharpe:** objective −(wᵀμ − r_f)/√(wᵀΣw) through the shared `optimize`, using the prepared covariance matrix. Verified against `sharpe_ceiling`: the exact best Sharpe ratio when the 2.5% floor and minimum-count rules are dropped (convex reformulation y = κw: minimize yᵀΣy s.t. (μ − r_f)ᵀy = 1, Σy = κ, 0 ≤ y ≤ 0.3κ). No valid portfolio can beat it. If no rule-following portfolio beats the risk-free rate, Max Sharpe shows an error instead of a portfolio.
- **Risk-free rate:** named default `RISK_FREE_RATE = 0.04` with a UI input. 4% is a placeholder roughly between US T-bills (~4%), Australia's cash rate (~3.6%) and India's policy rate (~5.5%) as of 2025; **not verified for October 2026**; the user should set a current rate. On-screen note: one rate is applied across INR/AUD/USD stocks.
- **Efficient frontier** (`frontier.py`): 20 target returns from Min Risk's return to Max Return's (18 interior points swept + the two ends); at each, the lowest-risk portfolio reaching it under the same rules, via `optimize` with an extra "return ≥ target" constraint and **without the swap step** (prototype: with swaps the sweep took 7 s for 12 stocks and 54 s for 35; without, 0.4 s and 3.9 s). The actual Min Risk, Max Sharpe and Max Return portfolios are then added to the curve and dominated points removed, so the curve passes exactly through what the optimizer produced. The "on the frontier" check compares Max Sharpe with the swept points only (otherwise it would trivially pass); tolerance 0.1 percentage point of risk.
- **Swap time limit:** 5 s per portfolio (`SWAP_TIME_LIMIT`), to stay responsive on Streamlit Cloud with large lists (prototype: Max Sharpe on 35 random stocks took ~10 s with unlimited swaps). Real 10–20 stock lists finish far below it. A note appears if the limit is hit.
- **Caching:** each calculation is cached on exactly its inputs (`st.cache_data`): Min Risk (Σ, tickers, rules), Max Return (μ, rules), Max Dividend (yields, rules), Max Sharpe (Σ, μ, rf, rules, comparison portfolios), frontier (Σ, μ, rules, anchor portfolios). Switching the dropdown hits the cache; changing the minimum-stock count recomputes everything; changing rf recomputes only Max Sharpe and the frontier (whose curve includes the Max Sharpe portfolio); Min Risk, Max Return and Max Dividend stay cached. Fresh data (new stock list, or a market closing so today's price becomes final) changes Σ/μ and refreshes automatically.
- **Equal-weight comparisons** use all included stocks (all, including non-payers, for Max Dividend) and show "not applicable" when equal weight itself breaks the rules (e.g. > 40 stocks).
- **Sharpe ratio is shown for every portfolio**, including Min Risk (display only; Min Risk weights unchanged).

### Scope change 2026-10-07: one market per session, 10-year bond yield as risk-free rate (spec updated; implemented 2026-10-07, see Status)
User decisions (final; recorded in PROJECT_SPEC.md Sections 2.1, 2.2, 2.6 (new), 3.4, 6 and 9 (new)):
1. **One market per session.** At the very start the user explicitly selects exactly one of India (NSE), Australia (ASX) or USA. **No market is pre-selected.** Never mixed in a session.
2. **Every stock entered is assumed to belong to the selected market.** No per-stock exchange tag any more; name/ticker resolution is scoped to the selected market only.
3. **Anything that doesn't look like it belongs to the selected market** (wrong exchange, wrong currency, wrong ticker suffix, foreign or dual listing) **is flagged, not silently included.** The user is never blocked: they can skip a flagged row or override the flag and include it, consistent with the existing Confirm-matches skip/ignore behaviour.
4. **Risk-free rate = the selected country's 10-year government bond yield** (India 10Y, Australia 10Y, US 10Y). The user can still override it manually. The app must show the value used, its source and its as-of date, and must say explicitly when a fallback value is used instead of a live one.
5. **One currency per session**, so the mixed INR/AUD/USD limitation no longer applies within a session (once implemented). Currency conversion and cross-market portfolios remain out of scope.
6. **Min Risk, Max Return and Max Dividend are unaffected.** Only Max Sharpe, the Sharpe ratios and the efficient frontier change, and only because the risk-free rate changes.

Open decisions answered by the user (2026-10-07), now written into the spec as rules:
- **India = NSE only.** BSE is not supported; BSE listings are flagged as outside the market.
- **Switching market asks for confirmation first; for now, confirming clears the session's progress** (entered stocks and all results).
- **Market choice is explicit** (no default).
- **10-year yield data source: Bloomberg (bloomberg.com) government bond pages** (user's choice).

**Open decisions: ALL RESOLVED during implementation (user, 2026-10-07)**, and the spec updated accordingly (Sections 2.6, 3.4, revision history):
- **Foreign / dual listings:** "choose the price and currency of the exchange selected at the start". A company belongs to the market when the listing used is on the selected exchange and priced in its currency (e.g. Infosys's NYSE listing is fine in a USA session; ResMed's ASX listing is fine in an ASX session). Flags = listing on another exchange, another market's ticker suffix, or another currency. The company's home country is *not* checked (I had proposed country of domicile; the user chose this instead). **Flagged rows start unticked** (user choice).
- **India's 10-year yield / data source:** **CNBC for all three markets** (user decision), replacing Bloomberg. Then the fallback if not found.
- **Fallback values:** a **fallback document**, `fallback_rates.json` (user decision), maintained by hand.
- My own implementation choice (recorded, easy to change): typing another market's ticker offers the same company's listing on the selected market when one exists ("switched listing"), in the spirit of the user's "use the selected exchange's price and currency" rule.

*Original list, kept for history:*
1. **Exact criteria for flagging a foreign or dual listing** (spec 2.6). E.g. an ADR such as INFY (Infosys, NYSE) entered in a USA session; how to detect "primary listing elsewhere".
2. **How India's 10-year yield is obtained** (spec 3.4): no Bloomberg page found for it (see below).
3. **Fallback yields: what the values are, how they're stored, how they're kept up to date** (spec 3.4).

**CNBC check (2026-10-07, implementation):** CNBC's quote service returns all three 10-year yields with exact timestamps (India 7.21–7.26%, Australia 5.41%, USA 5.31% during testing; Yahoo's `^TNX` agreed for the US). Quirk: the India symbol `IN10Y-IN` returns "no data" (code 1) when requested on its own, but `IN10Y` works, so `IN10Y` is used.

**Bloomberg (superseded by CNBC):** on re-test during implementation, Bloomberg returned 403 for the same pages depending on the browser identity sent (bot protection), and still had no India page. **Correction:** the "4.11" quoted below from the first check was the US 3-month bill, not the 10-year; parsed correctly, Bloomberg's 10-year values were US 5.307% (`GT10:GOV`) and Australia 5.402% (`GTAUD10Y:GOV`), matching CNBC.

**Bloomberg feasibility check (2026-10-07, before writing the spec):**
- `https://www.bloomberg.com/markets/rates-bonds/government-bonds/us` and `/australia`: HTTP 200 from a script (with a browser user-agent); the yields are embedded in the page HTML (e.g. `"yield":4.11…` near the `GT10:GOV` 10-year entry), so they can be parsed without a browser.
- `/government-bonds/india` and `https://www.bloomberg.com/quote/GIND10YR:IND`: HTTP 404, so no India page was found.
- **Risks to handle in implementation:** Bloomberg's terms of use restrict automated scraping; its bot protection may block Streamlit Cloud's shared servers even though a local request worked; page layout changes would break parsing. All of these must fall back cleanly, with the on-screen "fallback value used" notice the spec requires. "A simple Google search" can't be done by the app at runtime without a paid search API, so the spec names the Bloomberg pages directly.

**Scope change 2026-10-07: what the implementation must do** (all done 2026-10-07, see Status; the HTML-parsing package question became moot because CNBC returns JSON, read with the standard library):
- Add an explicit market selector at the very start (no default); confirmation dialog on switching that clears all session progress.
- Remove the per-row Exchange column from the input table; resolve every input against the selected market only (`data.resolve` / `EXCHANGE_SEARCH_CODES` scoped to one market).
- Flag rows that don't look like they belong to the market (wrong exchange, currency, suffix, foreign/dual listing) in Confirm matches, with skip/override, never blocking. BSE (`.BO`) listings in an India session are flagged.
- Fetch the 10-year yield for the selected market (Bloomberg, with fallback); show value, source, as-of date and a clear fallback notice; keep the manual override input (pre-filled with the fetched value).
- Remove the mixed-currency and cross-exchange-correlation notices that can no longer occur within a session (or keep them only if a user override brings in a foreign-currency stock; decide when implementing the flags).
- Min Risk, Max Return and Max Dividend logic stays unchanged; only Max Sharpe, the Sharpe ratios and the frontier change via the risk-free rate.
- `requirements.txt` will likely need an HTML-parsing package if Bloomberg pages are parsed (e.g. `beautifulsoup4`, or plain `re`/`json` parsing to avoid it); decide during implementation.

## Known limitations / risks
- **Currency (not handled, per spec Section 6):** *No longer applies within a session since the 2026-10-07 scope change (one market per session, implemented): it can only arise if the user overrides an out-of-market flag and includes a stock priced in another currency, in which case the warnings below still appear.* each stock's μ, σ and covariances are in its own currency (INR/AUD/USD), with no conversion. Effects: (1) returns in weaker or higher-inflation currencies look higher (INR has historically depreciated ~2–4%/yr vs USD), so Max Return/Max Sharpe will lean towards NSE stocks partly for that reason; (2) σ excludes FX risk for a foreign investor; (3) cross-exchange correlations miss shared currency moves. Within a single exchange the numbers are fine; comparisons across exchanges are biased, mainly on returns. The app shows a ⚠️ mixed-currency warning whenever included stocks span more than one currency.
- **Cross-exchange correlations are understated with daily returns.** *(No longer applies within a session since one market per session was implemented, except for stocks the user includes by overriding an out-of-market flag.)* NSE/ASX close before the US opens, so a US move shows up in Asian/Australian prices a day later. Measured: Infosys NSE vs NYSE ADR daily correlation 0.49 (weekly 0.80, monthly 0.97); BHP ASX vs NYSE 0.36 (weekly 0.82, monthly 0.94). The optimizer will therefore see more diversification between exchanges than really exists. The app shows a note when stocks span exchanges. Weekly returns would fix most of this if revisited.
- **Forward-filled holidays** add 0% days, which slightly lowers σ and correlations.
- **Dividends excluded from returns** (price-only `Close`): μ is understated for dividend payers by roughly their yield.
- **Pairwise covariance with different history lengths can be non-positive-semi-definite.** The PSD check flags it; step 3 must repair it (e.g. nearest PSD matrix) before optimizing.
- **Yahoo Finance reliability**: unofficial data source; may rate-limit (especially Streamlit Cloud's shared servers) or change its API. Search results are capped at ~5–10, so a globally common name may occasionally miss the right listing; typing the exact ticker always works.

## Deployment
- **GitHub**: `rahulpalit07/virtual-portfolio-builder`, branch `main`. Streamlit Cloud redeploys automatically on push.
- **`requirements.txt` is the only thing Streamlit Cloud installs.** Every package the app imports must be listed, or the live app breaks even if local works. Current list: `streamlit`, `yfinance`, `numpy`, `pandas`, `plotly`, `jinja2`, `scipy`, `PyPortfolioOpt`, `riskparityportfolio`.
  - `jinja2` is needed by pandas table formatting (`.style.format`, used for the covariance/correlation tables). It is not imported directly; it's listed explicitly so the app doesn't depend on Streamlit happening to install it.
  - `scipy` is used from step 3 (`optimizer.py`). `PyPortfolioOpt` and `riskparityportfolio` are not used yet (kept by user decision); all three installed fine on Streamlit Cloud.
  - Step 3 adds no new packages (`cvxpy`/`pyscipopt` were considered and rejected; see step 3 decisions).
  - Step 4 adds no new packages: the frontier chart uses `plotly.graph_objects` (part of `plotly`, already listed); all optimization stays in `scipy`.
  - The scope-change implementation adds no new packages: `rates.py` uses only the standard library. `fallback_rates.json` must be committed (the app reads it at runtime on Streamlit Cloud).
- **`.gitignore`** excludes: virtual environments (`.venv/`, `venv/`, `env/`), Python caches (`__pycache__/`, `*.py[cod]`, `.pytest_cache/`, `.mypy_cache/`, `.ipynb_checkpoints/`), secrets (`.env`, `.env.*`, `.streamlit/secrets.toml`), temp/log/OS files (`*.log`, `*.tmp`, `.DS_Store`, `Thumbs.db`) and local Claude Code tooling (`.claude/`).
- `PROJECT_SPEC.md` was unchanged from the initial commit until **2026-10-07**, when it was updated for the one-market-per-session scope change (Sections 2.1, 2.2, 2.6 new, 3.4, 6, 9 new; see Section 9 "Revision history" in the spec).

## Notes for step 3 (Min Risk portfolio): all addressed
- Use `StatsResult.cov` from `stats.compute_stats` as Σ; put the optimizer in `optimizer.py`. **Done.**
- Check positive semi-definiteness first; repair (nearest PSD) if the sanity check fails. **Done** (`nearest_psd`).
- Constraints from Section 2.4: weights ≥ 0, sum to 1; minimum number of stocks; max weight per stock. Note: a cap alone forces ≥5 stocks only when the cap is below 25% (at 25%, four stocks × 25% = 100%). With the suggested 30–40% cap, 3–4 stocks could hold everything, so the minimum-count rule needs its own handling. **Done:** user set cap 30%, floor 2.5% ("non-trivial weight"), minimum 4 by default (adjustable); count rule handled in the drop loop.
- Enforce the 10-stock minimum once portfolios are built. **User decided to keep it as a warning.**
- Carry the Match flag (⚠️ Auto-picked) and the mixed-currency warning into portfolio output. **Done.**

## Notes for step 4 (Max Return, Max Dividend, Max Sharpe): all addressed
- Reuse `optimizer.optimize` and `Constraints`; each portfolio supplies only an `Objective` (minimize −Σwμ for Max Return, −Σw·yield for Max Dividend, −(wμ − r_f)/√(wᵀΣw) for Max Sharpe). Remember to negate `objective_value` and `lower_bound` back when displaying. **Done.**
- Max Sharpe must use `prepared.cov` from the single `prepare_covariance` call in `app.py` (same matrix as Min Risk). **Done.**
- Max Return and Max Dividend have linear objectives: with the 30% cap the answer will typically be the top 3 stocks at 30% plus one at 10% (min 4 stocks). The equal-weight risk check is specific to Min Risk and must not be applied to these. **Done:** confirmed by tests and checked against the exact closed-form optimum; these portfolios use equal-weight return/yield checks instead.
- Max Sharpe needs a risk-free rate r_f. **Done:** default 4% (named setting), user-adjustable, with a mixed-currency note.
- Max Sharpe's objective is non-convex in general; check against a bound. **Done:** verified against the exact `sharpe_ceiling` and brute force.
- Swap improvement timing for 30–40 stock lists. **Done:** 5 s time limit with an on-screen note.

## Open questions / next up
- Resolve/fetch run sequentially (~2–3 s per stock). Could be run in parallel if 10–20 stock lists feel slow.
- `requirements.txt` includes `riskparityportfolio`; may not install on Python 3.14 / Windows locally. Revisit in V2.
- Currency handling: resolved by the 2026-10-07 scope change (one market per session); implementation pending.
- Scope-change open decisions (dual-listing criteria, India 10-year yield source, fallback yields): all resolved 2026-10-07; see "Scope change 2026-10-07".
- CNBC's quote service is unofficial (no documented API) and could change or block Streamlit Cloud; the fallback covers it, but `fallback_rates.json` needs manual refreshes.
- Out-of-market checks add ~0.3–1 s per stock in Confirm matches (one Yahoo request for each selected listing's currency; cached for an hour).
- Weekly returns: possible later fix for understated cross-exchange correlations.
- Risk-free rate default (4%) is a placeholder not verified for 2026; **replaced** in the app by the selected market's 10-year yield (2026-10-07). `optimizer.RISK_FREE_RATE` remains only as the function's code default.
- With very large lists (30–40 stocks), the swap step may hit its 5 s limit; watch for the on-screen note on Streamlit Cloud.
