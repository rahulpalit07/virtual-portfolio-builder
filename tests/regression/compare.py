"""Compare a run against the baseline: every baseline value must exist and be identical."""
import json, sys
base = json.load(open(sys.argv[1]))["records"]; new = json.load(open(sys.argv[2]))
problems, newrec = new["problems"], new["records"]
diffs, compared, extra = [], 0, []
for key, fns in base.items():
    for fn, entries in fns.items():
        for sub, val in entries.items():
            got = newrec.get(key, {}).get(fn, {}).get(sub, "<missing>")
            compared += 1
            if got != val:
                diffs.append((key, fn, sub[:60], "missing" if got == "<missing>" else "DIFFERENT"))
for key, fns in newrec.items():
    for fn, entries in fns.items():
        for sub in entries:
            if sub not in base.get(key, {}).get(fn, {}):
                extra.append((key, fn, sub[:60]))
print(f"compared {compared} recorded results: {len(diffs)} differences")
for d in diffs[:20]: print("  DIFF", d)
print(f"extra results in new run (not in baseline): {len(extra)}")
for e in extra[:10]: print("  extra", e)
print("app exceptions/errors:", problems)
