"""Pass 1 amendment 2: text-box input and the collapsing "1. Your stocks" section.
Run: PYTHONIOENCODING=utf-8 .venv/Scripts/python tests/regression/ui_test3.py
Prints PASS/FAIL per check and a final count (frozen snapshot data, via harness)."""
import sys, os, copy
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # applies the frozen-data patches
from harness import snap, REPO
from streamlit.testing.v1 import AppTest
from data import Candidate, MULTIPLE

results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))


def new():
    at = AppTest.from_file(os.path.join(REPO, "app.py"), default_timeout=900)
    at.run()
    return at


def btn(at, start):
    return next(b for b in at.button if b.label.startswith(start))


def exc(at):
    return [str(e.value)[:160] for e in at.exception]


def s1(at):
    """The section-1 expander (label starts with '**1. Your stocks**'), or None."""
    return next((e for e in at.expander if e.label.startswith("**1. Your stocks**")), None)


def s1_open(at):
    return bool(at.session_state["section1_open"]) if "section1_open" in at.session_state else None


def has_results(at):
    return any(h.value == "2. Your portfolios" for h in at.header)


# 1. Parsing (the app's own function, imported without running the page)
import ast
src = open(os.path.join(REPO, "app.py"), encoding="utf-8").read()
fn = next(n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == "parse_stocks")
ns = {"re": __import__("re")}
exec(compile(ast.Module([fn], []), "app.py", "exec"), ns)
parse = ns["parse_stocks"]
got = parse("BHP, CBA;CSL\tNAB\n\nWBC ,  ;\r\nCommonwealth Bank,,\n  Woolworths Group  \n")
check("mixed separators parse in order, blanks dropped",
      got == ["BHP", "CBA", "CSL", "NAB", "WBC", "Commonwealth Bank", "Woolworths Group"], got)
check("company name with spaces stays one entry", "Commonwealth Bank" in got)
check("empty / blank-only input parses to nothing", parse("") == [] and parse(" ,\n;\t ") == [] and parse(None) == [])

# 2. Before results: section 1 is a plain section (header), no collapsible expander
at = new()
check("first screen: header '1. Your stocks', no section expander",
      any(h.value == "1. Your stocks" for h in at.header) and s1(at) is None)

# 3. Each example reaches results in one click with section 1 collapsed
for m in ("India (NSE)", "Australia (ASX)", "USA"):
    at = new()
    next(b for b in at.button if b.label == m).click().run()
    e = s1(at)
    check(f"{m} example: results in one click, section 1 collapsed and names the market",
          has_results(at) and e is not None and s1_open(at) is False and m in e.label
          and "11 stocks" in e.label and not exc(at), e.label if e else None)
    check(f"{m} example: text box pre-filled as a comma-separated list",
          parse(at.text_area[0].value) == harness_list if (harness_list := snap["lists"][m]) else False,
          at.text_area[0].value[:60])

# 4. Typing into the text box (AppTest can, unlike the data editor) + Find stocks
at = new()
at.radio[0].set_value("USA").run()
at.text_area[0].input("AAPL, MSFT\nJNJ;KO\tPG\n\n JPM ,XOM\nWMT;PEP\nMRK,HD")  # form: submitted with the click
btn(at, "Find stocks").click().run()
rs = at.session_state["resolutions"]
check("typed mixed-separator list resolves to 11 inputs in order",
      [r.query for r in rs] == snap["lists"]["USA"], [r.query for r in rs])
check("after Find stocks (not built yet): section open, no results", s1(at) is None and not has_results(at))
btn(at, "Build").click().run()
check("Build: results shown, section 1 collapsed", has_results(at) and s1_open(at) is False, s1(at).label if s1(at) else None)

# 5. Picks and Include choices survive collapsing and reopening section 1
at = new()
at.radio[0].set_value("USA").run()
base = [copy.deepcopy(snap["resolve"][(q, "USA")]) for q in snap["lists"]["USA"]]
amb = base[1]; amb.query = "Microsoft?"; amb.status = MULTIPLE
amb.candidates = amb.candidates + [Candidate("MSFO", "Some Other Microsoft", "NASDAQ", "NMS")]
at.session_state["resolutions"] = base; at.run()
# the alternative candidate needs frozen data too: a copy of MSFT's under the symbol MSFO
alt = copy.deepcopy(snap["fetch"][("MSFT", "USA")]); alt.yahoo_symbol = "MSFO"; alt.company_name = "Some Other Microsoft"
snap["fetch"][("MSFO", "USA")] = alt; snap["currency"]["MSFO"] = "USD"
hd_box = next(c for c in at.checkbox if c.key.startswith("inc_10_"))
hd_box.uncheck().run()
btn(at, "Build").click().run()
check("built with HD unticked (10 stocks)", has_results(at) and "10 stocks" in (s1(at).label if s1(at) else ""),
      s1(at).label if s1(at) else None)
