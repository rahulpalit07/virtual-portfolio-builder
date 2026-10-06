"""Portfolio optimization (PROJECT_SPEC.md Sections 2.4 and 3).

Pure calculations, no Streamlit. The constraint handling in `optimize` is generic: each
portfolio type supplies only its objective (Min Risk now; Max Return, Max Dividend and
Max Sharpe later).

Constraints (Section 2.4, values decided by the user):
- weights sum to 100%, no short-selling;
- each stock is either excluded (exactly 0%) or held between MIN_WEIGHT and MAX_WEIGHT;
- at least MIN_STOCKS stocks held (user-adjustable in the UI).

The "0% or at least 2.5%" rule makes the problem non-convex, so it is solved by
drop-and-re-solve (user decision, method B): solve without the 2.5% floor, drop the
smallest position below the floor, re-solve, repeat; then solve once more with the floor
on every remaining stock. Not guaranteed optimal in theory, so the result is reported
alongside a lower bound (the same problem without the floor and minimum-count rules).
"""

import math
from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import pandas as pd
from scipy.optimize import minimize

# ---- Constraint parameters: the single place to change them --------------------------
MAX_WEIGHT = 0.30  # maximum weight in any single stock
MIN_WEIGHT = 0.025  # minimum weight for a stock that is held (otherwise exactly 0%)
MIN_STOCKS = 4  # default minimum number of stocks held (user can change it in the UI)

TOLERANCE = 1e-6  # 0.0001%: allowed numerical slack when verifying constraints
ZERO = 1e-9  # weights below this are cleaned to exactly 0


@dataclass(frozen=True)
class Constraints:
    max_weight: float = MAX_WEIGHT
    min_weight: float = MIN_WEIGHT
    min_stocks: int = MIN_STOCKS

    @property
    def stocks_needed_for_cap(self) -> int:
        """Fewest stocks that can reach 100% under the cap (4 for a 30% cap)."""
        return math.ceil(1 / self.max_weight - 1e-12)

    @property
    def max_stocks_for_floor(self) -> int:
        """Most stocks that can be held at the floor without exceeding 100% (40 for 2.5%)."""
        return math.floor(1 / self.min_weight + 1e-12)

    @property
    def min_held(self) -> int:
        return max(self.min_stocks, self.stocks_needed_for_cap)


@dataclass
class Objective:
    """Function to minimize over the full weight vector, with its gradient.

    Sign convention: `optimize` always MINIMIZES. A portfolio that maximizes something
    (Max Return, Max Dividend, Max Sharpe) must pass its negative, e.g. fun(w) = -(w @ mu),
    and negate `objective_value` / `lower_bound` back when displaying them.
    """

    name: str
    fun: Callable[[np.ndarray], float]
    jac: Callable[[np.ndarray], np.ndarray]


@dataclass
class Check:
    name: str
    passed: bool
    detail: str
    applicable: bool = True


@dataclass
class PortfolioResult:
    weights: pd.Series | None  # all stocks, 0 for excluded; None if no valid portfolio
    objective_value: float | None = None  # in the minimized sign (see Objective)
    # Best objective without the floor / min-count rules: no valid portfolio can beat it.
    # For maximizing objectives this is negated too (see Objective).
    lower_bound: float | None = None
    checks: list[Check] = field(default_factory=list)
    error: str | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.error is None and self.weights is not None

    @property
    def held(self) -> pd.Series:
        if self.weights is None:
            return pd.Series(dtype=float)
        return self.weights[self.weights > 0].sort_values(ascending=False)


def feasibility_error(n: int, c: Constraints) -> str | None:
    """Plain-English reason the constraints can't be met with n stocks, or None."""
    if c.min_held > c.max_stocks_for_floor:
        return (
            f"The minimum of {c.min_held} stocks can't be met: at a {c.min_weight:.1%} floor, "
            f"at most {c.max_stocks_for_floor} stocks fit in 100%. Lower the minimum number of stocks."
        )
    if n < c.min_held:
        if c.stocks_needed_for_cap >= c.min_stocks:
            return (
                f"{n} stock(s) available, but with a {c.max_weight:.0%} cap per stock, at least "
                f"{c.stocks_needed_for_cap} stocks are needed to reach 100%. Add more stocks."
            )
        return (
            f"{n} stock(s) available, but the minimum number of stocks held is set to "
            f"{c.min_stocks}. Add more stocks, or lower the minimum."
        )
    return None


