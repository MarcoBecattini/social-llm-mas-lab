"""Live: the same population, graph, trust rules and policies as the replay, but every honest-type execution is a real
OpenAI call graded by the grader service, under a session cap that is never crossed."""
import json
import time

import pandas as pd
import streamlit as st

from socialmas import access as ACC
from socialmas import bcb_data as B
from socialmas import data as D
from socialmas import live as L
from socialmas.experiment import config_hash, validate_config

from .. import auth, results, state, ui
from ..state import policy_label

TITLE = "Live"


def render():
    exp = ui.require_experiment(TITLE, "Real OpenAI calls on the paper's out-of-sample tasks, graded by the grader service, under a spending cap.")
    if exp is None:
        return
    principal = state.principal(); ex = state.experiments(); cfg = exp["config"]
    pr = state.pricing(); pool = D.load_pool("bcb-live-pool.json"); ref = D.load_reference_file("social-live-v1-results.json")
    ui.page_header(TITLE, ["Experiments", exp["name"]],
                   "Same population, graph, trust rules and policies as the replay, but every honest-type execution is a real call to an OpenAI key "
                   "on one of the 121 out-of-sample tasks of the paper's live validation, graded before the trust update. Lazy shirking, impostor "
                   "and refused episodes make no call and cost nothing. Keys stay in the server-side session memory for the run and are never stored or logged.")
    ui.context_strip(exp)
    if state.unsaved(exp):
        st.warning("Configure has unsaved changes: live runs use the **saved** configuration.", icon=":material/edit:")
    health = status_row()
    with st.expander("Reference: the paper's live validation (27 September 2026, 1,029 real calls, 0.29 USD)"):
        pooled_ref = ref.get("pooled", {}); transfer = ref.get("transfer", {})
        rows = [{"policy": policy_label(pol), "episodes": v.get("episodes"), "success_rate": v.get("success_rate"), "calls": v.get("calls")}
                for pol, v in pooled_ref.items() if isinstance(v, dict) and "success_rate" in v]
        if rows:
            ui.table(pd.DataFrame(rows), {"policy": "Policy", "episodes": ("Episodes", "%d"), "success_rate": ("Success rate", "%.3f"), "calls": ("Calls", "%d")})
        if transfer:
            st.caption("Base models on unseen tasks: " + "; ".join(f"{b} live {v['live_rate']:.3f} vs map {v['map_rate']:.3f} ({v['live_calls']} calls)"
                                                                    for b, v in transfer.items() if isinstance(v, dict) and "live_rate" in v))
    new_run_card(ex, principal, exp, cfg, pr, pool, health)
    ui.section("Live runs")
    runs = ex.runs(exp["id"], kind="live")
    if not runs:
        ui.empty_state("No live run yet", "Choose the schedule and the key above, then press **Start live run**.", icon=":material/bolt:"); return
    sel = state.selected_run(exp, "live")
    c1, c2 = st.columns([3, 2], vertical_alignment="center")
    chosen = c1.selectbox("Live run", runs, format_func=state.live_run_label, index=next(i for i, r in enumerate(runs) if r["id"] == sel["id"]), key=f"live_pick_{exp['id']}")
    if chosen["id"] != sel["id"]:
        state.select_run(exp, "live", chosen["id"]); st.rerun()
    with c2:
        if chosen["config_sha256"] and ex.current_run_matches(exp, chosen):
            st.success("This run was made with the current saved configuration.", icon=":material/check:")
        else:
            st.warning("Made with an earlier configuration of this experiment.", icon=":material/history:")
    try:
        res = ex.load_run(chosen["id"])
    except Exception as e:
        st.error(f"Could not load this run: {e}"); return
    results.render_live(res)


def status_row():
    """Grader and dataset status as two cards; returns the grader health."""
    c1, c2 = st.columns(2)
    with c1, st.container(border=True):
        h = state.grader_health(state.grader_url(), state.grader_token())
        if h.get("ok"):
            st.success(f"Grader reachable: {h.get('version')}, {h.get('workers')} workers, {h.get('busy')} busy.", icon=":material/check:")
        else:
            err = str(h.get("error") or ""); err = err[:90] + ("…" if len(err) > 90 else "")
            st.error(f"Grader not reachable at {state.grader_url()} ({err}). Live runs are disabled.", icon=":material/cloud_off:")
    with c2, st.container(border=True):
        if state.dataset_status():
            st.success("Task dataset present (BigCodeBench v0.1.4, hash verified).", icon=":material/check:")
        else:
            st.warning("Task dataset not fetched yet (2.3 MB from Hugging Face, verified against the frozen SHA-256).", icon=":material/download:")
            if st.button("Fetch dataset", icon=":material/download:"):
                try:
                    B.ensure_dataset(auth.access().data_dir); st.rerun()
                except Exception as e:
                    st.error(f"Could not fetch the dataset: {e}")
    return h


