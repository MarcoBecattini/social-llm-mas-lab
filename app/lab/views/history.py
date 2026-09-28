"""History: every run of the open experiment, replay and live, with the configuration version it was made with."""
import pandas as pd
import streamlit as st

from .. import state, ui
from ..state import policy_label

TITLE = "History"
COLUMNS = {"when": "When (UTC)", "kind": "Kind", "user": "By", "status": "Status", "version": ("Configuration version", "%d"),
           "current": ("Matches current", "bool"), "policies": "Success by policy", "seeds": ("Seeds", "%d"), "episodes": ("Episodes", "%d"),
           "calls": ("Calls", "%d"), "cost": ("Upper cost USD", "%.4f"), "key": "Key"}


def render():
    exp = ui.require_experiment(TITLE, "Every replay and live run of the open experiment.")
    if exp is None:
        return
    ex = state.experiments()
    ui.page_header(TITLE, ["Experiments", exp["name"]], "Every run recorded on this experiment, newest first, with the configuration version it used.")
    ui.context_strip(exp)
    runs = ex.runs(exp["id"])
    if not runs:
        ui.empty_state("No runs yet", "Replay and live runs of this experiment will be listed here.", icon=":material/history:"); return
    live = [r for r in runs if r["kind"] == "live"]
    spent = sum(float(r["summary"].get("upper_cost_usd") or 0) for r in live)
    ui.tiles([{"label": "Runs", "value": str(len(runs)), "note": f"since {state.when(runs[-1]['ts'])} UTC"},
              {"label": "Replay runs", "value": str(len(runs) - len(live)), "note": "deterministic, over measured outcomes"},
              {"label": "Live runs", "value": str(len(live)), "note": f"{sum(int(r['summary'].get('calls') or 0) for r in live)} real calls"},
              {"label": "Live spending", "value": f"{spent:.4f} USD", "note": "upper cost, all live runs"}])
    rows = []
    for r in runs:
        sm = r["summary"]
        rows.append({"when": state.when(r["ts"]), "kind": r["kind"], "user": r["user"], "status": r["status"], "version": r["config_version"],
                     "current": ex.current_run_matches(exp, r),
                     "policies": ", ".join(f"{policy_label(p)} {v:.3f}" for p, v in sm.get("policies", {}).items() if v is not None),
                     "seeds": sm.get("seeds") if isinstance(sm.get("seeds"), int) else len(sm.get("seeds") or []), "episodes": sm.get("episodes"),
                     "calls": sm.get("calls"), "cost": float(sm["upper_cost_usd"]) if sm.get("upper_cost_usd") is not None else None, "key": sm.get("key_source")})
    ui.table(pd.DataFrame(rows), COLUMNS)
    c1, c2 = st.columns([3, 1.2], vertical_alignment="bottom")
    pick = c1.selectbox("Run", runs, format_func=lambda r: f"{state.when(r['ts'])} · {r['kind']} · {r['user']} · {r['status']}", key=f"hist_{exp['id']}")
    target = pick["kind"] if state.has_page(pick["kind"]) else None
    if c2.button("Open this run", icon=":material/open_in_new:", width="stretch", disabled=target is None, key="open_run"):
        state.select_run(exp, pick["kind"], pick["id"]); ui.go(target)
