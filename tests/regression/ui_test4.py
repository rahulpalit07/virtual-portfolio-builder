"""Pass 2: metric-card deltas vs equal weight, comparison-table highlighting, donut charts,
"why this portfolio" lines and "Start a new analysis".
Run: PYTHONIOENCODING=utf-8 .venv/Scripts/python tests/regression/ui_test4.py
Prints PASS/FAIL per check and a final count (frozen snapshot data, via harness)."""
import sys, os, re, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # applies the frozen-data patches
from harness import REPO
from streamlit.testing.v1 import AppTest

results = []
GREEN, RED, GRAY = 1, 0, 2          # MetricProto.MetricColor
VIEWS = ("Min Risk", "Max Return", "Max Dividend", "Max Sharpe")
EW = "Equal weight (reference)"
# card label -> (comparison column, kind, lower is better)
CARDS = {
    "Expected return": ("Expected return", "pct", False),
    "Risk": ("Risk", "pct", True),
    "Dividend yield": ("Dividend yield", "pct", False),
    "Sharpe ratio": ("Sharpe ratio", "num", False),
}
COMPARED = {"Expected return": max, "Risk": min, "Dividend yield": max, "Sharpe ratio": max}


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""))


def new():
    at = AppTest.from_file(os.path.join(REPO, "app.py"), default_timeout=900)
    at.run()
    return at


def exc(at):
    return [str(e.value)[:160] for e in at.exception]


def comparison(at):
    return next(d for d in at.dataframe if "Portfolio" in d.value.columns)


def expected_delta(diff, kind):
    number = f"{diff:+.2f}" if kind == "pct" else f"{diff:+.3f}"   # table values are already in %
    zero = float(number) == 0
    return (number.lstrip("+-") if zero else number) + (" pts" if kind == "pct" else "") + " vs equal weight", zero


def plotly_array(v):
    """Plotly serializes numpy arrays as {"dtype", "bdata"} (base64); plain lists stay lists."""
    if isinstance(v, dict) and "bdata" in v:
        import base64, numpy as np
        return list(np.frombuffer(base64.b64decode(v["bdata"]), dtype=np.dtype(v["dtype"])))
    return list(v)


def highlighted(df_el):
    """{column name: set of row positions} filled by the Styler."""
    css = df_el.proto.arrow_data.styler.styles
    cols = list(df_el.value.columns)
    out = {}
    for rule in re.findall(r"([^{}]+)\{([^}]*)\}", css):
        if "background-color" not in rule[1]:
            continue
        for sel in rule[0].split(","):
            m = re.search(r"row(\d+)_col(\d+)", sel)
            if m:
                out.setdefault(cols[int(m.group(2))], set()).add(int(m.group(1)))
    return out


