# Virtual Portfolio Builder — Master Project Specification

**Purpose of this document**: This is the single source of truth for what this project is and how it works. Any new Claude or Claude Code session should read this document first and treat it as the authoritative spec. If anything in a conversation contradicts this document, this document wins unless the user explicitly says otherwise.

This document is separate from `CLAUDE.md` (which tracks build *progress* — what's done, what's next). This document defines *what the product is and how each version behaves* and should rarely need to change once agreed.

---

## 1. What this project is

A web platform that constructs optimized virtual investment portfolios from a user-provided list of stocks, using established portfolio construction theory (Modern Portfolio Theory and its extensions). There is no user login. The user is not buying real securities — this is a portfolio *construction and analysis* tool, not a trading platform.

The project is built in three versions, each a distinct portfolio-construction methodology, layered on the same underlying data pipeline:

- **V1**: Four portfolios built with classic mean-variance optimization (Markowitz), for users who want a purely data-driven, theory-standard output.
- **V2**: Risk Parity — for users who have no market views/opinions and want a portfolio built purely from risk characteristics.
- **V3**: Black-Litterman — for users who *do* have market views/opinions and want those opinions incorporated into the optimization.

All three versions share the same data ingestion, the same stock universe input, and the same general UI pattern (input stocks → see constructed portfolio(s) → see weight per stock).

---

## 2. Shared architecture (applies to V1, V2, and V3)

### 2.1 User input
- User provides a list of **10 or more stock tickers**, all belonging to the single market selected for the session (see Section 2.6). There is no per-stock exchange tag.
- The system must map the selected market → correct ticker suffix/format for the data source (e.g. `.NS` for NSE, `.AX` for ASX, plain ticker for US exchanges).
- No login, no account, no saved user profile. Each session is a fresh input.

