import sys, os, copy
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # applies the frozen-data patches
from harness import snap, REPO, data
from streamlit.testing.v1 import AppTest
from data import Resolution, Candidate, MULTIPLE

def new():
    at = AppTest.from_file(os.path.join(REPO, "app.py"), default_timeout=900); at.run(); return at
def btn(at, start): return next(b for b in at.button if b.label.startswith(start))
def texts(at):
    return [e.value for k in ("markdown","caption","info","warning","error","success") for e in getattr(at, k)]
def exc(at): return [str(e.value)[:160] for e in at.exception]

# 1. first screen
at = new()
print("1) radio:", at.radio[0].value, "| headers:", [h.value for h in at.header], "| example buttons:", [b.label for b in at.button])
print("   sidebar elements before market:", len(at.sidebar.children) if hasattr(at.sidebar,'children') else "?", "| methodology/footer present:", any("Educational tool" in t for t in texts(at)))

# 2. one-click USA example
btn(at, "USA").click().run()
print("2) after USA example: market =", at.session_state["market"], "| radio =", at.radio[0].value,
      "| fetched:", "fetched" in at.session_state, "| headers:", [h.value for h in at.header])
print("   section 1 (collapsed after results):", [(e.label, e.proto.expanded) for e in at.expander if e.label.startswith("**1. Your stocks**")])
print("   matches expander:", [(e.label, e.proto.expanded) for e in at.expander if "matched" in e.label or "found" in e.label])
print("   summary:", [t for t in texts(at) if t.startswith("**11 stocks")])
print("   sidebar number inputs:", [n.label for n in at.sidebar.number_input])
print("   comparison columns:", list(at.dataframe[0].value.columns))
print("   exceptions:", exc(at))

# 3. segmented control: visit every portfolio view
seg = [w for w in at.get("button_group")] if hasattr(at, "get") else []
print("3) button_group widgets:", len(seg))
for view in ("Max Return", "Max Dividend", "Max Sharpe", "Min Risk"):
    g = at.get("button_group")[0]
    g.set_value([view] if isinstance(g.value, list) else view).run()
    checks = [e.label for e in at.expander if "checks" in e.label]
    held = [t for t in texts(at) if " portfolio (" in t]
    print(f"   {view:13} -> {held[0] if held else '?'} | {checks} | exceptions {exc(at)}")

# 4. loading an example over existing work asks first
btn(at, "India").click().run()
print("4) pending:", at.session_state["pending_example"] if "pending_example" in at.session_state else None,
      "| warning:", [w.value[:70] for w in at.warning][:1])
btn(at, "Cancel").click().run()
print("   after Cancel: market =", at.session_state["market"], "| results kept:", "fetched" in at.session_state)
btn(at, "India").click().run(); btn(at, "Load India").click().run()
print("   after Load: market =", at.session_state["market"], "| fetched:", "fetched" in at.session_state,
      "| first holding view:", [t for t in texts(at) if " portfolio (" in t][:1], "| exceptions", exc(at))

# 5. attention auto-expands the matches (ambiguous + flagged + no-match rows)
at = new(); at.radio[0].set_value("USA").run()
rs = [copy.deepcopy(snap["resolve"][(q, "USA")]) for q in snap["lists"]["USA"]]
amb = copy.deepcopy(rs[0]); amb.query = "Apple?"; amb.status = MULTIPLE
amb.candidates = amb.candidates + [Candidate("APLE", "Apple Hospitality REIT", "NYSE", "NYQ")]
nom = Resolution(query="xyzqwerty", exchange="USA")
at.session_state["resolutions"] = rs + [amb, nom]; at.run()
print("5) matches expander:", [(e.label, e.proto.expanded) for e in at.expander if "matched" in e.label or "found" in e.label])
print("   auto-pick warning:", [w.value[:90] for w in at.warning if "auto-picked" in w.value])
print("   build button:", [b.label for b in at.button if b.label.startswith("Build")], "| exceptions", exc(at))

# 6. market switch still confirms and clears
at.radio[0].set_value("India (NSE)").run()
print("6) switch warning:", [w.value[:60] for w in at.warning if "Switch the market" in w.value])
btn(at, "Switch to India").click().run()
print("   after confirm: market =", at.session_state["market"], "| resolutions kept:", "resolutions" in at.session_state, "| exceptions", exc(at))
