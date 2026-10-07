"""Portfolio optimization (PROJECT_SPEC.md Sections 2.4 and 3).

Pure calculations, no Streamlit. The constraint handling in `optimize` is generic: each
portfolio type (Min Risk, Max Return, Max Dividend, Max Sharpe) supplies only its objective.

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
import time
from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import pandas as pd
from scipy.optimize import minimize

# ---- Constraint parameters: the single place to change them --------------------------
MAX_WEIGHT = 0.30  # maximum weight in any single stock
MIN_WEIGHT = 0.025  # minimum weight for a stock that is held (otherwise exactly 0%)
MIN_STOCKS = 4  # default minimum number of stocks held (user can change it in the UI)

RISK_FREE_RATE = 0.04  # default for Max Sharpe (user can change it in the UI)

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


# Extra constraint on the full weight vector, scipy style:
# {"type": "ineq" (fun(w) >= 0) or "eq" (fun(w) == 0), "fun": w -> float, "jac": w -> array}
ExtraConstraint = dict


def _solve(
    obj: Objective,
    n: int,
    idx: list[int],
    lb: float,
    ub: float,
    extra: list[ExtraConstraint] = (),
) -> tuple[np.ndarray | None, str]:
    """Minimize `obj` with only stocks `idx` allowed, each bounded to [lb, ub], summing to 1,
    plus any `extra` constraints (e.g. a target return for the efficient frontier).

    Returns (full weight vector or None, message). Retries once from a different start.
    """
    k = len(idx)

    def embed(x: np.ndarray) -> np.ndarray:
        w = np.zeros(n)
        w[idx] = x
        return w

    constraints = [{"type": "eq", "fun": lambda x: x.sum() - 1, "jac": lambda x: np.ones(k)}]
    for e in extra:
        constraints.append({
            "type": e["type"],
            "fun": lambda x, e=e: e["fun"](embed(x)),
            "jac": lambda x, e=e: e["jac"](embed(x))[idx],
        })

    def satisfied(x: np.ndarray) -> bool:
        if not (np.all(x >= lb - TOLERANCE) and np.all(x <= ub + TOLERANCE)):
            return False
        for con in constraints:
            v = con["fun"](x)
            if (con["type"] == "eq" and abs(v) > TOLERANCE) or (con["type"] == "ineq" and v < -TOLERANCE):
                return False
        return True

    starts = [np.full(k, 1 / k), np.random.default_rng(0).dirichlet(np.ones(k))]
    message = ""
    for x0 in starts:
        res = minimize(
            lambda x: obj.fun(embed(x)),
            x0,
            jac=lambda x: obj.jac(embed(x))[idx],
            method="SLSQP",
            bounds=[(lb, ub)] * k,
            constraints=constraints,
            options={"ftol": 1e-15, "maxiter": 1000},
        )
        if res.success and satisfied(res.x):
            return embed(res.x), res.message
        message = res.message
    return None, f"Solver did not converge: {message}"


def optimize(
    obj: Objective,
    tickers: list[str],
    c: Constraints,
    extra: list[ExtraConstraint] = (),
    swaps: bool = True,
) -> PortfolioResult:
    """Generic constrained optimizer: drop-and-re-solve for the 0%-or-≥floor rule.

    Always minimizes `obj`; maximizing portfolios pass a negated objective (see Objective).
    Any covariance matrix the objective uses must come from `prepare_covariance`.
    `extra` adds constraints (e.g. target return); `swaps=False` skips the swap
    improvement (used for efficient-frontier points, where it would be too slow).
    """
    n = len(tickers)
    err = feasibility_error(n, c)
    if err:
        return PortfolioResult(weights=None, error=err)

    # Lower bound: the same problem without the floor and minimum-count rules
    relaxed, msg = _solve(obj, n, list(range(n)), 0.0, c.max_weight, extra)
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
        w, msg = _solve(obj, n, idx, 0.0, c.max_weight, extra)
        if w is None:
            return PortfolioResult(weights=None, lower_bound=lower_bound, error=msg)

    # Final solve: every remaining stock held between the floor and the cap
    w, msg = _solve(obj, n, idx, c.min_weight, c.max_weight, extra)
    if w is None:
        return PortfolioResult(weights=None, lower_bound=lower_bound, error=msg)

    notes = []
    if swaps:
        w, timed_out = _improve_by_swaps(obj, n, idx, w, c, extra)
        if timed_out:
            notes.append(
                f"The swap-improvement step stopped after {SWAP_TIME_LIMIT:.0f} s to keep the app "
                "responsive; the result may be slightly short of the best possible."
            )

    w[np.abs(w) < ZERO] = 0.0
    weights = pd.Series(w, index=tickers)
    checks = verify_constraints(weights, c)
    result = PortfolioResult(
        weights=weights,
        objective_value=obj.fun(w),
        lower_bound=lower_bound,
        checks=checks,
        notes=notes,
    )
    if not all(ch.passed for ch in checks if ch.applicable):
        result.error = "The optimized weights break at least one rule (see checks below)."
    return result


MAX_SWAP_PASSES = 10
SWAP_TIME_LIMIT = 5.0  # seconds; keeps large lists responsive on Streamlit Cloud


def _improve_by_swaps(
    obj: Objective,
    n: int,
    idx: list[int],
    w: np.ndarray,
    c: Constraints,
    extra: list[ExtraConstraint] = (),
) -> tuple[np.ndarray, bool]:
    """Local search: swap one held stock for one excluded stock while that lowers the
    objective. Fixes cases where dropping the smallest position first kept the wrong set
    (mainly when the minimum-count rule binds). Returns (weights, timed_out)."""
    start = time.monotonic()
    best = obj.fun(w)
    for _ in range(MAX_SWAP_PASSES):
        improved = False
        for out in list(idx):
            for into in (j for j in range(n) if j not in idx):
                if time.monotonic() - start > SWAP_TIME_LIMIT:
                    return w, True
                trial = [into if i == out else i for i in idx]
                tw, _ = _solve(obj, n, trial, c.min_weight, c.max_weight, extra)
                if tw is not None and obj.fun(tw) < best - 1e-12:
                    idx[:], w, best, improved = trial, tw, obj.fun(tw), True
                    break
            if improved:
                break
        if not improved:
            break
    return w, False


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


def sharpe_ratio(expected_return: float, risk: float, risk_free_rate: float) -> float:
    return (expected_return - risk_free_rate) / risk if risk > 0 else float("nan")


def portfolio_stats(
    weights: pd.Series,
    mu: pd.Series,
    cov: pd.DataFrame,
    dividend_yield: pd.Series,
    risk_free_rate: float | None = None,
) -> dict[str, float]:
    """Weighted expected return, annualized risk, weighted dividend yield and (if a
    risk-free rate is given) Sharpe ratio. Missing dividend yields count as 0%.
    """
    w = weights.to_numpy()
    S = cov.loc[weights.index, weights.index].to_numpy()
    stats = {
        "expected_return": float(w @ mu[weights.index].to_numpy()),
        "risk": math.sqrt(max(float(w @ S @ w), 0.0)),
        "dividend_yield": float(w @ dividend_yield[weights.index].fillna(0).to_numpy()),
    }
    if risk_free_rate is not None:
        stats["sharpe"] = sharpe_ratio(stats["expected_return"], stats["risk"], risk_free_rate)
    return stats


def equal_weights(tickers: list[str]) -> pd.Series:
    return pd.Series(1 / len(tickers), index=tickers)


def equal_weight_is_valid(n: int, c: Constraints) -> bool:
    """Equal weight is a fair benchmark only if it obeys the rules itself."""
    return c.min_held <= n <= c.max_stocks_for_floor


def _benchmark_check(name: str, passed: bool, detail: str, n: int, c: Constraints) -> Check:
    if equal_weight_is_valid(n, c):
        return Check(name, passed, detail)
    return Check(
        name,
        True,
        f"Not applicable: an equal-weight portfolio of {n} stocks breaks the rules itself "
        f"(needs {c.min_held}–{c.max_stocks_for_floor} stocks).",
        applicable=False,
    )


def _flag_failed_checks(result: PortfolioResult) -> None:
    if not all(ch.passed for ch in result.checks if ch.applicable):
        result.error = "The optimized portfolio failed at least one check (see below)."


# ---- Max Return and Max Dividend (Sections 3.1 and 3.3): linear objectives ------------
def exact_linear_optimum(values: pd.Series, c: Constraints) -> pd.Series:
    """Exact best portfolio for maximizing a weighted sum (return or yield) under the rules.

    Hold exactly the top `min_held` stocks (holding more only forces weight onto worse
    stocks): give each the floor, then hand out the rest in order, up to the cap.
    E.g. min 4 → 30 / 30 / 30 / 10. Used to verify the optimizer's answer.
    """
    top = values.sort_values(ascending=False, kind="stable").index[: c.min_held]
    w = pd.Series(0.0, index=values.index)
    w[top] = c.min_weight
    remaining = 1 - c.min_held * c.min_weight
    for s in top:
        add = min(c.max_weight - c.min_weight, remaining)
        w[s] += add
        remaining -= add
    return w


@dataclass
class LinearResult(PortfolioResult):
    value: float | None = None  # the maximized weighted return or yield
    equal_weight_value: float | None = None
    exact_value: float | None = None  # from exact_linear_optimum


def _linear_portfolio(
    values: pd.Series, c: Constraints, label: str, benchmark: pd.Series
) -> LinearResult:
    """Maximize Σ wᵢ·valueᵢ over the stocks in `values`. `benchmark` holds the values for
    all included stocks (for the equal-weight comparison)."""
    v = values.to_numpy()
    obj = Objective(f"Negative {label}", lambda w: -float(w @ v), lambda w: -v)
    base = optimize(obj, list(values.index), c)
    result = LinearResult(**vars(base))
    result.equal_weight_value = float(benchmark.mean())
    if not base.ok:
        return result

    result.value = -base.objective_value
    result.exact_value = float(exact_linear_optimum(values, c) @ values)
    result.checks.append(_benchmark_check(
        f"{label.capitalize()} is at least the equal-weight portfolio's",
        result.value >= result.equal_weight_value - TOLERANCE,
        f"Optimized {result.value:.2%} vs equal-weight {result.equal_weight_value:.2%}",
        len(benchmark),
        c,
    ))
    result.checks.append(Check(
        f"{label.capitalize()} matches the exact optimum",
        abs(result.value - result.exact_value) <= TOLERANCE,
        f"Optimized {result.value:.4%} vs exact {result.exact_value:.4%}",
    ))
    _flag_failed_checks(result)
    return result


def max_return_portfolio(mu: pd.Series, constraints: Constraints = Constraints()) -> LinearResult:
    """Maximize the weighted sum of each stock's annualized expected return (μ)."""
    return _linear_portfolio(mu, constraints, "expected return", benchmark=mu)


