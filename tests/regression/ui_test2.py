import sys, os, copy
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness
from harness import snap, REPO
from streamlit.testing.v1 import AppTest
from data import Candidate, MULTIPLE
import stats
# flag labels, using real stats flag texts
from stats import StockStats
at = AppTest.from_file(os.path.join(REPO, "app.py"), default_timeout=900); at.run()
at.radio[0].set_value("USA").run()
rs = [copy.deepcopy(snap["resolve"][(q, "USA")]) for q in snap["lists"]["USA"]]
amb = rs[1]; amb.query = "Microsoft?"; amb.status = MULTIPLE   # MSFT, ambiguous, not a duplicate
amb.candidates = amb.candidates + [Candidate("MSFO", "Some Other Microsoft", "NASDAQ", "NMS")]
at.session_state["resolutions"] = rs; at.run()
print("expander:", [(e.label, e.proto.expanded) for e in at.expander][:1])
print("auto-pick warning:", [w.value for w in at.warning if "auto-picked" in w.value])
# data-flag summary line: inject flags into compute_stats output
orig = stats.compute_stats
def flagged_stats(stocks, now=None):
    r = harness._compute(stocks, now=snap["now"])
    r.stocks["AAPL"].flags = ["Only 2.5 years of history (spec asks for 3–5). Its statistics…", "Very high annualized risk (81%)."]
    r.stocks["KO"].flags = ["25% of trading days had exactly 0% return: possibly thinly traded or stale prices."]
    return r
harness.stats.compute_stats = flagged_stats
at2 = AppTest.from_file(os.path.join(REPO, "app.py"), default_timeout=900); at2.run()
next(b for b in at2.button if b.label == "USA").click().run()
print("flag summary:", [w.value for w in at2.warning if "Data worth" in w.value])
print("exceptions:", [str(e.value)[:150] for e in list(at.exception) + list(at2.exception)])
