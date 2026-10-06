# CLAUDE.md: Build Progress

Read `PROJECT_SPEC.md` first; it defines *what* the product is. This file tracks *where the build is*.

## Run it
```bash
python -m venv .venv
.venv/Scripts/python -m pip install streamlit yfinance pandas
.venv/Scripts/python -m streamlit run app.py
```
(Only the packages needed so far are installed locally; the rest of `requirements.txt` is for later steps.)
Note: Streamlit does not hot-reload `data.py` reliably. Restart the server after editing it.

## File structure
- `app.py`: Streamlit UI (input → resolve/confirm → fetch → display).
- `data.py`: ticker/name resolution + data fetching (yfinance). No Streamlit imports.
- `optimizer.py`: empty; built in a later session.

## Status

### V1 (Markowitz)
- [x] **Step 1: Data pipeline.** Complete, tested and confirmed working for **NSE, ASX and USA** (2026-10-06):
  - Input by **exact ticker or company name** on any of the three exchanges, resolved via Yahoo symbol search.
  - **Confirm matches** step: dropdown of matches per input, Include checkbox per row, auto-pick flag for ambiguous names, skip/ignore unresolved rows without blocking.
  - **Historical prices**: 5 years of daily OHLCV, both Close and Adj Close, shown raw per stock.
  - **Last price** (with "as of" date) and **TTM dividend yield** per stock.
  - Clear **Included / Skipped / Failed to fetch** lists in the output.
  - Tested with: AAPL, Apple, Tesla, Alphabet, BRK.B, Ford (USA); Reliance, RELIANCE, Reliance Industries, Bharti Airtel, Tata (NSE); BHP, CBA, Commonwealth Bank, Woolworths (ASX); plus no-match (`xyzqwerty`, `xxxya`), ETF (`SPY`) and duplicate (Apple + AAPL) cases.
- [ ] Step 2: Returns, annualized μ and σ, covariance matrix Σ (incl. date alignment across exchanges).
- [ ] Step 3: Optimizer: shared constraints + 4 objectives.
- [ ] Step 4: Portfolio output UI.

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
  - Ambiguous rows **auto-pick the top match with a flag**. Match types: `✅ Exact ticker` / `✅ Single match` / `⚠️ Auto-picked` / `✅ Picked by you`. The flag clears only when the user picks a *different* option (Streamlit can't detect re-selecting the same one). **Keep this Match flag visible in later portfolio output too.**
  - The Fetch button is enabled whenever ≥1 stock is included and states the counts ("Fetch 6 stocks (skipping 2)"), with the skipped inputs + reasons listed above it.
  - Duplicate matches: the first input wins; later ones are skipped with reason "Duplicate of …".
  - Fixing a row = edit the input table and Resolve again; choices on unchanged rows are kept. Skipping never removes the row from the input table.
- **Output** shows three separate lists: **Included** (with Match column), **Skipped** (no match / skipped by you / duplicate) and **Failed to fetch** (matched but no price data). Raw data is shown for included stocks only.
- **< 10 stocks**: warning only (based on the included count). Enforce once the optimizer exists.

### Data
- **Lookback**: `period="5y"`, `interval="1d"`. Stocks with < 3 years of history are kept, with a warning.
- **Price columns**: fetched with `auto_adjust=False`, so both `Close` and `Adj Close` are kept. *Which one feeds returns is still open; decide in Step 2.*
- **Last price**: latest `Close` from the already-fetched daily history (no separate live call; matches `fast_info.last_price`, ~15-min delayed intraday). Shown with its "as of" date in the Included table and per-stock header, not as a repeated column in the history table.
- **TTM dividend yield**: computed ourselves = dividends paid in the last 365 days (history's `Dividends` column) ÷ latest `Close`. yfinance's `info["dividendYield"]` is not used: its units changed in 2025 and the endpoint is slow/rate-limited.
  - Paid nothing → `0.0` (shown 0.00%). Data missing → `None` (shown N/A).
- **Invalid tickers**: yfinance returns an empty frame (no exception) → reported as a per-stock error; other stocks still proceed.
- **Caching**: `st.cache_data(ttl=3600)` in memory only for both resolve and fetch; no disk/DB storage (spec 2.2).
- **Dates**: each exchange keeps its own timezone/trading calendar for now; alignment is deferred to Step 2.

## Open questions / next up
- Step 2: choose `Adj Close` vs `Close` for returns (Adj Close includes dividends, which could double-count with the Max Dividend objective; decide deliberately).
- Step 2: during market hours the last history row is today's *in-progress* bar; returns should probably drop it.
- Step 2: date alignment strategy across NSE/ASX/US calendars (inner join on dates vs. forward-fill).
- Resolve/fetch run sequentially (~2–3 s per stock). Could be run in parallel if 10–20 stock lists feel slow.
- `requirements.txt` includes `riskparityportfolio`; may not install on Python 3.14 / Windows or on Streamlit Cloud. Revisit in V2.