check("auto-picked row opens section 1 once after build (match needs attention)", s1_open(at) is True)
at.session_state["section1_open"] = False; at.run()
check("user can then collapse it; it stays collapsed while the auto-pick is unchanged",
      s1_open(at) is False and has_results(at))
at.session_state["section1_open"] = True; at.run()
# Now resolve the auto-pick by choosing the other candidate, then back: user's choice = 'Picked by you'
sel = next(s for s in at.selectbox if s.key.startswith("pick_1_"))
sel.set_value(1).run()
check("picking another candidate makes the build stale -> section stays open, rebuild prompt",
      s1_open(at) is True and any("selections changed" in i.value for i in at.info))
btn(at, "Build").click().run()
check("rebuild with no attention left: section 1 collapses", has_results(at) and s1_open(at) is False,
      s1(at).label if s1(at) else None)
# reopen, then collapse again: choices must survive
at.session_state["section1_open"] = True; at.run()
check("reopened: label has no 'click to edit'", s1_open(at) is True and "click to edit" not in s1(at).label)
at.session_state["section1_open"] = False; at.run()
at.session_state["section1_open"] = True; at.run()
sel = next(s for s in at.selectbox if s.key.startswith("pick_1_"))
hd_box = next(c for c in at.checkbox if c.key.startswith("inc_10_"))
check("after collapse + reopen: pick and Include choices kept, results unchanged",
      sel.value == 1 and hd_box.value is False and has_results(at)
      and not any("selections changed" in i.value for i in at.info), (sel.value, hd_box.value))
check("market radio kept", at.radio[0].value == "USA")

# 6. Section 1 opens automatically when a match needs attention (no-match + duplicate)
at = new()
at.radio[0].set_value("USA").run()
at.session_state["resolutions"] = [copy.deepcopy(snap["resolve"][(q, "USA")]) for q in snap["lists"]["USA"]]
at.run(); btn(at, "Build").click().run()
check("clean build collapses", s1_open(at) is False)
at.session_state["section1_open"] = True; at.run()  # user opens it to edit
at.text_area[0].input(", ".join(snap["lists"]["USA"]) + ", xyzqwerty")
from data import Resolution
extra = Resolution(query="xyzqwerty", exchange="USA")
at.session_state["resolutions"] = at.session_state["resolutions"] + [extra]
at.session_state["section1_open"] = False  # try to keep it collapsed
at.run()
check("unmatched row forces section 1 open", s1_open(at) is True and not exc(at))

# 7. Confirmations with progress; Cancel keeps everything
at = new()
next(b for b in at.button if b.label == "USA").click().run()
at.session_state["section1_open"] = True; at.run()
next(b for b in at.button if b.label == "India (NSE)").click().run()
check("load-example confirmation appears (section open)",
      any("Load the **India (NSE)** example" in w.value for w in at.warning) and s1_open(at) is True)
btn(at, "Cancel").click().run()
check("Cancel keeps market and results", at.session_state["market"] == "USA" and has_results(at))
at.radio[0].set_value("Australia (ASX)").run()
check("market-switch confirmation appears", any("Switch the market" in w.value for w in at.warning))
btn(at, "Cancel, stay").click().run()
check("Cancel keeps market, radio and results",
      at.session_state["market"] == "USA" and at.radio[0].value == "USA" and has_results(at))

at = new()
at.radio[0].set_value("USA").run()
at.text_area[0].input("AAPL, MSFT")
btn(at, "Find stocks").click().run()
at.radio[0].set_value("India (NSE)").run()
check("submitted text: market switch asks for confirmation", any("Switch the market" in w.value for w in at.warning))
btn(at, "Switch to India").click().run()
check("confirm clears: market India, empty text box, no lookups",
      at.session_state["market"] == "India (NSE)" and at.text_area[0].value == ""
      and "resolutions" not in at.session_state and not exc(at))

print(f"\n{sum(results)}/{len(results)} checks passed")