def _solve(
    obj: Objective, n: int, idx: list[int], lb: float, ub: float
) -> tuple[np.ndarray | None, str]:
    """Minimize `obj` with only stocks `idx` allowed, each bounded to [lb, ub], summing to 1.

    Returns (full weight vector or None, message). Retries once from a different start.
    """
    k = len(idx)

    def embed(x: np.ndarray) -> np.ndarray:
        w = np.zeros(n)
        w[idx] = x
        return w

    starts = [np.full(k, 1 / k), np.random.default_rng(0).dirichlet(np.ones(k))]
    message = ""
    for x0 in starts:
        res = minimize(
            lambda x: obj.fun(embed(x)),
            x0,
            jac=lambda x: obj.jac(embed(x))[idx],
            method="SLSQP",
            bounds=[(lb, ub)] * k,
            constraints=[{"type": "eq", "fun": lambda x: x.sum() - 1, "jac": lambda x: np.ones(k)}],
            options={"ftol": 1e-15, "maxiter": 1000},
        )
        x = res.x
        in_bounds = np.all(x >= lb - TOLERANCE) and np.all(x <= ub + TOLERANCE)
        if res.success and in_bounds and abs(x.sum() - 1) <= TOLERANCE:
            return embed(x), res.message
        message = res.message
    return None, f"Solver did not converge: {message}"


def optimize(obj: Objective, tickers: list[str], c: Constraints) -> PortfolioResult:
    """Generic constrained optimizer: drop-and-re-solve for the 0%-or-≥floor rule.

    Always minimizes `obj`; maximizing portfolios pass a negated objective (see Objective).
    Any covariance matrix the objective uses must come from `prepare_covariance`.
    """
    n = len(tickers)
    err = feasibility_error(n, c)
    if err:
        return PortfolioResult(weights=None, error=err)

    # Lower bound: the same problem without the floor and minimum-count rules
    relaxed, msg = _solve(obj, n, list(range(n)), 0.0, c.max_weight)
    if relaxed is None:
        return PortfolioResult(weights=None, error=msg)
    lower_bound = obj.fun(relaxed)

    # Drop phase: remove the smallest position below the floor, re-solve, repeat
    idx = list(range(n))
    w = relaxed
    while len(idx) > c.min_held:
        below = [i for i in idx if w[i] < c.min_weight - TOLERANCE]
        if not below:
            break
        idx.remove(min(below, key=lambda i: w[i]))
        w, msg = _solve(obj, n, idx, 0.0, c.max_weight)
        if w is None:
            return PortfolioResult(weights=None, lower_bound=lower_bound, error=msg)

    # Final solve: every remaining stock held between the floor and the cap
    w, msg = _solve(obj, n, idx, c.min_weight, c.max_weight)
    if w is None:
        return PortfolioResult(weights=None, lower_bound=lower_bound, error=msg)

    w = _improve_by_swaps(obj, n, idx, w, c)

    w[np.abs(w) < ZERO] = 0.0
    weights = pd.Series(w, index=tickers)
    checks = verify_constraints(weights, c)
    result = PortfolioResult(
        weights=weights,
        objective_value=obj.fun(w),
        lower_bound=lower_bound,
        checks=checks,
    )
    if not all(ch.passed for ch in checks if ch.applicable):
        result.error = "The optimized weights break at least one rule (see checks below)."
    return result


MAX_SWAP_PASSES = 10


def _improve_by_swaps(
    obj: Objective, n: int, idx: list[int], w: np.ndarray, c: Constraints
) -> np.ndarray:
    """Local search: swap one held stock for one excluded stock while that lowers the
    objective. Fixes cases where dropping the smallest position first kept the wrong set
    (mainly when the minimum-count rule binds)."""
    best = obj.fun(w)
    for _ in range(MAX_SWAP_PASSES):
        improved = False
        for out in list(idx):
            for into in (j for j in range(n) if j not in idx):
                trial = [into if i == out else i for i in idx]
                tw, _ = _solve(obj, n, trial, c.min_weight, c.max_weight)
                if tw is not None and obj.fun(tw) < best - 1e-12:
                    idx[:], w, best, improved = trial, tw, obj.fun(tw), True
                    break
            if improved:
                break
        if not improved:
            break
    return w


def verify_constraints(weights: pd.Series, c: Constraints) -> list[Check]:
    w = weights.to_numpy()
    held = w[w > 0]
    total = w.sum()
    return [
        Check(
            "Weights sum to 100%",
            abs(total - 1) <= TOLERANCE,
            f"Sum: {total:.6%}",
        ),
        Check(
            "No negative weights (no short-selling)",
            bool(np.all(w >= -TOLERANCE)),
            f"Smallest weight: {w.min():.4%}",
        ),
        Check(
            f"No weight above {c.max_weight:.0%}",
            bool(np.all(w <= c.max_weight + TOLERANCE)),
            f"Largest weight: {w.max():.4%}",
        ),
        Check(
            f"No held weight below {c.min_weight:.1%}",
            bool(np.all(held >= c.min_weight - TOLERANCE)),
            f"Smallest held weight: {held.min():.4%}" if held.size else "No stocks held",
        ),
        Check(
            f"At least {c.min_stocks} stocks held",
            held.size >= c.min_stocks,
            f"Stocks held: {held.size}",
        ),
    ]


