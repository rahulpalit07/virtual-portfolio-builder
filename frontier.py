"""Efficient frontier under the same rules as the portfolios (PROJECT_SPEC.md Section 3.4 chart).

Pure calculations, no Streamlit. Sweeps target returns between the Min Risk and Max Return
portfolios and, at each target, finds the lowest-risk portfolio that reaches it, using the
shared optimizer (`optimizer.optimize`) with the same constraints: 30% cap, 2.5% floor,
minimum stock count. The swap-improvement step is skipped for sweep points (it made the
sweep ~18x slower); the actual Min Risk, Max Sharpe and Max Return portfolios are then added
to the curve so it passes exactly through what the optimizer produced.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from optimizer import Check, Constraints, Objective, optimize

FRONTIER_POINTS = 20  # target returns swept between Min Risk and Max Return
FRONTIER_TOLERANCE = 0.001  # 0.1 percentage point of risk, for the "on the frontier" check


@dataclass
class Frontier:
    curve: pd.DataFrame  # efficient points incl. anchors: columns risk, expected_return, label
    sweep: pd.DataFrame  # swept points only (before adding the portfolios)
    points_requested: int
    points_solved: int
    # The actual portfolios (Min Risk, Max Return, ...), kept separately: when two coincide
    # (e.g. Max Sharpe = Max Return), the curve keeps only one label for that point.
    anchors: pd.DataFrame = None


def _risk_return(w: np.ndarray, S: np.ndarray, m: np.ndarray) -> tuple[float, float]:
    return float(np.sqrt(max(w @ S @ w, 0.0))), float(w @ m)


def _efficient(points: pd.DataFrame) -> pd.DataFrame:
    """Keep only efficient points: sorted by risk, each must have a higher return than every
    lower-risk point kept so far (drops points that are both riskier and lower-returning)."""
    points = points.sort_values(["risk", "expected_return"], ascending=[True, False])
    keep, best = [], -np.inf
    for i, row in points.iterrows():
        if row.expected_return > best + 1e-12:
            keep.append(i)
            best = row.expected_return
    return points.loc[keep].reset_index(drop=True)


def efficient_frontier(
    cov: pd.DataFrame,
    mu: pd.Series,
    constraints: Constraints,
    anchors: dict[str, pd.Series],
    n_points: int = FRONTIER_POINTS,
) -> Frontier:
    """`anchors` must include "Min Risk" and "Max Return" weights (the two ends of the
    curve) and may include others (e.g. "Max Sharpe") to add exactly onto the curve.
    `cov` must come from `prepare_covariance`."""
    tickers = list(cov.index)
    S = cov.to_numpy()
    m = mu[tickers].to_numpy()
    variance = Objective("Portfolio variance", lambda w: float(w @ S @ w), lambda w: 2 * S @ w)

    r_low = float(anchors["Min Risk"][tickers].to_numpy() @ m)
    r_high = float(anchors["Max Return"][tickers].to_numpy() @ m)
    targets = np.linspace(r_low, r_high, n_points)[1:-1]  # the ends are the anchors

    swept = []
    for t in targets:
        target = {"type": "ineq", "fun": lambda w, t=t: float(w @ m) - t, "jac": lambda w: m}
        res = optimize(variance, tickers, constraints, extra=[target], swaps=False)
        if res.ok:
            risk, ret = _risk_return(res.weights.to_numpy(), S, m)
            swept.append({"risk": risk, "expected_return": ret, "label": ""})
    sweep = pd.DataFrame(swept, columns=["risk", "expected_return", "label"])

    anchor_rows = [
        {**dict(zip(("risk", "expected_return"), _risk_return(w[tickers].to_numpy(), S, m))), "label": name}
        for name, w in anchors.items()
    ]
    anchor_df = pd.DataFrame(anchor_rows, columns=["risk", "expected_return", "label"])
    curve = _efficient(pd.concat([sweep, anchor_df], ignore_index=True))
    return Frontier(
        curve=curve,
        sweep=sweep,
        points_requested=len(targets),
        points_solved=len(sweep),
        anchors=anchor_df,
    )


def frontier_check(
    frontier: Frontier, risk: float, expected_return: float, ends: list[str] = ("Min Risk", "Max Return")
) -> Check:
    """Is a portfolio on or left of the swept frontier? Compares its risk with the frontier's
    risk at the same expected return (interpolated between swept points and the two ends;
    the portfolio itself is not part of this comparison curve)."""
    ref = frontier.anchors[frontier.anchors.label.isin(ends)]
    pts = _efficient(pd.concat([frontier.sweep, ref], ignore_index=True)).sort_values("expected_return")
    frontier_risk = float(np.interp(expected_return, pts.expected_return, pts.risk))
    gap = risk - frontier_risk
    return Check(
        "Lies on (or left of) the efficient frontier",
        gap <= FRONTIER_TOLERANCE,
        f"Risk {risk:.2%} vs frontier risk {frontier_risk:.2%} at the same expected return "
        f"({expected_return:.2%}); difference {gap * 100:+.2f} percentage points "
        f"(allowed up to +{FRONTIER_TOLERANCE * 100:.1f})",
    )
