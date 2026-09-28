"""Shared state of the interface: human labels, process-wide cached resources, and the session's open experiment, its
unsaved draft and the selected runs.

Nothing per session lives in module globals: the principal of the run and the page objects sit in `st.session_state`,
the stores in `st.cache_resource`, so concurrent sessions never see each other's data."""
import copy
import json
import os
import time

import pandas as pd
import streamlit as st

from socialmas import bcb_data as B
from socialmas import data as D
from socialmas import experiments as X
from socialmas import sim as S
from socialmas import templates as T

from .auth import access

# ---- labels and help texts ----
POLICY_LABEL = {"random": "random", "declared": "declared", "best_fixed": "best fixed contact (ref.)", "oracle": "oracle (ref.)",
                "social_noref": "social, no referrals", "social_nobefriend": "social, no new relationships",
                "social": "social (full)", "social_refcheck": "social + referral check"}
PROFILE_ORDER = ["honest", "boaster", "impostor", "lazy", "specialist", "unstable", "liar"]
PROFILE_HELP = {
    "honest": "declares the domains where its base model passes at least the declaration threshold; outcome = measured map",
    "boaster": "declares all seven domains; works like honest (a mild false claim)",
    "impostor": "declares all seven domains, always fails, still bills the call",
    "lazy": "declares like honest; with probability lazy_p returns an empty answer and still bills",
    "specialist": "declares only its listed domains and refuses tasks outside them (no cost, one extra message)",
    "unstable": "declares like honest; alternates phases of phase_length episodes: honest, lazy with lazy_p, honest, ...",
    "liar": "honest worker; when asked for opinions it reports the opposite verdict, amplified (malicious recommender)"}
POLICY_HELP = {
    "random": "uniform choice among reachable agents",
    "declared": "uniform choice among reachable agents that declare the task's domain",
    "best_fixed": "reference line: always the same best honest agent (assumes knowing who is best)",
    "oracle": "reference line: verified per-domain competence from a central registry",
    "social_noref": "own outcome-based trust, new relationships after success, no referral opinions",
    "social_nobefriend": "own trust plus referral opinions, but the graph never changes",
    "social": "own trust, referral opinions weighted by trust in the referrer as a worker, new relationships after success",
    "social_refcheck": "as social, but referrals are weighted by the referrer's past referral accuracy (defence against liars)"}


def policy_label(p):
    return POLICY_LABEL.get(p, p)


def preset_label(name):
    return D.PRESETS[name]["label"] if name in D.PRESETS else (name or "")


# ---- live mode settings (read at call time so tests and deployments can change the environment) ----
def grader_url():
    return os.environ.get("GRADER_URL", "http://social-llm-mas-grader:10000")


def grader_token():
    return os.environ.get("GRADER_TOKEN", "")


def live_max_cap():
    return float(os.environ.get("SOCIALMAS_LIVE_MAX_CAP", "5"))


# ---- process-wide resources ----
@st.cache_resource(show_spinner=False)
def experiments():
    ex = X.Experiments(access())
    try:
        ex.import_legacy_live_runs()
    except Exception:
        pass
    return ex


@st.cache_resource(show_spinner=False)
def templates():
    return T.Templates(experiments())


@st.cache_resource(show_spinner=False)
def server_speed_factor():
    """How much slower this server is than the reference machine on which the estimates were calibrated."""
    c = D.load_preset("paper-v2"); c["episodes"] = 1000
    t0 = time.perf_counter(); S.run_policy("social", c, D.load_competence_map(), 0); dt = time.perf_counter() - t0
    return max(1.0, dt / 0.095)


@st.cache_resource(show_spinner=False)
def results_store():
    """Replay results by configuration hash, shared by all sessions of this server."""
    return {}


@st.cache_resource(show_spinner=False)
def pricing():
    return json.loads((D.DATA_DIR / "pricing.json").read_text())


@st.cache_data(ttl=30, show_spinner=False)
def grader_health(url, token=""):
    import requests
    try:
        r = requests.get(url.rstrip("/") + "/healthz", timeout=5, headers={"X-Grader-Token": token} if token else {})
        return r.json() if r.status_code == 200 else {"ok": False, "error": f"http {r.status_code}"}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"[:200]}


def dataset_status():
    path = B.dataset_path(access().data_dir)
    return path if path.exists() else None


# ---- the run: principal and pages, kept in session state ----
def begin_run(principal, pages):
    ss = st.session_state
    ss["_principal"] = principal; ss["_pages"] = pages
    ss.setdefault("exp_id", None); ss.setdefault("tpl_id", None); ss.setdefault("drafts", {}); ss.setdefault("draft_version", {}); ss.setdefault("selected_run", {})


def principal():
    return st.session_state["_principal"]


def page(name):
    """The st.Page registered under `name` in this run (for st.switch_page and st.page_link)."""
    return st.session_state["_pages"][name]


def has_page(name):
    return name in st.session_state.get("_pages", {})


# ---- the open experiment, its draft and the selected runs ----
def open_experiment(exp_id):
    ss = st.session_state
    exp = experiments().get(exp_id)
    if exp is None:
        st.error("Experiment not found."); return
    ss.exp_id = exp_id; ss.drafts[exp_id] = copy.deepcopy(exp["config"])
    ss.draft_version[exp_id] = ss.draft_version.get(exp_id, 0) + 1
    ss.selected_run.pop(exp_id, None)