HIGH_YIELD = 0.08  # flagged "high, check"
IMPLAUSIBLE_YIELD = 0.15  # flagged "implausible"


@dataclass
class DividendFlags:
    missing: list[str] = field(default_factory=list)  # no dividend data (counted as 0%)
    non_payers: list[str] = field(default_factory=list)  # paid nothing in the last 12 months
    high: list[tuple[str, float]] = field(default_factory=list)
    implausible: list[tuple[str, float]] = field(default_factory=list)
    out_of_range: list[tuple[str, float]] = field(default_factory=list)  # <0 or >100%: unit error


def dividend_data_flags(yields: pd.Series) -> DividendFlags:
    """Data-quality flags for dividend yields. Yields are fractions (0.025 = 2.5%) computed
    in data.py as dividends ÷ price from the same price history, so a percent/fraction
    mix-up can't occur by construction; anything outside 0–100% is flagged as a unit error."""
    flags = DividendFlags()
    for s, y in yields.items():
        if pd.isna(y):
            flags.missing.append(s)
        elif y < 0 or y > 1:
            flags.out_of_range.append((s, y))
        elif y == 0:
            flags.non_payers.append(s)
        elif y > IMPLAUSIBLE_YIELD:
            flags.implausible.append((s, y))
        elif y > HIGH_YIELD:
            flags.high.append((s, y))
    return flags


