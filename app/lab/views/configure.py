"""Configure: population, rules and run settings of the open experiment, its differences from the origin preset, and
the save / discard bar. Widgets edit a per-session draft; runs always use the saved configuration."""
import json

import pandas as pd
import streamlit as st

from socialmas import data as D
from socialmas import experiments as X
from socialmas import sim as S
from socialmas.experiment import validate_config

from .. import state, ui
from ..state import POLICY_HELP, PROFILE_HELP, k, policy_label

TITLE = "Configure"


def render():
    exp = ui.require_experiment(TITLE, "Population, graph, trust rules and run settings of the open experiment.")
    if exp is None:
        return
    ex = state.experiments(); principal = state.principal()
    cfg = state.draft_of(exp); editable = ex.can_edit(principal, exp); dis = not editable
    ui.page_header(TITLE, ["Experiments", exp["name"]], "Population, graph, trust rules and run settings. Runs always use the saved configuration.",
                   help=ui.help("configure.page"))
    strip = st.empty()                       # filled at the end, when the draft reflects this run's edits
    if not editable:
        st.info("Read-only: only the owner or an administrator can change this experiment. Duplicate it from the Experiments page to work on a copy.",
                icon=":material/lock:")
    origin_card(ex, exp)
    population_card(cfg, editable, exp)
    rules_cards(cfg, dis, exp)
    run_settings_card(cfg, dis, exp)
    notes_card(ex, principal, exp, editable)
    action_bar(ex, principal, exp, cfg, editable)
    ui.context_strip(exp, slot=strip, editable=None if editable else False)


def origin_card(ex, exp):
    o = ex.origin(exp, state.principal())
    if o is None:
        return
    if o["private"]:
        with ui.card("Origin", f"Derived from a private template of another member, copied at version {o['copied_version']}. "
                     "Its content is visible only to its owner and the administrators.", help=ui.help("configure.origin")):
            st.markdown(ui.badge("private origin", "gray", ":material/lock:"))
        return
    diffs = X.config_diff(o["config"], exp["config"])
    if o["kind"] == "template":
        text = (f"Derived from the template «{o['name']}», copied at version {o['copied_version']}. "
                "The table compares the saved configuration with the template's current version.")
    else:
        text = f"Derived from {state.preset_label(o['ref'])}. The table compares the saved configuration with the preset."
    with ui.card("Origin", text, help=ui.help("configure.origin")):
        if o["kind"] == "template" and o["current_version"] != o["copied_version"]:
            st.warning(f"The template changed after this experiment was created: it is now at version {o['current_version']}, "
                       f"this experiment copied version {o['copied_version']}. The experiment does not follow the template; "
                       "the differences below include the template's later edits.", icon=":material/update:")
        if diffs:
            ui.table(pd.DataFrame([{"parameter": a, "preset": str(b), "this": str(c)} for a, b, c in diffs]),
                     {"parameter": ("Parameter", None, "configure.origin.parameter"), "preset": ("Preset", None, "configure.origin.preset"),
                      "this": ("This experiment", None, "configure.origin.this")})
        else:
            st.markdown(ui.badge("identical to its origin", "green", ":material/check:"))


def population_card(cfg, editable, exp):
    bases = list(cfg["base_models"])
    with ui.card("Population", "One row per agent. Bases: `nano` = gpt-4.1-nano, `mini` = gpt-4.1-mini, as measured in the competence map. "
                 "Lazy probability applies to lazy and unstable agents, phase length to unstable ones, domains (comma-separated) to specialists.",
                 help=ui.help("configure.population")):
        edited = st.data_editor(state.agents_frame(cfg["agents"]), num_rows="dynamic" if editable else "fixed", width="stretch", hide_index=True,
                                key=k("agents", exp), disabled=not editable,
                                column_config={"id": st.column_config.TextColumn("Agent id", required=True, width="small", help=ui.help("configure.population.id")),
                                               "base": st.column_config.SelectboxColumn("Base model", options=bases, required=True, width="small", help=ui.help("configure.population.base")),
                                               "profile": st.column_config.SelectboxColumn("Profile", options=list(S.PROFILES), required=True, help=ui.help("configure.population.profile")),
                                               "lazy_p": st.column_config.NumberColumn("Lazy probability", min_value=0.0, max_value=1.0, step=0.05, format="%.2f", help=ui.help("configure.population.lazy_p")),
                                               "phase_length": st.column_config.NumberColumn("Phase length", min_value=1, step=50, help=ui.help("configure.population.phase_length")),
                                               "domains": st.column_config.TextColumn("Domains", help=(ui.help("configure.population.domains") or "") + " Domains: " + ", ".join(S.DOMAINS))})
        if editable:
            cfg["agents"] = state.frame_agents(edited)
        st.caption(f"{len(cfg['agents'])} agents: {state.profile_counts(cfg['agents'])}.")
        with st.expander("Profile glossary"):
            for p_, h in PROFILE_HELP.items():
                st.markdown(f"- **{p_}**: {h}")