def close_experiment():
    st.session_state.exp_id = None


def current_experiment():
    ss = st.session_state
    if ss.exp_id:
        exp = experiments().get(ss.exp_id)
        if exp is not None:
            return exp
        ss.exp_id = None
    return None


def open_template(tpl_id):
    """Make `tpl_id` the template of the editor page, with a fresh draft (drafts are keyed by id, like experiments')."""
    ss = st.session_state
    tpl = templates().get(principal(), tpl_id)
    if tpl is None:
        st.error("Template not found."); return
    ss.tpl_id = tpl_id; ss.drafts[tpl_id] = copy.deepcopy(tpl["config"])
    ss.draft_version[tpl_id] = ss.draft_version.get(tpl_id, 0) + 1


def current_template():
    ss = st.session_state
    if ss.get("tpl_id"):
        tpl = templates().get(principal(), ss.tpl_id)
        if tpl is not None:
            return tpl
        ss.tpl_id = None
    return None


def origin_label(exp):
    """'paper-v2' or 'template «name» v3' for an experiment's origin, '' when it has none."""
    if exp.get("origin_template"):
        t = templates().get_any(exp["origin_template"])
        return f"template «{t['name'] if t else 'deleted'}» v{exp.get('origin_template_version')}"
    return exp.get("origin_preset") or ""


def draft_of(exp):
    return st.session_state.drafts.setdefault(exp["id"], copy.deepcopy(exp["config"]))


def replace_draft(exp, cfg):
    ss = st.session_state
    ss.drafts[exp["id"]] = cfg; ss.draft_version[exp["id"]] = ss.draft_version.get(exp["id"], 0) + 1


def k(name, exp):
    """Widget key bound to the experiment and to the draft version, so reopening or discarding resets the widgets."""
    return f"{name}_{exp['id']}_{st.session_state.draft_version.get(exp['id'], 0)}"


def unsaved(exp):
    return X.normalized_json(draft_of(exp)) != X.normalized_json(exp["config"])


def select_run(exp, kind, run_id):
    st.session_state.selected_run.setdefault(exp["id"], {})[kind] = run_id


def selected_run(exp, kind):
    runs = experiments().runs(exp["id"], kind=kind)
    if not runs:
        return None
    wanted = st.session_state.selected_run.get(exp["id"], {}).get(kind)
    return next((r for r in runs if r["id"] == wanted), runs[0])


def selected_replay_results():
    exp = current_experiment()
    if exp is None:
        return None
    run = selected_run(exp, "replay")
    if run is None:
        return None
    try:
        return experiments().load_run(run["id"])
    except Exception:
        return None


# ---- small formatters shared by the pages ----
def when(ts):
    """`2026-09-28T18:20:11+00:00` -> `2026-09-28 18:20`."""
    return (ts or "")[:16].replace("T", " ")


def schedule(cfg):
    return f"{cfg['seeds']} seeds × {cfg['episodes']:,} episodes × {len(cfg['policies'])} policies"


def profile_counts(agents):
    c = {}
    for a in agents:
        c[a["profile"]] = c.get(a["profile"], 0) + 1
    return ", ".join(f"{k_} {v}" for k_, v in sorted(c.items(), key=lambda kv: (PROFILE_ORDER.index(kv[0]) if kv[0] in PROFILE_ORDER else 99)))


def replay_run_label(r):
    pol = ", ".join(f"{policy_label(p)} {v:.3f}" for p, v in r["summary"]["policies"].items())
    return f"{when(r['ts'])} UTC · {r['user']} · v{r['config_version']} · {r['summary']['seeds']} seeds × {r['summary']['episodes']} · {pol}"


def live_run_label(r):
    sm = r["summary"]; pol = ", ".join(f"{policy_label(p)} {v:.3f}" for p, v in sm["policies"].items() if v is not None)
    return (f"{when(r['ts'])} UTC · {r['user']} · {sm.get('status')} · {sm.get('calls')} calls · "
            f"{float(sm.get('upper_cost_usd') or 0):.4f} USD · {sm.get('key_source')} key · {pol}")


# ---- population editor frames ----
def agents_frame(agents):
    rows = []
    for a in agents:
        rows.append({"id": a["id"], "base": a["base"], "profile": a["profile"], "lazy_p": a.get("lazy_p"),
                     "phase_length": a.get("phase_length"), "domains": ", ".join(a.get("domains", []))})
    return pd.DataFrame(rows, columns=["id", "base", "profile", "lazy_p", "phase_length", "domains"])


def frame_agents(df):
    agents = []
    for _, r in df.iterrows():
        if not isinstance(r["id"], str) or not r["id"].strip():
            continue
        a = {"id": r["id"].strip(), "base": r["base"], "profile": r["profile"]}
        if r["profile"] in ("lazy", "unstable"):
            a["lazy_p"] = float(r["lazy_p"]) if pd.notna(r["lazy_p"]) else 0.5
        if r["profile"] == "unstable":
            a["phase_length"] = int(r["phase_length"]) if pd.notna(r["phase_length"]) else 300
        if r["profile"] == "specialist":
            a["domains"] = [d.strip() for d in str(r["domains"] or "").split(",") if d.strip()]
        agents.append(a)
    return agents
