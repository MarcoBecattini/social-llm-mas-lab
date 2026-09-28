"""Presets: the six read-only configurations of the paper's pre-registered runs, side by side and one by one (population,
rules, run settings, differences from another preset, reference results), with the way to start an experiment from one."""
import json

import pandas as pd
import streamlit as st

from socialmas import data as D
from socialmas import experiments as X

from .. import results, state, ui
from ..state import POLICY_HELP, PROFILE_HELP, policy_label

TITLE = "Presets"
INTRO = ("The paper's pre-registered runs as configurations. They are read-only, so that every replay can be checked against the "
         "paper; to change one, create an experiment from it and edit the copy in Configure.")
# The preset each one is naturally read against: variants against their main run, the v3 twin against the v3 run with liars.
BASE = {"paper-v2-radius1": "paper-v2", "paper-v2-pool174": "paper-v2", "paper-v2-degree2-posthoc": "paper-v2",
        "paper-v3-noliars": "paper-v3-liars", "paper-v3-liars": "paper-v2", "paper-v2": "paper-v3-liars"}
POOL_SIZE = {"all": 350, "discriminating": 174}
PARAMETERS = [("declaration_threshold", "Declaration threshold (map pass rate)"), ("task_pool.rule", "Task pool"),
              ("graph.type", "Graph"), ("graph.degree", "Initial degree"), ("social.radius", "Discovery radius"),
              ("social.befriend_on_success", "New relationship after a success"), ("social.epsilon", "Exploration ε"),
              ("social.max_reselections", "Max reselections after refusals"), ("social.declared_prior", "Prior score, declared domain"),
              ("social.undeclared_prior", "Prior score, undeclared domain"), ("social.referral_weight_default", "Referral weight for unknown referrers"),
              ("social.prior_alpha", "Prior α"), ("social.prior_beta", "Prior β"), ("social.domain_min_obs", "Min observations for domain-specific evidence"),
              ("analysis.cold_start_episodes", "Cold-start episodes"), ("analysis.bootstrap_resamples", "Bootstrap resamples"),
              ("seeds", "Seeds"), ("episodes", "Episodes per seed and policy"), ("best_fixed_agents", "best_fixed agents")]


def _get(cfg, path):
    for part in path.split("."):
        cfg = (cfg or {}).get(part)
    return cfg


def _full_height(df):
    """Height that shows every row of a table without an inner scrollbar."""
    return 35 * (len(df) + 1) + 3


def _show(v):
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, list):
        return ", ".join(map(str, v))
    return str(v)


def overview_frame():
    rows = []
    for name in D.preset_names():
        cfg = D.load_preset(name)
        rows.append({"preset": name, "agents": len(cfg["agents"]), "profiles": state.profile_counts(cfg["agents"]),
                     "degree": cfg["graph"]["degree"], "radius": cfg["social"]["radius"],
                     "pool": f"{cfg['task_pool']['rule']} ({POOL_SIZE.get(cfg['task_pool']['rule'], '?')})",
                     "policies": len(cfg["policies"]), "schedule": f"{cfg['seeds']} × {cfg['episodes']:,}"})
    return pd.DataFrame(rows)


def render():
    principal = state.principal()
    can_create = principal.can("replay.run") and not principal.legacy
    ui.page_header(TITLE, ["Reference", TITLE], INTRO, help=ui.help("presets.page"))
    ov = overview_frame()
    ui.table(ov,
             {"preset": ("Preset", None, "presets.overview.preset"), "agents": ("Agents", "%d", "presets.overview.agents"),
              "degree": ("Degree", "%d", "configure.degree"), "radius": ("Radius", "%d", "configure.radius"),
              "pool": ("Task pool", None, "configure.task_pool"), "policies": ("Policies", "%d", "presets.overview.policies"),
              "schedule": ("Seeds × episodes", None, "presets.overview.schedule"), "profiles": ("Profiles", None, "presets.overview.profiles")},
             help=ui.help("presets.overview"), height=_full_height(ov))
    names = D.preset_names()
    exp = state.current_experiment()
    start = names.index(exp["origin_preset"]) if "preset_choice" not in st.session_state and exp and exp.get("origin_preset") in names else 0
    name = st.selectbox("Preset", names, index=start, format_func=lambda n: D.PRESETS[n]["label"], key="preset_choice", help=ui.help("presets.choice"))
    cfg = D.load_preset(name); ref = D.load_reference(name)
    detail_header(name, cfg, can_create)
    differences_card(name, cfg)
    population_card(cfg)
    rules_card(cfg)
    policies_card(cfg)
    if ref:
        reference_card(name, ref)


