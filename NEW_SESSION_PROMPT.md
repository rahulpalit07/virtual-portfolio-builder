You are continuing work on my project "Virtual Portfolio Builder" in Claude Code. A previous
session did all the work so far; this prompt gives you the full context. Read everything below
before doing anything, and do not write or change any code until I say "go ahead".

## 1. Read these files first, in this order
1. `PROJECT_SPEC.md`: the authoritative spec (what the product is). It wins over everything
   else. **Never modify it** unless I explicitly ask; if I do, show me before/after pairs and
   wait for "approved".
2. `CLAUDE.md`: the master progress record (everything built, tested, every decision and why,
   known limitations, deployment notes). **Never shorten it**: only add or correct.
3. `UI_REDESIGN_PLAN.md`: the current piece of work (presentation-layer redesign): goals,
   hard rules, my decisions, target design, technical pitfalls, and a **Progress log
   (Section 11)** saying exactly where we are.
4. `tests/regression/README.md`: how to run the regression check that proves no number changed.
Then skim `app.py` (UI), and know that `data.py`, `stats.py`, `optimizer.py`, `frontier.py`,
`rates.py` and `fallback_rates.json` hold all calculations and data access.

After reading, reply with: (a) a short summary of the project and current status, (b) what
the next step is, (c) anything ambiguous or any assumption I should confirm. Then wait.

