# Regression check (UI redesign)

Proves that presentation changes to `app.py` never change a number the app produces.
It drives the **real `app.py`** with Streamlit's `AppTest`, replacing the live Yahoo /
CNBC lookups with a frozen snapshot and freezing the clock, then records every result the
calculation functions return (all four portfolios' full weights and figures, the
equal-weight row, theoretical floor/ceiling, exact optimum, frontier curve) for 3 markets ×
2 scenarios (default settings; minimum 5 stocks + 6% risk-free rate).

## Files
| File | Committed? | Purpose |
|---|---|---|
| `make_snapshot.py` | yes | Fetches the three example lists live once and writes `snapshot.pkl`. **Only re-run if you deliberately want a new baseline** (then re-record `baseline.json` from the commit you trust). |
| `harness.py` | yes | `python tests/regression/harness.py <out.json>`: runs the app on the snapshot and records results. |
| `compare.py` | yes | `python tests/regression/compare.py baseline.json <out.json>`: every baseline value must exist and be identical (full precision). |
| `ui_test.py`, `ui_test2.py` | yes | Functional UI checks (examples, matches auto-open, segmented control views, confirmations, market switch, auto-pick warning, data-flag summary). |
| `snapshot.pkl`, `baseline.json`, `pass1.json` | **no** (git-ignored, local only) | Frozen inputs (taken 2026-10-07 22:51 UTC) and the recorded baseline from commit `b74f80f` (before the redesign). |

## Run (from the project root, Windows)
```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/python tests/regression/harness.py tests/regression/run.json
python tests/regression/compare.py tests/regression/baseline.json tests/regression/run.json
```
Expected: `compared 78 recorded results: 0 differences`, no exceptions/errors.

## Notes
- The harness assumes `app.py` keeps: the market `st.radio` (first radio), `session_state["resolutions"]`,
  a button whose label starts with "Build" (or "Fetch"), and number inputs labelled
  "Minimum number of stocks held" and "Risk-free rate…" (sidebar or main). If a UI change
  renames these, update the harness's driving code, not the recorded values.
- AppTest strips a leading emoji from `st.warning`/`st.error` text into the icon; match on words, not emoji.
- If the snapshot files are missing (e.g. a fresh clone), run `make_snapshot.py`, then record a
  new baseline by running `harness.py` on the commit you trust *before* making changes.
