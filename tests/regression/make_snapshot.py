"""Snapshot live inputs once, so baseline and later runs see identical data."""
import os, sys, pickle, pandas as pd
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")))
from data import resolve, listing_currency, fetch_ticker_data
from rates import risk_free_rate
EX = {
 "India (NSE)": ["RELIANCE","TCS","HDFCBANK","INFY","ICICIBANK","ITC","HINDUNILVR","BHARTIARTL","LT","SBIN","ASIANPAINT"],
 "Australia (ASX)": ["BHP","CBA","CSL","NAB","WBC","ANZ","WES","WOW","TLS","RIO","MQG"],
 "USA": ["AAPL","MSFT","JNJ","KO","PG","JPM","XOM","WMT","PEP","MRK","HD"],
}
snap = {"lists": EX, "resolve": {}, "currency": {}, "fetch": {}, "rf": {},
        "now": pd.Timestamp.now(tz="UTC")}
for m, qs in EX.items():
    snap["rf"][m] = risk_free_rate(m)
    for q in qs:
        r = resolve(q, m); snap["resolve"][(q, m)] = r
        for c in r.candidates:
            snap["currency"].setdefault(c.symbol, listing_currency(c.symbol))
        s = r.candidates[0].symbol
        snap["fetch"][(s, m)] = fetch_ticker_data(s, m, q, r.candidates[0].name)
pickle.dump(snap, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "snapshot.pkl"), "wb"))
print("snapshot at", snap["now"], "| stocks", len(snap["fetch"]), "| rates", {m: (round(r.value*100,3), r.is_fallback) for m, r in snap["rf"].items()})
print("failed fetches:", [k for k, v in snap["fetch"].items() if not v.ok])
