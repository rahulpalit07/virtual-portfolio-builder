# CLAUDE.md: Build Progress

Read `PROJECT_SPEC.md` first; it defines *what* the product is. This file is the master record of *where the build is*: what's built, what was tested, every decision made (and why), known limitations and what's next. Keep it comprehensive; update it at the end of every step.

## Run it
```bash
python -m venv .venv
.venv/Scripts/python -m pip install streamlit yfinance pandas plotly
.venv/Scripts/python -m streamlit run app.py
```
(Only the packages needed so far are installed locally; `numpy` and `jinja2` come in as dependencies. The rest of `requirements.txt` is for later steps.)
Note: Streamlit does not hot-reload `data.py`/`stats.py` reliably. Restart the server after editing them.

## File structure
- `app.py`: Streamlit UI (input → resolve/confirm → fetch → display → returns & risk). Only calls functions and displays results; no calculations.
- `data.py`: ticker/name resolution + data fetching (yfinance). No Streamlit imports. Key functions: `to_yahoo_symbol`, `resolve`, `fetch_ticker_data`.
- `stats.py`: daily returns, annualized μ and σ, covariance, correlation, sanity checks and flags. Pure calculations, no Streamlit. Key functions: `completed_closes` (drops today's bar if the exchange is still open), `compute_stats` (returns a `StatsResult`).
- `optimizer.py`: empty; reserved for the optimization math (step 3 onwards).
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
- [ ] **Step 3 (next): Min Risk portfolio**, the first optimizer (PROJECT_SPEC.md Section 3.2): minimize wᵀΣw subject to the Section 2.4 constraints (weights ≥ 0, sum to 1, at least 5 stocks with non-trivial weight, tunable max weight per stock). Goes in `optimizer.py`. See "Notes for step 3" below.
- [ ] Step 4: Max Return, Max Dividend and Max Sharpe portfolios (reusing the step 3 optimizer setup).
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
  - `scipy`, `PyPortfolioOpt`, `riskparityportfolio` are not used yet (kept by user decision); they installed fine on Streamlit Cloud.
- **`.gitignore`** excludes: virtual environments (`.venv/`, `venv/`, `env/`), Python caches (`__pycache__/`, `*.py[cod]`, `.pytest_cache/`, `.mypy_cache/`, `.ipynb_checkpoints/`), secrets (`.env`, `.env.*`, `.streamlit/secrets.toml`), temp/log/OS files (`*.log`, `*.tmp`, `.DS_Store`, `Thumbs.db`) and local Claude Code tooling (`.claude/`).
- `PROJECT_SPEC.md` has not been modified since the initial commit.

## Notes for step 3 (Min Risk portfolio)
- Use `StatsResult.cov` from `stats.compute_stats` as Σ; put the optimizer in `optimizer.py`.
- Check positive semi-definiteness first; repair (nearest PSD) if the sanity check fails.
- Constraints from Section 2.4: weights ≥ 0, sum to 1; at least 5 stocks with non-trivial weight (default; user may lower it); max weight per stock tunable (suggested 30–40%). Note: a cap alone forces ≥5 stocks only when the cap is below 25% (at 25%, four stocks × 25% = 100%). With the suggested 30–40% cap, 3–4 stocks could hold everything, so the minimum-count rule needs its own handling (and a definition of "non-trivial weight", e.g. ≥ 1%).
- Enforce the 10-stock minimum (currently only a warning) once portfolios are built.
- Carry the Match flag (⚠️ Auto-picked) and the mixed-currency warning into portfolio output.

## Open questions / next up
- Resolve/fetch run sequentially (~2–3 s per stock). Could be run in parallel if 10–20 stock lists feel slow.
- `requirements.txt` includes `riskparityportfolio`; may not install on Python 3.14 / Windows locally. Revisit in V2.
- Currency handling: user will revisit later (see Known limitations).
- Weekly returns: possible later fix for understated cross-exchange correlations.