def max_dividend_portfolio(
    yields: pd.Series, constraints: Constraints = Constraints()
) -> LinearResult:
    """Maximize the weighted TTM dividend yield, using dividend-paying stocks only (user
    decision). Missing yields count as 0% (non-payers). Errors if too few stocks pay."""
    clean = yields.fillna(0.0)
    payers = clean[(clean > 0) & (clean <= 1)]
    if len(payers) < constraints.min_held:
        return LinearResult(
            weights=None,
            equal_weight_value=float(clean.mean()),
            error=(
                f"Not enough stocks pay dividends to build this portfolio: {len(payers)} of "
                f"{len(clean)} stocks paid a dividend in the last 12 months, but at least "
                f"{constraints.min_held} are needed. Add more dividend-paying stocks."
            ),
        )
    result = _linear_portfolio(payers, constraints, "dividend yield", benchmark=clean)
    if result.weights is not None:
        result.weights = result.weights.reindex(clean.index, fill_value=0.0)
    return result


# ---- Max Sharpe (Section 3.4) ---------------------------------------------------------
@dataclass
class MaxSharpeResult(PortfolioResult):
    sharpe: float | None = None
    expected_return: float | None = None
    risk: float | None = None
    ceiling_sharpe: float | None = None  # best Sharpe without the floor / min-count rules
    equal_weight_sharpe: float | None = None
    risk_free_rate: float | None = None