## 2. The project in brief
A Streamlit (Python) web app that builds optimized virtual stock portfolios with Modern
Portfolio Theory. No login, no trading. The user explicitly picks **one market per session**
(India NSE, Australia ASX or USA; nothing pre-selected), enters 10+ stocks by ticker or company
name, confirms the matches, and the app fetches ~5 years of daily prices from Yahoo Finance
(yfinance), computes daily simple returns (price only, dividends excluded), annualized μ, σ,
covariance and correlation, and builds four V1 (Markowitz) portfolios: **Min Risk, Max Return,
Max Dividend, Max Sharpe**, plus an efficient frontier. Rules for every portfolio: weights sum
to 100%, no short-selling, each stock either 0% or between **2.5% and 30%**, at least **4**
stocks held (default; user-adjustable). The Max Sharpe risk-free rate is the selected market's
**10-year government bond yield, live from CNBC**, with a stored fallback in
`fallback_rates.json` (the app must show value, source, as-of date, and say clearly when a
fallback is used); the user can override it. Out-of-market stocks (another exchange, another
currency, another market's ticker suffix) are flagged and start unticked; the user can include
them. V2 (Risk Parity) and V3 (Black-Litterman) come later.

Repo: `rahulpalit07/virtual-portfolio-builder`, branch `main`, deployed on Streamlit Community
Cloud (redeploys on push; installs only `requirements.txt`). Owner: Rahul Palit
(LinkedIn https://www.linkedin.com/in/rahul-palit/).

## 3. Current status (as of 2026-10-08)
- Last pushed commit: `b74f80f` (one market per session + 10-year yield). Local commits not yet
  pushed: `3ca46bc` (UI redesign plan), `76f9038` (**UI redesign Pass 1: layout and flow**),
  plus a commit adding `tests/regression/`, this prompt file and the plan's progress log.
- **UI redesign progress** (details in `UI_REDESIGN_PLAN.md` Section 11):
  - Pass 0 (regression baseline): done.
  - Pass 1 (layout and flow): done, committed locally, regression 78/78 identical.
  - **Pass 2 (charts and metric cards): NEXT.** Not started.
  - Pass 3 (theme and polish): to do.
  - Finish (update CLAUDE.md with all UI decisions): to do.
- `CLAUDE.md` has not yet been updated for the UI redesign (that happens at "Finish"); the plan
  file is the up-to-date record for the redesign until then.
- Open item: GitHub link in the footer currently uses the repo URL; I haven't confirmed it.

## 4. Hard rules for the redesign (non-negotiable)
1. **Presentation only.** Do not change any calculation, optimizer, constraint, data fetch or
   result. Every number the app produces must stay identical.
2. `data.py`, `stats.py`, `optimizer.py`, `frontier.py`, `rates.py`, `fallback_rates.json` and
   `PROJECT_SPEC.md` must show **zero diff** after every pass. Work only in `app.py` and new
   presentation files (e.g. `.streamlit/config.toml`).
3. Keep honouring the spec: one market per session with explicit choice; switching market (or
   loading an example over existing work) asks for confirmation and clears the session;
   out-of-market stocks flagged and unticked; risk-free rate value/source/as-of shown and any
   fallback stated prominently in the results (not only in the sidebar).
4. **No new packages.** If something seems to need one, stop and ask me.
5. Work in passes. **After each pass:** run the regression check (must be 78/78 identical,
   no exceptions), confirm zero diff on the protected files, run `pyflakes app.py`, run the UI
   tests, report to me, **commit locally, do not push**, and **stop** for my review.
6. Push only when I explicitly ask.

## 5. Decisions already made (do not reopen)
- Flow: "1. Your stocks" → "2. Your portfolios" → collapsed "Under the hood" → Methodology &
  limitations → footer. (Built in Pass 1.)
- One-click example per market (lists in `app.py` `EXAMPLE_STOCKS`, verified: exact tickers, no
  flags, all pay dividends). (Built.)
- **Segmented control** (`st.segmented_control`) for choosing the portfolio, not tabs (tabs
  render all views every rerun; hidden-tab charts mis-size). (Built.)
- Parallel lookups/fetches with threads in `app.py`; `data.py` untouched. (Built.) Note: in
  parallel, yfinance's Adj Close can differ by ≤7e-7 relative; Adj Close is not used in any
  calculation, so app numbers are identical.
- Statistics are **not** frozen at build time (keep current behaviour).
- Theme: **teal** (~`#0F766E`), red only for errors; sidebar only after a market is chosen.
- Footer: "Educational tool, not financial advice · Built by Rahul Palit · LinkedIn · GitHub".
- Keep side panels: Min Risk → correlation matrix; Max Sharpe → efficient frontier; Max Return
  and Max Dividend → none (full width).
- Future-proofing: drive results from a portfolio registry so V2/V3 are extra entries (see plan
  6.3).

## 6. What Pass 2 must deliver (from the plan)
- Weights as a horizontal bar chart (Plotly) + compact table (ticker, company, weight).
- Four metric cards (Expected return, Risk, Dividend yield, Sharpe) with **"vs equal weight"
  deltas**, replacing the separate equal-weight metrics and Min Risk's "risk reduction".
- Comparison table: highlight the best value per column (max return, yield, Sharpe; min risk),
  excluding the equal-weight reference row.
- One plain-English "why this portfolio" line per view.
- Match shown as a small icon column with a tooltip (column help), instead of repeating the
  auto-pick caption in results (the prominent auto-pick warning stays once, in the matches step).
Then Pass 3: `.streamlit/config.toml` teal theme; plain-English labels in the main view, Greek
symbols only under the hood; wording/spacing polish. Then Finish: update `CLAUDE.md`.

## 7. How to verify (commands; Windows, Git Bash)
- Run the app: `.venv/Scripts/python -m streamlit run app.py` → http://localhost:8501
  (also `.claude/launch.json` config "streamlit" for the preview tool). Restart the server after
  editing imported modules (Streamlit doesn't reliably hot-reload them).
- Regression (from the project root):
  `PYTHONIOENCODING=utf-8 .venv/Scripts/python tests/regression/harness.py tests/regression/run.json`
  then `python tests/regression/compare.py tests/regression/baseline.json tests/regression/run.json`
  → expect "compared 78 recorded results: 0 differences" and no exceptions/errors.
  The snapshot and baseline are local, git-ignored files in `tests/regression/`; don't
  re-snapshot (that would reset the baseline) unless I ask.
- UI tests: `PYTHONIOENCODING=utf-8 .venv/Scripts/python tests/regression/ui_test.py` (and
  `ui_test2.py`). Update their driving code if labels change; never change recorded values.
- Static check: `.venv/Scripts/python -m pyflakes app.py` (it caught a real bug before).
- Protected files: `git diff --stat HEAD -- data.py stats.py optimizer.py frontier.py rates.py fallback_rates.json PROJECT_SPEC.md requirements.txt` must be empty.

## 8. Practical notes from previous sessions
- Environment: Windows 11, Python 3.14 in `.venv`; use `PYTHONIOENCODING=utf-8` when printing
  symbols. Local venv has streamlit, yfinance, pandas, plotly, scipy, pyflakes (not
  `riskparityportfolio`, which needs a C++ compiler on Windows; it installs fine on Streamlit
  Cloud).
- The in-app browser pane is sometimes hidden, so screenshots/clicks fail; drive the real app
  with Streamlit `AppTest` instead (the data editor can't be typed into via AppTest: set
  `session_state["resolutions"]` or use the example buttons).
- AppTest moves a leading emoji in `st.warning`/`st.error` into the icon; match on words.
- Streamlit doesn't allow nested expanders (that's why "Under the hood" uses tabs inside one
  expander).
- Keep existing widget keys (`market_radio_{n}`, `input_{n}`, `pick_*`, `inc_*`, `min_stocks`,
  `rf_{market}_{value}`, `portfolio_view`) so user choices survive reruns.
- Yahoo and CNBC are unofficial sources; the fallback rate covers CNBC failures.

## 9. How I like to work
- Before building anything, confirm you understand the brief, list anything ambiguous, give
  recommendations with reasons (and say where you disagree with me), and wait for "go ahead".
- Test thoroughly and tell me honestly what failed and what you fixed.
- Keep `CLAUDE.md` comprehensive; record every decision with its reason.
- Plain language in what you show users; explain trade-offs to me briefly.
- Commit locally after each pass; push only when I say so.

Start by reading the files in Section 1 and replying as described there.