def rules_cards(cfg, dis, exp):
    c1, c2, c3 = st.columns(3)
    with c1:
        with ui.card("Tasks and declarations", "What agents declare and which tasks are drawn.", help=ui.help("configure.tasks")):
            cfg["declaration_threshold"] = st.slider("Declaration threshold (map pass rate)", 0.0, 1.0, float(cfg["declaration_threshold"]), 0.05, key=k("thr", exp), disabled=dis,
                                                     help=ui.help("configure.declaration_threshold"))
            cfg["task_pool"]["rule"] = st.radio("Task pool", ["all", "discriminating"], index=["all", "discriminating"].index(cfg["task_pool"]["rule"]),
                                                key=k("pool", exp), disabled=dis, horizontal=True, help=ui.help("configure.task_pool"))
        with ui.card("Graph and discovery", "Who can reach whom, and how the graph grows.", help=ui.help("configure.graph")):
            cfg["graph"]["degree"] = st.number_input("Initial degree (random connected graph)", 1, max(1, len(cfg["agents"]) - 1),
                                                     int(min(cfg["graph"]["degree"], max(1, len(cfg["agents"]) - 1))), key=k("deg", exp), disabled=dis,
                                                     help=ui.help("configure.degree"))
            cfg["social"]["radius"] = st.radio("Discovery radius", [1, 2], index=[1, 2].index(int(cfg["social"]["radius"])), horizontal=True, key=k("radius", exp),
                                               disabled=dis, help=ui.help("configure.radius"))
            cfg["social"]["befriend_on_success"] = st.checkbox("New relationship after a success", bool(cfg["social"]["befriend_on_success"]), key=k("befriend", exp),
                                                               disabled=dis, help=ui.help("configure.befriend"))
    with c2:
        with ui.card("Selection", "How a requester picks a worker among the agents it can reach.", help=ui.help("configure.selection")):
            cfg["social"]["epsilon"] = st.slider("Exploration ε", 0.0, 0.5, float(cfg["social"]["epsilon"]), 0.01, key=k("eps", exp), disabled=dis, help=ui.help("configure.epsilon"))
            cfg["social"]["max_reselections"] = st.number_input("Max reselections after refusals", 0, 10, int(cfg["social"]["max_reselections"]), key=k("resel", exp), disabled=dis,
                                                                help=ui.help("configure.max_reselections"))
            cfg["social"]["declared_prior"] = st.slider("Prior score, declared domain", 0.0, 1.0, float(cfg["social"]["declared_prior"]), 0.05, key=k("dp", exp), disabled=dis,
                                                        help=ui.help("configure.declared_prior"))
            cfg["social"]["undeclared_prior"] = st.slider("Prior score, undeclared domain", 0.0, 1.0, float(cfg["social"]["undeclared_prior"]), 0.05, key=k("up", exp), disabled=dis,
                                                          help=ui.help("configure.undeclared_prior"))
            cfg["social"]["referral_weight_default"] = st.slider("Referral weight for unknown referrers", 0.0, 1.0, float(cfg["social"]["referral_weight_default"]), 0.05,
                                                                 key=k("rw", exp), disabled=dis, help=ui.help("configure.referral_weight_default"))
    with c3:
        with ui.card("Trust (Beta reputation)", "Prior and evidence of the outcome-based trust record.", help=ui.help("configure.trust")):
            cfg["social"]["prior_alpha"] = st.number_input("Prior α", 0.1, 20.0, float(cfg["social"]["prior_alpha"]), 0.5, key=k("pa", exp), disabled=dis, help=ui.help("configure.prior_alpha"))
            cfg["social"]["prior_beta"] = st.number_input("Prior β", 0.1, 20.0, float(cfg["social"]["prior_beta"]), 0.5, key=k("pb", exp), disabled=dis, help=ui.help("configure.prior_beta"))
            cfg["social"]["domain_min_obs"] = st.number_input("Min observations for domain-specific evidence", 1, 20, int(cfg["social"]["domain_min_obs"]), key=k("mo", exp), disabled=dis,
                                                              help=ui.help("configure.domain_min_obs"))
        with ui.card("Analysis", "How the results are summarised.", help=ui.help("configure.analysis")):
            cfg["analysis"]["cold_start_episodes"] = st.number_input("Cold-start episodes", 100, 3000, int(cfg["analysis"]["cold_start_episodes"]), 100, key=k("cold", exp), disabled=dis,
                                                                     help=ui.help("configure.cold_start"))
            ids = [a["id"] for a in cfg["agents"]]
            cfg["best_fixed_agents"] = st.multiselect("best_fixed agents (first available is used)", ids,
                                                      default=[a for a in cfg.get("best_fixed_agents", []) if a in ids], key=k("bf", exp), disabled=dis,
                                                      help=ui.help("configure.best_fixed_agents"))