def sharpe_ceiling(cov: pd.DataFrame, mu: pd.Series, risk_free_rate: float, c: Constraints) -> float | None:
    """Exact best Sharpe ratio WITHOUT the floor and minimum-count rules (cap only).

    No valid portfolio can beat it, so it bounds how far Max Sharpe could be from the true
    best. Solved exactly via the standard convex reformulation: with y = κ·w,
    minimize yᵀΣy subject to (μ − r_f)ᵀy = 1, Σy = κ, 0 ≤ y ≤ cap·κ; Sharpe = 1/√(yᵀΣy).
    Returns None if no portfolio beats the risk-free rate.
    """
    S = cov.to_numpy()
    ex = mu[cov.index].to_numpy() - risk_free_rate
    n = len(ex)
    cap = c.max_weight
    # Start from the best-excess-return portfolio under the cap alone (always feasible)
    cap_only = Constraints(max_weight=cap, min_weight=0.0, min_stocks=1)
    w0 = exact_linear_optimum(pd.Series(ex), cap_only).to_numpy()
    if ex @ w0 <= 0:
        return None
    z0 = np.r_[w0, 1.0] / (ex @ w0)
    res = minimize(
        lambda z: float(z[:n] @ S @ z[:n]),
        z0,
        jac=lambda z: np.r_[2 * S @ z[:n], 0.0],
        method="SLSQP",
        bounds=[(0, None)] * (n + 1),
        constraints=[
            {"type": "eq", "fun": lambda z: ex @ z[:n] - 1, "jac": lambda z: np.r_[ex, 0.0]},
            {"type": "eq", "fun": lambda z: z[:n].sum() - z[n], "jac": lambda z: np.r_[np.ones(n), -1.0]},
            {"type": "ineq", "fun": lambda z: cap * z[n] - z[:n], "jac": lambda z: np.c_[-np.eye(n), np.full(n, cap)]},
        ],
        options={"ftol": 1e-15, "maxiter": 2000},
    )
    if not res.success or res.fun <= 0:
        return None
    return 1 / math.sqrt(res.fun)


