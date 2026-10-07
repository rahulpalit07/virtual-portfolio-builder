"""Regression harness: drive the real app.py with frozen inputs and record every result.

Usage: python harness.py <output.json>
Inputs come from snapshot.pkl (no live Yahoo/CNBC calls, frozen clock), so baseline and
later runs see identical data. Records the outputs of every calculation function the app
calls (portfolios, displayed portfolio stats, frontier), keyed by market and scenario.
"""
import copy, json, os, pickle, sys

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(REPO); sys.path.insert(0, REPO)

import data, rates, stats, optimizer, frontier  # noqa: E402
from streamlit.testing.v1 import AppTest  # noqa: E402

snap = pickle.load(open(os.path.join(HERE, "snapshot.pkl"), "rb"))

# ---- frozen inputs ------------------------------------------------------------------
data.resolve = lambda q, m: copy.deepcopy(snap["resolve"][(q.strip(), m)])
data.listing_currency = lambda s: snap["currency"].get(s)
data.fetch_ticker_data = lambda s, m, q="", n=None: copy.deepcopy(snap["fetch"][(s, m)])
rates.risk_free_rate = lambda m: copy.deepcopy(snap["rf"][m])
_compute = stats.compute_stats
stats.compute_stats = lambda stocks, now=None: _compute(stocks, now=snap["now"])

# ---- recording wrappers -----------------------------------------------------------------
REC = {}
CTX = {"key": None}


def f(x):
    return None if x is None else repr(float(x))


def weights(w):
    return None if w is None else {k: repr(float(v)) for k, v in w.items()}


def checks(r):
    return [(c.name, bool(c.passed), bool(c.applicable)) for c in getattr(r, "checks", [])]


def wrap(mod, name, summarise):
    orig = getattr(mod, name)

    def inner(*a, **k):
        out = orig(*a, **k)
        REC.setdefault(CTX["key"], {}).setdefault(name, {}).update(summarise(out, a, k))
        return out
    setattr(mod, name, inner)


wrap(optimizer, "min_risk_portfolio", lambda r, a, k: {"x": {
    "weights": weights(r.weights), "risk": f(r.risk), "floor": f(r.lower_bound_risk),
    "ew_risk": f(r.equal_weight_risk), "error": r.error, "checks": checks(r)}})
for nm in ("max_return_portfolio", "max_dividend_portfolio"):
    wrap(optimizer, nm, lambda r, a, k: {"x": {
        "weights": weights(r.weights), "value": f(r.value), "ew": f(r.equal_weight_value),
        "exact": f(r.exact_value), "error": r.error, "checks": checks(r)}})
wrap(optimizer, "max_sharpe_portfolio", lambda r, a, k: {repr(float(a[2] if len(a) > 2 else k["risk_free_rate"])): {
    "weights": weights(r.weights), "sharpe": f(r.sharpe), "ret": f(r.expected_return),
    "risk": f(r.risk), "ceiling": f(r.ceiling_sharpe), "ew": f(r.equal_weight_sharpe),
    "error": r.error, "checks": checks(r)}})
wrap(optimizer, "portfolio_stats", lambda r, a, k: {
    json.dumps(weights(a[0]), sort_keys=True) + "|" + repr(a[4] if len(a) > 4 else k.get("risk_free_rate")):
    {kk: f(v) for kk, v in r.items()}})
wrap(frontier, "efficient_frontier", lambda r, a, k: {"x": {
    "curve": [(f(x), f(y), lab) for x, y, lab in r.curve[["risk", "expected_return", "label"]].itertuples(index=False)],
    "solved": r.points_solved}})
wrap(frontier, "frontier_check", lambda r, a, k: {"x": (r.passed, r.detail)})


# ---- drive the app ------------------------------------------------------------------------
def first(items, pred):
    return next((x for x in items if pred(x)), None)


def run_market(market):
    at = AppTest.from_file(os.path.join(REPO, "app.py"), default_timeout=900)
    at.run()
    at.radio[0].set_value(market).run()
    at.session_state["resolutions"] = [data.resolve(q, market) for q in snap["lists"][market]]
    at.run()
    build = first(at.button, lambda b: b.label.startswith(("Fetch", "Build")))
    CTX["key"] = f"{market} | default"
    build.click().run()
    excs = [str(e.value)[:200] for e in at.exception]

    # scenario 2: minimum 5 stocks, risk-free rate 6%
    CTX["key"] = f"{market} | min5_rf6"
    first(at.number_input, lambda n: n.label.startswith("Minimum number")).set_value(5).run()
    first(at.number_input, lambda n: n.label.startswith("Risk-free")).set_value(6.0).run()
    excs += [str(e.value)[:200] for e in at.exception]
    errors = [e.value[:150] for e in at.error]
    return excs, errors


if __name__ == "__main__":
    out = sys.argv[1]
    problems = {}
    for m in snap["lists"]:
        problems[m] = run_market(m)
    json.dump({"records": REC, "problems": problems}, open(out, "w"), indent=1, sort_keys=True)
    print("recorded keys:", sorted(REC))
    for m, (excs, errs) in problems.items():
        print(f"{m}: exceptions={excs} errors={errs}")