### 2.2 Data fetching
- Historical price data is fetched from a public data source (e.g. `yfinance` in Python, or `yahoo-finance2` in Node) for each ticker.
- Lookback window: 3–5 years of historical data (daily or monthly granularity — daily preferred for more precise covariance estimation, monthly acceptable if data availability across the selected market's stocks is inconsistent).
- Dividend yield (trailing twelve months) is fetched per ticker from the same source for use in the max-dividend portfolio (V1) and general reference.
- The selected market's 10-year government bond yield is fetched for use as the risk-free rate in the Max Sharpe portfolio (see Section 3.4).
- No historical data is currently stored in a database across sessions — each request fetches fresh (a future optimization could cache this, but it is not required for V1–V3).

### 2.3 Core calculations (computed once per request, reused across all portfolio types)
- **Periodic returns** per stock: calculated from the fetched price series.
- **Expected return (μ)** per stock: annualized mean of historical returns. *Note: this is the raw historical-mean estimate used directly in V1. V3 (Black-Litterman) replaces this input with a different derivation — see Section 5.*
- **Risk (σ)** per stock: annualized standard deviation of historical returns.
- **Covariance matrix (Σ)** across all stocks in the user's list: this is the single most important shared artifact — it captures how stocks move together and is reused, unmodified, across V1, V2, and V3.

### 2.4 Diversification constraints (apply to every portfolio in every version)
- Minimum number of stocks with a non-trivial weight: **5** (default; user may lower this if they explicitly choose to).
- Maximum weight for any single stock: capped (suggested default 30–40%, this can be a tunable parameter, not hardcoded) — this exists specifically to prevent the optimizer from concentrating capital into one or two names, which unconstrained mean-variance optimization will otherwise do.
- Weights are non-negative (no short-selling) and must sum to 1 (100% allocation) in every individual portfolio.

### 2.5 Output format (applies to every portfolio in every version)
- For each portfolio produced, output is a list of `{stock, weight %}` pairs. Weight is the percentage of that specific portfolio, not a share of some combined total across multiple portfolios.
- The system does **not** need to show how capital is split across multiple portfolios simultaneously (e.g. "60% in Max Return, 40% in Min Risk") — each portfolio type is a self-contained, independent 100% allocation.
- Optionally display each portfolio's resulting aggregate expected return, risk, dividend yield, or Sharpe ratio (whichever are relevant to that portfolio type) so the user can see the trade-off between portfolio types at a glance.

### 2.6 Market selection (one market per session)
- At the start of each session the user explicitly selects exactly one market: India (NSE), Australia (ASX), or USA. No market is pre-selected. A session never mixes markets.
- India means NSE only; BSE listings are not supported and are flagged as outside the selected market.
- Every stock the user enters is assumed to belong to the selected market. Name/ticker resolution is scoped to the selected market only.
- Anything that does not look like it belongs to the selected market (wrong exchange, wrong currency, wrong ticker suffix, or a foreign or dual listing) must be flagged to the user, not silently included. The user is never blocked: they can skip a flagged stock, or override the flag and include it.
- Switching market during a session asks the user for confirmation first. For now, confirming the switch clears the session's progress (entered stocks and all results).
- Because a session has exactly one market, all stocks in a session share one currency. Currency conversion and cross-market portfolios remain out of scope (see Section 6).
- **Open decision** (to be confirmed during implementation and recorded in CLAUDE.md): the exact criteria for flagging a stock as a foreign or dual listing.

---

## 3. V1 — Mean-Variance Optimization (Markowitz), 4 Portfolios

**Theoretical basis**: Modern Portfolio Theory (Harry Markowitz, 1952). A portfolio's risk is not simply the average of its components' individual risks — it depends heavily on the covariance between assets. Given expected returns and a covariance matrix, one can mathematically solve for the weight allocation that optimizes a given objective, subject to constraints.

V1 produces **four independent portfolios**, each solving a different constrained optimization problem using the same μ, Σ, and constraints from Section 2:

### 3.1 Max Return Portfolio
- **Objective**: maximize Σ(w_i × μ_i)
- **Note**: this is a linear objective — without the diversification constraints in Section 2.4, the mathematically "optimal" answer is trivially 100% in the single highest-expected-return stock. The diversification constraints (min 5 stocks, max weight cap) are what make this portfolio meaningful rather than degenerate.

### 3.2 Min Risk Portfolio (Global Minimum Variance Portfolio)
- **Objective**: minimize w^T Σ w (portfolio variance)
- **Method**: quadratic programming (e.g. `scipy.optimize.minimize` with SLSQP, or `cvxpy`).
- This is the portfolio with the lowest possible volatility given the constraints — it does not consider expected return at all.

### 3.3 Max Dividend / Passive Income Portfolio
- **Objective**: maximize Σ(w_i × dividend_yield_i)
- Uses the trailing-twelve-month dividend yield fetched in Section 2.2, same constraints as above.

### 3.4 Max Sharpe Ratio Portfolio (Tangency Portfolio)
- **Objective**: maximize (Σ(w_i × μ_i) − r_f) / sqrt(w^T Σ w)
- Where r_f is the risk-free rate: the selected market's 10-year government bond yield (India 10Y, Australia 10Y or US 10Y; see Section 2.6). The user can override it manually. The app must show the value used, its source and its as-of date, and must say explicitly when a fallback value is being used instead of a live one.
- Data source for the 10-year yield: Bloomberg (bloomberg.com) government bond pages.
  - **Open decision** (to be confirmed during implementation and recorded in CLAUDE.md): how India's 10-year yield is obtained, since no Bloomberg page for it was found in an initial check.
  - **Open decision** (to be confirmed during implementation and recorded in CLAUDE.md): what the fallback values are, how they are stored, and how they are kept up to date.
- This is the portfolio with the best risk-adjusted return and is the point on the efficient frontier a rational risk-neutral-on-a-per-unit-of-risk-basis investor would choose.
- Solved via the same optimizer family as the other three, with a nonlinear objective (or transformed into a quadratic programming form, a standard technique for tangency portfolio solving).

**V1 is fully theory-standard and requires no subjective input from the user beyond their stock list.**

---

## 4. V2 — Risk Parity

**Theoretical basis**: Rather than optimizing for expected return (which requires an estimate that is inherently uncertain and, as discussed in Section 5, unreliable when derived naively from historical averages), Risk Parity allocates capital so that **each stock contributes equally to total portfolio risk**. This approach requires no expected-return estimate at all — only the covariance matrix (Σ), which is already computed in Section 2.3. This is the methodology behind well-known real-world strategies (e.g. Bridgewater's "All Weather" fund).

### 4.1 Who this is for
Users who have no specific market opinions or return expectations and want a portfolio constructed purely from historical risk/co-movement characteristics.

### 4.2 The math
- Each stock's **risk contribution** to the total portfolio is: RC_i = w_i × (Σw)_i
- The objective is to find the weight vector w such that RC_i is equal across all i (every stock contributes the same amount of risk to the portfolio, not the same amount of capital).
- This means: a highly volatile stock (or one highly correlated with others) receives a *smaller* weight; a stable, less-correlated stock receives a *larger* weight — even though no return expectations were used at all.
- **Method**: constrained optimization minimizing the variance of risk contributions across stocks (i.e., minimize the spread between each stock's RC_i and the average RC), subject to the same Section 2.4 constraints (weights sum to 1, non-negative, diversification floor/cap).
- Libraries: the `riskparityportfolio` Python package implements this directly; alternatively, a custom objective function in `scipy.optimize` works.

### 4.3 What changes vs. V1
- **No expected return (μ) is used anywhere in this calculation.** This is the defining difference from every V1 portfolio.
- Same covariance matrix (Σ), same data pipeline, same constraints, same output format as V1 — this is purely a different objective function fed into a similarly-structured optimizer.

### 4.4 Output
- One portfolio: `{stock, weight %}` pairs, same format as V1, labeled "Risk Parity Portfolio."
- Optionally show each stock's risk contribution percentage alongside its weight, to visually demonstrate the "equal risk, unequal capital" principle — this is a strong visual for demonstrating the concept to someone unfamiliar with it.

---

## 5. V3 — Black-Litterman Model

**Theoretical basis**: Developed by Fischer Black and Robert Litterman at Goldman Sachs (1990). This model exists to fix a specific, well-documented flaw in V1's approach: raw historical average returns (μ) are extremely noisy estimators, and mean-variance optimization is known to amplify that noise ("error maximization") — small differences in historical average return, some of which are just noise, cause the optimizer to produce extreme, unstable, unintuitive weight allocations. Black-Litterman replaces the historical-mean input with a more robust, two-layer estimate of expected returns, then feeds that improved estimate into the *same* optimizer built for V1.

### 5.1 Who this is for
Users who *do* have a market opinion or view on one or more specific stocks and want that opinion incorporated into portfolio construction, rather than relying purely on historical averages (V1) or ignoring returns entirely (V2).

### 5.2 Layer 1 — Equilibrium returns (the prior)
- Instead of starting from the historical mean, Black-Litterman starts by reverse-engineering the expected returns that would make the current **market-cap-weighted portfolio** the mathematically optimal one, under the assumption that markets are roughly in equilibrium.
- Formula: `π = δ × Σ × w_market`
  - `π` = implied equilibrium expected returns (this replaces raw historical μ as the starting point)
  - `δ` = a risk-aversion constant (a reasonable default can be hardcoded or made configurable, e.g. 2.5)
  - `Σ` = the same covariance matrix from Section 2.3
  - `w_market` = market-capitalization weights of the user's chosen stocks (this is a **new data requirement** not present in V1/V2 — market cap must be fetched per ticker from the same public data source)

### 5.3 Layer 2 — Investor views (the update)
- The user provides one or more views on specific stocks, either:
  - **Absolute view**: "Stock A will return X% annually"
  - **Relative view**: "Stock A will outperform Stock B by X%"
- Each view has an associated **confidence level** (how certain the user is).
- These views are encoded as:
  - `P` = the "picking matrix" mapping each view to the specific stock(s) it concerns
  - `Q` = the vector of view return values
  - `Ω` = a matrix representing the uncertainty/confidence of each view (higher confidence = lower uncertainty value)
- **Bayesian blending formula** (combines the equilibrium prior with the views):
  `E[R] = [(τΣ)^-1 + P^T Ω^-1 P]^-1 × [(τΣ)^-1 π + P^T Ω^-1 Q]`
  - `τ` = a scalar representing uncertainty in the equilibrium estimate itself (a small constant, commonly in the range 0.01–0.05)
  - The output, `E[R]`, is a blended expected-return vector: it stays close to the equilibrium prior (π) wherever the user has no view or low confidence, and shifts toward the user's stated view wherever confidence is high.
- Library support: `PyPortfolioOpt` includes a `BlackLittermanModel` class that implements this directly, reducing the need to hand-code the matrix algebra.

### 5.4 Layer 3 — Optimization (reuses V1's optimizer)
- The blended expected-return vector `E[R]` from Section 5.3 replaces the raw historical μ that V1 uses as input.
- Everything else — the same covariance matrix Σ, the same diversification constraints from Section 2.4, the same optimizer (mean-variance quadratic programming) — is reused **unchanged** from V1's implementation.
- This means Black-Litterman should be built as an additional expected-return estimation module that plugs into the existing V1 optimizer, not as a separate portfolio-construction pipeline.

### 5.5 What changes vs. V1
| Component | V1 | V3 |
|---|---|---|
| Expected return input | Raw historical mean (μ) | Black-Litterman blended posterior (E[R]) |
| Covariance matrix | Computed from history | Identical, reused as-is |
| Optimizer | Mean-variance QP | Identical, reused as-is |
| New data required | None beyond V1 | Market-cap weights per stock |
| New user input required | None | Views (which stock(s), expected return or relative outperformance, confidence level) |

### 5.6 Output
- One portfolio (or the user can additionally see the max-Sharpe or min-variance variant computed using the *new* Black-Litterman returns instead of the old historical ones, as an optional enhancement) labeled "Black-Litterman Portfolio."
- If it helps demonstrate the concept, the UI can show the portfolio both with and without the user's views applied (views vs. pure equilibrium) side by side, to visually illustrate how the user's stated opinion shifted the allocation.

---

## 6. Explicit non-goals (to avoid scope creep or ambiguity)

- No real trading, brokerage integration, or real-money execution — this is a construction/analysis tool only.
- No user accounts, login, or saved portfolio history across sessions in V1–V3.
- No requirement to show a combined "how much of my total capital goes into which portfolio type" view — each portfolio type is independently 100% allocated.
- No historical backtesting, Monte Carlo simulation, resampling (Michaud), Hierarchical Risk Parity, VaR/CVaR, or currency normalization across exchanges are in scope for V1–V3. These were discussed as *possible future extensions* but are explicitly deferred and should not be built unless the user explicitly requests a new version (V4+) for them.
- No cross-market portfolios: each session uses exactly one market (see Section 2.6). Currency conversion remains out of scope.

## 7. Build order

1. **V1** (Markowitz, 4 portfolios) — build and fully validate first. This establishes the data pipeline, covariance calculation, and optimizer that both V2 and V3 depend on.
2. **V2** (Risk Parity) — built on the same data pipeline and covariance matrix as V1; adds a new objective function only. Lower build risk, faster to validate correctness (a volatile stock should visibly receive a smaller weight).
3. **V3** (Black-Litterman) — built last, since it is the most complex and highest-risk-of-subtle-bugs component. By the time this is built, the underlying data pipeline and optimizer will already be proven correct from V1 and V2, isolating Black-Litterman-specific work to the new equilibrium-returns and views-blending module described in Section 5.

## 8. How to use this document

- Any new Claude or Claude Code session working on this project should read this document in full before making design decisions.
- This document should be treated as stable and authoritative. It should only be edited when the user explicitly changes project scope or requirements — not silently reinterpreted or "improved upon" by an assistant mid-session.
- Day-to-day build status, decisions log, and "what's next" tracking belongs in the separate `CLAUDE.md` file, not this document.

## 9. Revision history
- **2026-10-07**: One market per session (India NSE, Australia ASX or USA); stocks that don't appear to belong to the selected market are flagged, never silently included, and never block the user. Max Sharpe's risk-free rate is now the selected market's 10-year government bond yield (user-overridable, with value, source, as-of date and any fallback shown). Changed: Sections 2.1, 2.2, 2.6 (new), 3.4, 6, 9 (new).