def new_run_card(ex, principal, exp, cfg, pr, pool, health):
    acc = auth.access()
    with ui.card("New live run", f"Saved configuration: {len(cfg['agents'])} agents, degree {cfg['graph']['degree']}, radius {cfg['social']['radius']}. "
                 "Only the two measured base models can run live."):
        f1, f2, f3 = st.columns(3)
        episodes = f1.select_slider("Episodes per seed and policy", options=[100, 200, 300], value=100, key="live_episodes")
        seeds = f2.multiselect("Seeds", [0, 1, 2, 3, 4], default=[0], key="live_seeds")
        policies = f3.multiselect("Policies", list(L.LIVE_POLICIES), default=["random", "social"], format_func=policy_label, key="live_policies")
        q = L.quote(pr, episodes, seeds or [0], policies or ["random"])
        st.info(f"Quote from the paper's live run: about {q['expected_calls']} real calls over {q['episodes']} episodes, expected upper cost about "
                f"{q['expected_upper_usd']:.3f} USD. Suggested cap {q['suggested_cap_usd']:.3f} USD. The run stops before any call that could cross the cap.",
                icon=":material/request_quote:")
        shared_ok = bool(acc.shared_key_status()) and not principal.legacy and auth.auth_required()
        remaining = acc.remaining_allowance(principal.id) if shared_ok else 0.0
        sources = ["My own key"] + ([f"Shared laboratory key (remaining allowance {remaining:.2f} USD)"] if shared_ok and remaining > 0 else [])
        if shared_ok and remaining <= 0:
            st.caption("A shared laboratory key exists, but you have no remaining allowance on it: ask an administrator.")
        with st.form("live_run", border=False):
            source = st.radio("Key to use", sources, index=len(sources) - 1, horizontal=True)
            key = st.text_input("Your OpenAI API key (kept in memory for this run only; ignored when the shared key is chosen)", type="password", autocomplete="off")
            cap_max = state.live_max_cap()
            default_cap = float(min(cap_max, max(0.01, q["suggested_cap_usd"])))
            if len(sources) > 1:
                default_cap = float(min(default_cap, remaining))
            cap = st.number_input("Spending cap, USD (upper cost, never crossed)", min_value=0.01, max_value=cap_max, value=max(0.01, default_cap), step=0.01, format="%.2f")
            start = st.form_submit_button("Start live run", type="primary", icon=":material/bolt:", disabled=not health.get("ok"))
    if start:
        start_run(ex, principal, exp, cfg, pr, pool, acc, episodes, seeds, policies, source, key, cap)


def start_run(ex, principal, exp, cfg, pr, pool, acc, episodes, seeds, policies, source, key, cap):
    problems = validate_config(cfg, D.load_competence_map())
    use_shared = source != "My own key"
    if use_shared:
        try:
            key = acc.shared_key_for(principal, f"{cap:.2f}")
        except ACC.AccessError as e:
            st.error(str(e)); return
    if not key.strip():
        st.error("Enter your API key or choose the shared key."); return
    if not seeds or not policies:
        st.error("Choose at least one seed and one policy."); return
    if problems:
        st.error("Saved configuration invalid:\n\n- " + "\n- ".join(problems)); return
    bases = set(cfg["base_models"].values()) - set(pr["models"])
    if bases:
        st.error(f"Live mode supports only the measured base models; unknown: {sorted(bases)}"); return
    try:
        path = B.ensure_dataset(acc.data_dir); tasks = B.load_tasks(path, pool["task_order"])
    except Exception as e:
        st.error(f"Dataset problem: {e}"); return
    ledger = L.SessionLedger(pr, f"{cap:.2f}")
    executor = L.HttpLiveExecutor(key.strip(), pr, ledger, tasks, cfg["base_models"], state.grader_url(), state.grader_token())
    total = episodes * len(seeds) * len(policies)
    bar = st.progress(0.0, text="starting"); t0 = time.perf_counter(); count = {"n": 0}

    def on_episode(record, stats):
        count["n"] += 1; el = time.perf_counter() - t0
        bar.progress(min(1.0, count["n"] / total), text=f"{count['n']}/{total} episodes; {stats['policy']} seed {stats['seed']}; "
                     f"{ledger.summary()['calls']} calls, upper cost {float(ledger.upper):.4f} USD; {el:.0f} s")
    res = L.run_live(cfg, D.load_competence_map(), pool, executor, episodes, seeds, policies, on_episode=on_episode)
    del key
    res["elapsed_seconds"] = round(time.perf_counter() - t0, 1); res["user"] = principal.id
    res["key_source"] = "shared" if use_shared else "own"; res["cap_usd"] = f"{cap:.2f}"
    res["config"] = cfg; res["config_sha256"] = config_hash(cfg); res["experiment"] = exp["id"]
    res["grader"] = state.grader_health(state.grader_url(), state.grader_token())
    if auth.auth_required():
        acc.record_spend(principal, res["key_source"], res["ledger"]["upper_cost_usd"], res["ledger"]["calls"], res["status"], f"{cap:.2f}")
    print(json.dumps({"event": "live_run", "user": principal.id, "experiment": exp["id"], "status": res["status"], "episodes": total,
                      **res["ledger"], "seconds": res["elapsed_seconds"]}), flush=True)
    rid = ex.record_run(principal, exp["id"], "live", res); state.select_run(exp, "live", rid)
    bar.progress(1.0, text=f"{res['status']} in {res['elapsed_seconds']} s"); st.rerun()