@dataclass
class PreparedCovariance:
    cov: pd.DataFrame  # the matrix every portfolio calculation must use
    repaired: bool
    note: str | None = None


def prepare_covariance(cov: pd.DataFrame) -> PreparedCovariance:
    """Shared step, run ONCE before building any portfolio. Every optimizer and every
    displayed portfolio figure must use the returned matrix, so they always agree."""
    fixed, repaired = nearest_psd(cov)
    note = (
        "The covariance matrix was not positive semi-definite (stocks have different "
        "history lengths), so it was adjusted to the nearest valid matrix. All portfolio "
        "calculations use the adjusted matrix."
        if repaired
        else None
    )
    return PreparedCovariance(fixed, repaired, note)


def nearest_psd(cov: pd.DataFrame) -> tuple[pd.DataFrame, bool]:
    """Clip negative eigenvalues to make the covariance matrix positive semi-definite.

    Returns (matrix, repaired). Unchanged if it was already PSD.
    """
    c = cov.to_numpy()
    vals, vecs = np.linalg.eigh((c + c.T) / 2)
    if vals.min() >= -1e-10 * max(np.abs(c).max(), 1.0):
        return cov, False
    fixed = vecs @ np.diag(np.clip(vals, 0, None)) @ vecs.T
    fixed = (fixed + fixed.T) / 2
    return pd.DataFrame(fixed, index=cov.index, columns=cov.columns), True


# ---- Min Risk portfolio (Section 3.2) ------------------------------------------------
@dataclass
class MinRiskResult(PortfolioResult):
    risk: float | None = None  # annualized σ of the optimized portfolio
    lower_bound_risk: float | None = None  # σ without the floor / min-count rules
    equal_weight_risk: float | None = None


def min_risk_portfolio(
    cov: pd.DataFrame, tickers: list[str] | None = None, constraints: Constraints = Constraints()
) -> MinRiskResult:
    """Global minimum variance portfolio: minimize wᵀΣw under the constraints.

    `cov` must be the matrix from `prepare_covariance` (already repaired if needed).
    """
    tickers = list(cov.index) if tickers is None else tickers
    S = cov.loc[tickers, tickers].to_numpy()

    variance = Objective("Portfolio variance", lambda w: float(w @ S @ w), lambda w: 2 * S @ w)
    base = optimize(variance, tickers, constraints)
    result = MinRiskResult(**vars(base))
    if base.lower_bound is not None:
        result.lower_bound_risk = math.sqrt(max(base.lower_bound, 0.0))

    # Equal weight across all stocks: a fair benchmark only if it obeys the rules itself
    n = len(tickers)
    ew = np.full(n, 1 / n)
    result.equal_weight_risk = math.sqrt(float(ew @ S @ ew))
    if not base.ok:
        return result

    result.risk = math.sqrt(max(base.objective_value, 0.0))
    name = "Optimized risk is no higher than equal-weight risk"
    if constraints.min_held <= n <= constraints.max_stocks_for_floor:
        result.checks.append(Check(
            name,
            result.risk <= result.equal_weight_risk + TOLERANCE,
            f"Optimized σ {result.risk:.2%} vs equal-weight σ {result.equal_weight_risk:.2%}",
        ))
    else:
        result.checks.append(Check(
            name,
            True,
            f"Not applicable: an equal-weight portfolio of {n} stocks breaks the rules itself "
            f"(needs {constraints.min_held}–{constraints.max_stocks_for_floor} stocks).",
            applicable=False,
        ))
    if not all(ch.passed for ch in result.checks if ch.applicable):
        result.error = "The optimized portfolio failed at least one check (see below)."
    return result


def portfolio_stats(
    weights: pd.Series, mu: pd.Series, cov: pd.DataFrame, dividend_yield: pd.Series
) -> dict[str, float]:
    """Weighted expected return, annualized risk and weighted dividend yield.

    Missing dividend yields count as 0%.
    """
    w = weights.to_numpy()
    S = cov.loc[weights.index, weights.index].to_numpy()
    return {
        "expected_return": float(w @ mu[weights.index].to_numpy()),
        "risk": math.sqrt(max(float(w @ S @ w), 0.0)),
        "dividend_yield": float(w @ dividend_yield[weights.index].fillna(0).to_numpy()),
    }
