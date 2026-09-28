"""Replay: run the saved configuration over the measured outcomes and browse the experiment's replay runs."""
import time

import streamlit as st

from socialmas import data as D
from socialmas.experiment import config_hash, estimate_seconds, run_experiment, validate_config

from .. import results, state, ui
from ..state import policy_label

TITLE = "Replay"


def render():
    exp = ui.require_experiment(TITLE, "Deterministic simulation of the saved configuration over the measured outcomes.")
    if exp is None:
        return
    ex = state.experiments(); principal = state.principal(); cfg = exp["config"]

    def action():
        if principal.can("replay.run"):
            return st.button("Run replay", type="primary", icon=":material/play_arrow:", width="stretch", key="run_replay")

    clicked = ui.page_header(TITLE, ["Experiments", exp["name"]],
                             "Every worker is backed by the outcome table measured once with real models; policies only see declarations, "
                             "their own trust records, referral opinions and episode outcomes.", action=action)
    ui.context_strip(exp)
    est = estimate_seconds(cfg) * state.server_speed_factor()
    with ui.card("Saved configuration"):
        st.markdown(f"{len(cfg['agents'])} agents · {state.schedule(cfg)} · about **{est:.0f} s** on this server")
        if state.unsaved(exp):
            st.warning("Configure has unsaved changes: runs use the **saved** configuration.", icon=":material/edit:")
    if clicked:
        run(ex, principal, exp, cfg)
    ui.section("Results")
    runs = ex.runs(exp["id"], kind="replay")
    if not runs:
        ui.empty_state("No replay run yet", "Press **Run replay** to simulate the saved configuration. The paper's own numbers are on the Paper comparison page.",
                       icon=":material/play_circle:")
        return
    sel = state.selected_run(exp, "replay")
    c1, c2 = st.columns([3, 2], vertical_alignment="center")
    chosen = c1.selectbox("Replay run", runs, format_func=state.replay_run_label, index=next(i for i, r in enumerate(runs) if r["id"] == sel["id"]),
                          key=f"replay_pick_{exp['id']}")
    if chosen["id"] != sel["id"]:
        state.select_run(exp, "replay", chosen["id"]); st.rerun()
    with c2:
        if ex.current_run_matches(exp, chosen):
            st.success("This run was made with the current saved configuration.", icon=":material/check:")
        else:
            st.warning(f"The saved configuration has changed since this run (version {chosen['config_version']} then, {exp['config_version']} now).", icon=":material/history:")
    try:
        results.render_replay(ex.load_run(chosen["id"]))
    except Exception as e:
        st.error(f"Could not load this run: {e}")


def run(ex, principal, exp, cfg):
    problems = validate_config(cfg, D.load_competence_map())
    if problems:
        st.error("Saved configuration invalid:\n\n- " + "\n- ".join(problems)); return
    key_ = config_hash(cfg); store = state.results_store()
    if key_ in store:
        res = store[key_]; st.caption("Identical configuration already computed on this server: results served from memory.")
    else:
        bar = st.progress(0.0, text="starting"); t0 = time.perf_counter()

        def progress(done, total, policy, seed):
            el = time.perf_counter() - t0; eta = el / done * (total - done)
            bar.progress(done / total, text=f"{done}/{total}: {policy_label(policy)}, seed {seed}; {el:.0f} s elapsed, about {eta:.0f} s left")
        res = run_experiment(cfg, D.load_competence_map(), progress=progress)
        res["elapsed_seconds"] = round(time.perf_counter() - t0, 2)
        if len(store) >= 64:
            store.pop(next(iter(store)))
        store[key_] = res
        bar.progress(1.0, text=f"done in {res['elapsed_seconds']:.1f} s")
    rid = ex.record_run(principal, exp["id"], "replay", res); state.select_run(exp, "replay", rid); st.rerun()