def run_settings_card(cfg, dis, exp):
    with ui.card("Run settings (replay)", "Seed i of your run is seed i of the paper, so shared seeds are comparable one by one.", help=ui.help("configure.run_settings")):
        r1, r2, r3, r4 = st.columns([1, 1.1, 1.9, 1])
        cfg["seeds"] = r1.slider("Seeds", 1, 20, int(cfg["seeds"]), key=k("seeds", exp), disabled=dis, help=ui.help("configure.seeds"))
        cfg["episodes"] = r2.select_slider("Episodes per seed and policy", options=list(range(300, 3001, 100)), value=int(cfg["episodes"]), key=k("episodes", exp), disabled=dis,
                                           help=ui.help("configure.episodes"))
        cfg["policies"] = r3.multiselect("Policies", list(S.POLICIES), default=[p_ for p_ in cfg["policies"] if p_ in S.POLICIES], format_func=policy_label,
                                         key=k("policies", exp), disabled=dis, help=ui.help("configure.policies"))
        cfg["analysis"]["bootstrap_resamples"] = r4.select_slider("Bootstrap resamples", options=[1000, 2000, 5000, 10000], value=int(cfg["analysis"]["bootstrap_resamples"]),
                                                                  key=k("boot", exp), disabled=dis, help=ui.help("configure.bootstrap"))
        with st.expander("Policy glossary"):
            for p_, h in POLICY_HELP.items():
                st.markdown(f"- **{policy_label(p_)}** (`{p_}`): {h}")


def notes_card(ex, principal, exp, editable):
    with ui.card("Notes", "Free text kept with the experiment (not part of the configuration).", help=ui.help("configure.notes")):
        notes = st.text_area("Notes", value=exp["notes"], key=k("notes", exp), disabled=not editable, height=80, label_visibility="collapsed")
        if editable and notes != exp["notes"] and st.button("Save notes", icon=":material/save:"):
            ex.set_notes(principal, exp["id"], notes); st.toast("Notes saved."); st.rerun()


def action_bar(ex, principal, exp, cfg, editable):
    problems = validate_config(cfg, D.load_competence_map()); dirty = state.unsaved(exp)
    with st.container(border=True, key="action_bar"):
        status, b1, b2 = st.columns([4, 1.3, 1.7], vertical_alignment="center")
        with status:
            if problems:
                st.error("Fix before saving:\n\n- " + "\n- ".join(problems))
            elif dirty:
                st.warning("Unsaved changes: save them to use them in runs.", icon=":material/edit:")
            else:
                st.caption(f":material/check_circle: All changes saved · configuration version {exp['config_version']}", help=ui.help("configure.state"))
        if editable:
            if b1.button("Discard changes", disabled=not dirty, width="stretch", key="discard", help=ui.help("configure.discard")):
                state.open_experiment(exp["id"]); st.rerun()
            if b2.button("Save configuration", type="primary", disabled=bool(problems) or not dirty, width="stretch", icon=":material/save:", key="save_config",
                         help=ui.help("configure.save")):
                try:
                    ex.update_config(principal, exp["id"], cfg); state.open_experiment(exp["id"]); st.toast("Configuration saved."); st.rerun()
                except X.ExperimentError as err:
                    st.error(str(err))
    tp = state.templates()
    if tp.can_create(principal) and st.button("Save as template", icon=":material/bookmark_add:", disabled=dirty, key="exp_to_template",
                                              help=ui.help("templates.from_experiment")):
        try:
            t = tp.from_experiment(principal, exp["id"])
        except X.ExperimentError as err:
            st.error(str(err))
        else:
            state.open_template(t["id"]); st.toast(f"Template {t['name']} created: private until you share it."); ui.go("template")
    with st.expander("Import or export the configuration JSON"):
        st.download_button("Download the draft as JSON", json.dumps(cfg, indent=2), file_name=f"{exp['name']}.json", mime="application/json", icon=":material/download:",
                           help=ui.help("configure.download"))
        if editable:
            up = st.file_uploader("Upload a configuration JSON to replace the draft", type="json", key=k("upload", exp), help=ui.help("configure.upload"))
            if up is not None:
                try:
                    new = json.load(up)
                    if "agents" in new and "social" in new:
                        state.replace_draft(exp, new); st.rerun()
                    else:
                        st.error("Not a population configuration (missing `agents` or `social`).")
                except json.JSONDecodeError as e:
                    st.error(f"Invalid JSON: {e}")