def detail_header(name, cfg, can_create):
    with ui.card(D.PRESETS[name]["label"], D.PRESETS[name]["description"], key="preset_detail", help=ui.help("presets.detail")):
        rule = cfg["task_pool"]["rule"]
        ui.tiles([{"label": "Agents", "value": str(len(cfg["agents"])), "note": state.profile_counts(cfg["agents"]), "help": ui.help("presets.tile.agents")},
                  {"label": "Degree · radius", "value": f"{cfg['graph']['degree']} · {cfg['social']['radius']}",
                   "note": "graph grows" if cfg["social"]["befriend_on_success"] else "fixed graph", "help": ui.help("presets.tile.graph")},
                  {"label": "Tasks", "value": str(POOL_SIZE.get(rule, "?")), "note": rule, "help": ui.help("configure.task_pool")},
                  {"label": "Seeds", "value": str(cfg["seeds"]), "note": f"{cfg['episodes']:,} episodes · {len(cfg['policies'])} policies",
                   "help": ui.help("replay.metric.schedule")}])
        b1, b2, b3 = st.columns([1.4, 1.2, 1.2])
        if b1.button("Create experiment from this preset", type="primary", icon=":material/add:", disabled=not can_create, width="stretch",
                     key="preset_create", help=ui.help("presets.create")):
            st.session_state["new_preset"] = name
            ui.open_dialog("new"); ui.go("experiments")
        if b2.button("Compare with the paper's results", icon=":material/compare_arrows:", width="stretch", key="preset_to_paper",
                     help=ui.help("presets.to_paper")):
            st.session_state["ref_choice"] = name
            ui.go("paper")
        b3.download_button("Download JSON", json.dumps(cfg, indent=2), file_name=f"{name}.json", mime="application/json", icon=":material/download:",
                           width="stretch", key="preset_download", help=ui.help("presets.download"))


def differences_card(name, cfg):
    others = [n for n in D.preset_names() if n != name]
    with ui.card("Differences from another preset", "Only the parameters that change; the population is summarised in one row.",
                 help=ui.help("presets.differences")):
        other = st.selectbox("Compared with", others, index=others.index(BASE.get(name, others[0])), format_func=lambda n: D.PRESETS[n]["label"],
                             key=f"preset_other_{name}")
        diffs = X.config_diff(D.load_preset(other), cfg)
        if diffs:
            ui.table(pd.DataFrame([{"parameter": p, "other": _show(a), "this": _show(b)} for p, a, b in diffs]),
                     {"parameter": ("Parameter", None, "configure.origin.parameter"), "other": ("Compared preset", None, "presets.differences.other"),
                      "this": ("This preset", None, "presets.differences.this")})
        else:
            st.markdown(ui.badge("same configuration", "green", ":material/check:"))


def population_card(cfg):
    with ui.card("Population", f"{len(cfg['agents'])} agents. Bases: `nano` = gpt-4.1-nano, `mini` = gpt-4.1-mini.", help=ui.help("configure.population")):
        df = state.agents_frame(cfg["agents"])
        df["lazy_p"] = df["lazy_p"].map(lambda v: "" if pd.isna(v) else f"{v:.2f}")          # blank, not "None", where a profile has no such parameter
        df["phase_length"] = df["phase_length"].map(lambda v: "" if pd.isna(v) else f"{int(v)}")
        ui.table(df,
                 {"id": ("Agent id", None, "configure.population.id"), "base": ("Base model", None, "configure.population.base"),
                  "profile": ("Profile", None, "configure.population.profile"), "lazy_p": ("Lazy probability", None, "configure.population.lazy_p"),
                  "phase_length": ("Phase length", None, "configure.population.phase_length"), "domains": ("Domains", None, "configure.population.domains")}, height=_full_height(df))
        with st.expander("Profile glossary"):
            for p_, h in PROFILE_HELP.items():
                st.markdown(f"- **{p_}**: {h}")


def rules_card(cfg):
    with ui.card("Rules and run settings", "Every parameter of the preset, with the names used on the Configure page.", help=ui.help("presets.rules")):
        df = pd.DataFrame([{"parameter": label, "value": _show(_get(cfg, path)), "path": path} for path, label in PARAMETERS])
        ui.table(df,
                 {"parameter": ("Parameter", None, "presets.rules.parameter"), "value": ("Value", None, "presets.rules.value"),
                  "path": ("Key in the JSON", None, "configure.origin.parameter")}, height=_full_height(df))


def policies_card(cfg):
    with ui.card("Policies compared", "The selection rules each seed runs, on the same episodes.", help=ui.help("configure.policies")):
        for p_ in cfg["policies"]:
            st.markdown(f"- **{policy_label(p_)}** (`{p_}`): {POLICY_HELP.get(p_, '')}")


def reference_card(name, ref):
    with ui.card("Pre-registered results", f"Generated {ref['generated_utc'][:10]}; the full tables and charts are on the Paper comparison page.",
                 help=ui.help("presets.reference")):
        ui.tiles(results.replay_tiles(ref, reference=True))
