# CLAUDE.md: Build Progress

Read `PROJECT_SPEC.md` first; it defines *what* the product is. This file is the master record of *where the build is*: what's built, what was tested, every decision made (and why), known limitations and what's next. Keep it comprehensive; update it at the end of every step.

## Run it
```bash
python -m venv .venv
.venv/Scripts/python -m pip install streamlit yfinance pandas plotly scipy
.venv/Scripts/python -m streamlit run app.py
```
(Only the packages needed so far are installed locally; `numpy` and `jinja2` come in as dependencies. `PyPortfolioOpt` and `riskparityportfolio` in `requirements.txt` are for later steps.)
Note: Streamlit does not hot-reload `data.py`/`stats.py`/`optimizer.py` reliably. Restart the server after editing them.

## File structure
- `app.py`: Streamlit UI (input → resolve/confirm → fetch → display → returns & risk → Min Risk portfolio). Only calls functions and displays results; no calculations.
- `data.py`: ticker/name resolution + data fetching (yfinance). No Streamlit imports. Key functions: `to_yahoo_symbol`, `resolve`, `fetch_ticker_data`.
- `stats.py`: daily returns, annualized μ and σ, covariance, correlation, sanity checks and flags. Pure calculations, no Streamlit. Key functions: `completed_closes` (drops today's bar if the exchange is still open), `compute_stats` (returns a `StatsResult`).
- `optimizer.py`: portfolio optimization (scipy). Pure calculations, no Streamlit. Contents:
  - **Constraint parameters, the single place to change them:** `MAX_WEIGHT = 0.30`, `MIN_WEIGHT = 0.025`, `MIN_STOCKS = 4`, wrapped in the `Constraints` dataclass (with derived `stocks_needed_for_cap` = 4, `max_stocks_for_floor` = 40, `min_held`).
  - `optimize(objective, tickers, constraints)`: **generic** constraint handling (feasibility check, lower bound, drop-and-re-solve, swap improvement, verification). Later portfolios only supply a new `Objective` (function + gradient). **Sign convention: it always minimizes**; maximizing portfolios pass a negated objective and negate `objective_value` / `lower_bound` back for display (documented in `Objective`).
  - `prepare_covariance(cov)` → `PreparedCovariance(cov, repaired, note)`: **shared step, run once** before any portfolio; repairs Σ if it isn't positive semi-definite. Every optimizer and every displayed portfolio figure must use `prepared.cov`.
  - `min_risk_portfolio(cov, tickers, constraints)` → `MinRiskResult` (weights, risk, lower-bound risk, equal-weight risk, checks, notes). Expects the prepared matrix.
  - Helpers: `feasibility_error`, `verify_constraints`, `nearest_psd`, `portfolio_stats` (weighted return, risk, weighted yield).
  - `app.py` builds per-run constraints with `dataclasses.replace(Constraints(), min_stocks=...)`, so any rule added to `Constraints` later is carried over automatically.
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
- [ ] **Step 4 (next): Max Return, Max Dividend and Max Sharpe portfolios** (PROJECT_SPEC.md Sections 3.1, 3.3, 3.4), reusing `optimizer.optimize` with new objectives. See "Notes for step 4" below.
- [ ] Step 5: Portfolio output UI (stock + weight % per portfolio, plus each portfolio's return/risk/yield/Sharpe).

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

## Known limitations / risks
- **Currency (not handled, per spec Section 6; user will revisit):** each stock's μ, σ and covariances are in its own currency (INR/AUD/USD), with no conversion. Effects: (1) returns in weaker or higher-inflation currencies look higher (INR has historically depreciated ~2–4%/yr vs USD), so Max Return/Max Sharpe will lean towards NSE stocks partly for that reason; (2) σ excludes FX risk for a foreign investor; (3) cross-exchange correlations miss shared currency moves. Within a single exchange the numbers are fine; comparisons across exchanges are biased, mainly on returns. The app shows a ⚠️ mixed-currency warning whenever included stocks span more than one currency.
- **Cross-exchange correlations are understated with daily returns.** NSE/ASX close before the US opens, so a US move shows up in Asian/Australian prices a day later. Measured: Infosys NSE vs NYSE ADR daily correlation 0.49 (weekly 0.80, monthly 0.97); BHP ASX vs NYSE 0.36 (weekly 0.82, monthly 0.94). The optimizer will therefore see more diversification between exchanges than really exists. The app shows a note when stocks span exchanges. Weekly returns would fix most of this if revisited.
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
- **`.gitignore`** excludes: virtual environments (`.venv/`, `venv/`, `env/`), Python caches (`__pycache__/`, `*.py[cod]`, `.pytest_cache/`, `.mypy_cache/`, `.ipynb_checkpoints/`), secrets (`.env`, `.env.*`, `.streamlit/secrets.toml`), temp/log/OS files (`*.log`, `*.tmp`, `.DS_Store`, `Thumbs.db`) and local Claude Code tooling (`.claude/`).
- `PROJECT_SPEC.md` has not been modified since the initial commit.

## Notes for step 3 (Min Risk portfolio): all addressed
- Use `StatsResult.cov` from `stats.compute_stats` as Σ; put the optimizer in `optimizer.py`. **Done.**
- Check positive semi-definiteness first; repair (nearest PSD) if the sanity check fails. **Done** (`nearest_psd`).
- Constraints from Section 2.4: weights ≥ 0, sum to 1; minimum number of stocks; max weight per stock. Note: a cap alone forces ≥5 stocks only when the cap is below 25% (at 25%, four stocks × 25% = 100%). With the suggested 30–40% cap, 3–4 stocks could hold everything, so the minimum-count rule needs its own handling. **Done:** user set cap 30%, floor 2.5% ("non-trivial weight"), minimum 4 by default (adjustable); count rule handled in the drop loop.
- Enforce the 10-stock minimum once portfolios are built. **User decided to keep it as a warning.**
- Carry the Match flag (⚠️ Auto-picked) and the mixed-currency warning into portfolio output. **Done.**

## Notes for step 4 (Max Return, Max Dividend, Max Sharpe)
- Reuse `optimizer.optimize` and `Constraints`; each portfolio supplies only an `Objective` (minimize −Σwμ for Max Return, −Σw·yield for Max Dividend, −(wμ − r_f)/√(wᵀΣw) for Max Sharpe). Remember to negate `objective_value` and `lower_bound` back when displaying.
- Max Sharpe must use `prepared.cov` from the single `prepare_covariance` call in `app.py` (same matrix as Min Risk).
- Max Return and Max Dividend have linear objectives: without the cap they'd put 100% in one stock; with the 30% cap the answer will typically be the top 3 stocks at 30% plus one at 10% (min 4 stocks). The verification checks should still apply; the equal-weight risk check is specific to Min Risk and must not be applied to these.
- Max Sharpe needs a risk-free rate r_f (spec Section 3.4: hardcoded or configurable; not fetched live in V1). Decide with the user; mixed currencies make a single r_f questionable (e.g. India vs US vs Australia rates differ).
- Max Sharpe's objective is non-convex in general; SLSQP from equal weights is usually fine, but check against the lower bound and consider multiple starts.
- Swap improvement in `optimize` runs for every objective; check timing for 30–40 stock lists if Max Sharpe proves slower.

## Open questions / next up
- Resolve/fetch run sequentially (~2–3 s per stock). Could be run in parallel if 10–20 stock lists feel slow.
- `requirements.txt` includes `riskparityportfolio`; may not install on Python 3.14 / Windows locally. Revisit in V2.
- Currency handling: user will revisit later (see Known limitations).
- Weekly returns: possible later fix for understated cross-exchange correlations.