def max_sharpe_portfolio(
    cov: pd.DataFrame,
    mu: pd.Series,
    risk_free_rate: float = RISK_FREE_RATE,
    constraints: Constraints = Constraints(),
    compare: dict[str, pd.Series] | None = None,
) -> MaxSharpeResult:
    """Maximize (wᵀμ − r_f) / √(wᵀΣw). `cov` must come from `prepare_covariance`.

    `compare` maps portfolio names (e.g. Min Risk, Max Return) to weights; Max Sharpe must
    have a Sharpe ratio at least as high as each of them.
    """
    tickers = list(cov.index)
    S = cov.to_numpy()
    m = mu[tickers].to_numpy()
    rf = risk_free_rate

    err = feasibility_error(len(tickers), constraints)
    if err:
        return MaxSharpeResult(weights=None, error=err, risk_free_rate=rf)
    best_return = float(exact_linear_optimum(mu[tickers], constraints) @ m)
    if best_return <= rf:
        return MaxSharpeResult(
            weights=None,
            risk_free_rate=rf,
            error=(
                f"No portfolio that follows the rules beats the risk-free rate of {rf:.2%} "
                f"(the highest achievable expected return is {best_return:.2%}), so a Max "
                "Sharpe portfolio isn't meaningful. Lower the risk-free rate or add stocks "
                "with higher expected returns."
            ),
        )

    def neg_sharpe(w: np.ndarray) -> float:
        sd = math.sqrt(max(float(w @ S @ w), 1e-16))
        return -(float(w @ m) - rf) / sd

    def neg_sharpe_grad(w: np.ndarray) -> np.ndarray:
        var = max(float(w @ S @ w), 1e-16)
        sd = math.sqrt(var)
        return -(m / sd - (float(w @ m) - rf) * (S @ w) / (var * sd))

    base = optimize(Objective("Negative Sharpe ratio", neg_sharpe, neg_sharpe_grad), tickers, constraints)
    result = MaxSharpeResult(**vars(base), risk_free_rate=rf)
    ew = equal_weights(tickers).to_numpy()
    result.equal_weight_sharpe = -neg_sharpe(ew)
    result.ceiling_sharpe = sharpe_ceiling(cov, mu, rf, constraints)
    if not base.ok:
        return result

    w = base.weights.to_numpy()
    result.sharpe = -base.objective_value
    result.expected_return = float(w @ m)
    result.risk = math.sqrt(max(float(w @ S @ w), 0.0))

    result.checks.append(_benchmark_check(
        "Sharpe ratio is at least the equal-weight portfolio's",
        result.sharpe >= result.equal_weight_sharpe - TOLERANCE,
        f"Optimized {result.sharpe:.3f} vs equal-weight {result.equal_weight_sharpe:.3f}",
        len(tickers),
        constraints,
    ))
    for name, other in (compare or {}).items():
        other_sharpe = -neg_sharpe(other[tickers].to_numpy())
        result.checks.append(Check(
            f"Sharpe ratio is at least the {name} portfolio's",
            result.sharpe >= other_sharpe - TOLERANCE,
            f"Max Sharpe {result.sharpe:.3f} vs {name} {other_sharpe:.3f}",
        ))
    if result.ceiling_sharpe is not None:
        result.checks.append(Check(
            "Sharpe ratio does not exceed the theoretical ceiling",
            result.sharpe <= result.ceiling_sharpe + 1e-6,
            f"Optimized {result.sharpe:.4f} vs ceiling {result.ceiling_sharpe:.4f} "
            "(best possible without the 2.5% and minimum-stock rules)",
        ))
    _flag_failed_checks(result)
    return result