for market in ("India (NSE)", "Australia (ASX)", "USA"):
    at = new()
    next(b for b in at.button if b.label == market).click().run()
    check(f"{market}: example builds with no exceptions", not exc(at), exc(at))
    comp_el = comparison(at)
    comp = comp_el.value.set_index("Portfolio")
    ew = comp.loc[EW]

    # 1. Highlighting: the true best per column among the four portfolios; never equal weight
    marks = highlighted(comp_el)
    ew_pos = list(comp_el.value["Portfolio"]).index(EW)
    check(f"{market}: equal-weight row never highlighted", all(ew_pos not in rows for rows in marks.values()))
    check(f"{market}: 'Stocks held' not highlighted", "Stocks held" not in marks)
    for col, pick in COMPARED.items():
        vals = comp_el.value[comp_el.value["Portfolio"] != EW][col].astype(float)
        best_val = pick(vals.round(3 if col == "Sharpe ratio" else 2))
        expect = {i for i, v in vals.round(3 if col == "Sharpe ratio" else 2).items() if v == best_val}
        check(f"{market}: highlighted {col} = true best", marks.get(col) == expect, (marks.get(col), expect))

    for view in VIEWS:
        g = at.get("button_group")[0]
        g.set_value([view] if isinstance(g.value, list) else view).run()
        check(f"{market} / {view}: no exceptions", not exc(at), exc(at))
        # 2. Cards: delta = portfolio value − equal-weight value from the comparison table
        metrics = {m.label: m for m in at.metric if m.label in CARDS}
        check(f"{market} / {view}: four cards", len(metrics) == 4, list(metrics))
        for label, (col, kind, lower_better) in CARDS.items():
            m = metrics[label]
            diff = comp.loc[view, col] - ew[col]
            text, zero = expected_delta(diff, kind)
            check(f"{market} / {view} / {label}: delta {m.delta}", m.delta == text, (m.delta, text))
            better = (diff < 0) if lower_better else (diff > 0)
            want = GRAY if zero else (GREEN if better else RED)
            check(f"{market} / {view} / {label}: colour", m.proto.color == want, (m.proto.color, want))
        # removed separate equal-weight metrics
        stale = [m.label for m in at.metric if "Equal-weight" in m.label or m.label == "Risk reduction"]
        check(f"{market} / {view}: no separate equal-weight metrics", not stale, stale)
        # 3. Donut: slices = held weights from the holdings table, summing to 100%
        hold = next(d for d in at.dataframe if list(d.value.columns) == ["Ticker", "Company", "Weight", "Match"]).value
        pies = [json.loads(c.proto.spec) for c in at.get("plotly_chart")]
        pie = next(t for f in pies for t in f["data"] if t.get("type") == "pie")
        pie["values"] = plotly_array(pie["values"])
        check(f"{market} / {view}: donut slices = held stocks, by weight",
              pie["labels"] == list(hold["Ticker"]) and all(abs(a - b) < 1e-9 for a, b in zip(pie["values"], hold["Weight"])))
        check(f"{market} / {view}: donut sums to 100%", abs(sum(pie["values"]) - 100) < 1e-6, sum(pie["values"]))
        colors = pie["marker"]["colors"]
        check(f"{market} / {view}: no red in donut, neighbours differ",
              all(c.upper() not in ("#FF0000", "#FF2B2B", "#D32F2F", "#E53935", "#F44336") for c in colors)
              and all(colors[i] != colors[i + 1] for i in range(len(colors) - 1)))
        check(f"{market} / {view}: Match column is icons only", set(hold["Match"]) <= {"✅", "⚠️", "🔁", "🌐"}, set(hold["Match"]))
        # 4. "Why this portfolio" line
        why = [e.value for e in at.markdown if "For a" in e.value or "For an" in e.value]
        check(f"{market} / {view}: one 'why this portfolio' line", len(why) == 1, why)

# 5. Start a new analysis: back to the start, no leftover state; then a full run on another market
at = new()
next(b for b in at.button if b.label == "USA").click().run()
next(n for n in at.sidebar.number_input if n.label.startswith("Minimum")).set_value(5).run()
next(n for n in at.sidebar.number_input if n.label.startswith("Risk-free")).set_value(6.0).run()
at.get("button_group")[0].set_value("Max Sharpe").run()
next(b for b in at.button if b.label == "Start a new analysis").click().run()
keys = list(at.session_state._state.filtered_state)  # user-visible session-state keys
leftover = [k for k in keys if k.startswith(("inc_", "pick_", "rf_", "s1_")) or k in (
    "resolutions", "fetched", "listing_currencies", "min_stocks", "portfolio_view", "pending_example",
    "input_seed", "section1_open") or (k.startswith("input_") and k != "input_version")]
check("reset: no market selected (radio empty, session market None)",
      at.radio[0].value is None and at.session_state["market"] is None)
check("reset: no leftover stock, match, result or settings state", not leftover, leftover)
check("reset: first screen (header '1. Your stocks', no results, no sidebar settings)",
      [h.value for h in at.header] == ["1. Your stocks"] and not at.sidebar.number_input and not at.text_area)
check("reset: no exceptions", not exc(at), exc(at))
next(b for b in at.button if b.label == "Australia (ASX)").click().run()
check("after reset: Australia example runs in one click (no confirmation needed)",
      any(h.value == "2. Your portfolios" for h in at.header) and at.session_state["market"] == "Australia (ASX)")
mins = next(n for n in at.sidebar.number_input if n.label.startswith("Minimum"))
check("after reset: settings back to defaults (minimum 4, live rate)", mins.value == 4
      and not any("Overridden by you" in i.value for i in at.sidebar.info), mins.value)
check("after reset: portfolio view back to Min Risk",
      any("Min Risk portfolio (" in m.value for m in at.markdown))
at.radio[0].set_value("Australia (ASX)").run()
at.text_area[0].input("BHP, CBA, CSL, NAB, WBC, ANZ, WES, WOW, TLS, RIO, MQG")
next(b for b in at.button if b.label.startswith("Find stocks")).click().run()
next(b for b in at.button if b.label.startswith("Build")).click().run()
check("after reset: a typed full run works with no exceptions",
      any(h.value == "2. Your portfolios" for h in at.header) and not exc(at), exc(at))

print(f"\n{sum(results)}/{len(results)} checks passed")
