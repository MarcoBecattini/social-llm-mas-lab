"""Presets and templates: the six read-only configurations of the paper's pre-registered runs and the personal templates
of the laboratory, side by side and one by one (population, rules, run settings, differences from another configuration,
reference results for presets), with the ways to start an experiment or a new template from them."""
import json

import pandas as pd
import streamlit as st

from socialmas import data as D
from socialmas import experiments as X

from .. import results, state, ui
from ..state import POLICY_HELP, PROFILE_HELP, policy_label

TITLE = "Presets and templates"
INTRO = ("Configurations to start experiments from. The paper's presets are read-only, so that every replay can be checked against "
         "the paper. Templates are your own starting points: editable, private unless you share them with the laboratory.")
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
    return 36 * (len(df) + 1) + 4


def _show(v):
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, list):
        return ", ".join(map(str, v))
    return str(v)


# ---- sources: presets are keyed by name (paper-…), templates by id (tpl-…) ----
def sources(principal, include_archived=False):
    """{key: (label, template or None)} for every preset and every template this principal can see (archived ones on request)."""
    out = {n: (D.PRESETS[n]["label"], None) for n in D.preset_names()}
    for t in state.templates().list(principal, include_archived=include_archived):
        out[t["id"]] = (f"Template · {t['name']} ({t['owner']}, v{t['config_version']}{', archived' if t['archived'] else ''})", t)
    return out


def is_template(key):
    return key.startswith("tpl-")


def config_of(key, srcs):
    return srcs[key][1]["config"] if is_template(key) else D.load_preset(key)


def overview_frame():
    rows = []
    for name in D.preset_names():
        cfg = D.load_preset(name)
        rows.append({"preset": name, "agents": len(cfg["agents"]), "profiles": state.profile_counts(cfg["agents"]),
                     "degree": cfg["graph"]["degree"], "radius": cfg["social"]["radius"],
                     "pool": f"{cfg['task_pool']['rule']} ({POOL_SIZE.get(cfg['task_pool']['rule'], '?')})",
                     "policies": len(cfg["policies"]), "schedule": f"{cfg['seeds']} × {cfg['episodes']:,}"})
    return pd.DataFrame(rows)


def templates_frame(tpls):
    return pd.DataFrame([{"name": t["name"], "owner": t["owner"], "visibility": ("archived" if t["archived"] else "shared" if t["shared"] else "private"),
                          "version": t["config_version"], "agents": len(t["config"]["agents"]), "radius": t["config"]["social"]["radius"],
                          "schedule": f"{t['config']['seeds']} × {t['config']['episodes']:,}", "updated": state.when(t["updated_at"])} for t in tpls])


def render():
    principal = state.principal(); tp = state.templates()
    can_create = tp.can_create(principal)

    def action():
        with st.container(horizontal=True, horizontal_alignment="right"):
            return st.button("New template", type="primary", icon=":material/add:", disabled=not can_create, key="new_template", help=ui.help("templates.new"))

    if ui.page_header(TITLE, ["Laboratory", TITLE], INTRO, action=action, help=ui.help("presets.page")):
        ui.open_dialog("new_template")
    d = ui.dialog_state()
    if d and d["kind"] == "new_template":
        new_template_dialog(principal)
    show_archived = st.session_state.get("show_archived_templates", False)
    srcs = sources(principal, include_archived=show_archived)

    ui.section("Paper presets", help=ui.help("presets.overview"))
    ov = overview_frame()
    ui.table(ov,
             {"preset": ("Preset", None, "presets.overview.preset"), "agents": ("Agents", "%d", "presets.overview.agents"),
              "degree": ("Degree", "%d", "configure.degree"), "radius": ("Radius", "%d", "configure.radius"),
              "pool": ("Task pool", None, "configure.task_pool"), "policies": ("Policies", "%d", "presets.overview.policies"),
              "schedule": ("Seeds × episodes", None, "presets.overview.schedule"), "profiles": ("Profiles", None, "presets.overview.profiles")},
             height=_full_height(ov))

    ui.section("Templates", help=ui.help("templates.section"))
    if any(t["archived"] for t in tp.list(principal, include_archived=True)):
        st.toggle("Show archived templates", key="show_archived_templates", help=ui.help("templates.show_archived"))
    tpls = [s[1] for k, s in srcs.items() if is_template(k)]
    if tpls:
        tf = templates_frame(tpls)
        ui.table(tf, {"name": ("Template", None, "templates.table.name"), "owner": ("Owner", None, "templates.table.owner"),
                      "visibility": ("Visibility", None, "templates.table.visibility"), "version": ("Version", "%d", "templates.table.version"),
                      "agents": ("Agents", "%d", "presets.overview.agents"), "radius": ("Radius", "%d", "configure.radius"),
                      "schedule": ("Seeds × episodes", None, "presets.overview.schedule"), "updated": ("Updated (UTC)", None, "templates.table.updated")},
                 height=_full_height(tf))
    else:
        st.caption("No templates yet. Create one with *New template*, with *Save as template* below, or from an experiment on the Configure page.")

    keys = list(srcs)
    exp = state.current_experiment()
    if "preset_choice" in st.session_state and st.session_state["preset_choice"] not in keys:
        del st.session_state["preset_choice"]                                    # a template archived or unshared meanwhile
    origin = (exp.get("origin_template") or exp.get("origin_preset")) if exp else None
    start = keys.index(origin) if "preset_choice" not in st.session_state and origin in keys else 0
    key = st.selectbox("Show in detail", keys, index=start, format_func=lambda k: srcs[k][0], key="preset_choice", help=ui.help("presets.choice"))
    cfg = config_of(key, srcs)
    if is_template(key):
        template_header(principal, srcs[key][1], can_create)
    else:
        detail_header(key, cfg, can_create)
    differences_card(key, cfg, srcs)
    population_card(cfg)
    rules_card(cfg)
    policies_card(cfg)
    if not is_template(key):
        ref = D.load_reference(key)
        if ref:
            reference_card(key, ref)


def _tiles(cfg):
    rule = cfg["task_pool"]["rule"]
    ui.tiles([{"label": "Agents", "value": str(len(cfg["agents"])), "note": state.profile_counts(cfg["agents"]), "help": ui.help("presets.tile.agents")},
              {"label": "Degree · radius", "value": f"{cfg['graph']['degree']} · {cfg['social']['radius']}",
               "note": "graph grows" if cfg["social"]["befriend_on_success"] else "fixed graph", "help": ui.help("presets.tile.graph")},
              {"label": "Tasks", "value": str(POOL_SIZE.get(rule, "?")), "note": rule, "help": ui.help("configure.task_pool")},
              {"label": "Seeds", "value": str(cfg["seeds"]), "note": f"{cfg['episodes']:,} episodes · {len(cfg['policies'])} policies",
               "help": ui.help("replay.metric.schedule")}])


def _start_experiment(key):
    st.session_state["new_preset"] = key
    ui.open_dialog("new"); ui.go("experiments")


def _save_as_template(principal, make):
    try:
        t = make()
    except X.ExperimentError as err:
        st.error(str(err)); return
    state.open_template(t["id"]); st.toast(f"Template {t['name']} created: private until you share it.")
    ui.go("template")


def detail_header(name, cfg, can_create):
    principal = state.principal()
    with ui.card(D.PRESETS[name]["label"], D.PRESETS[name]["description"], key="preset_detail", help=ui.help("presets.detail")):
        _tiles(cfg)
        b1, b2, b3, b4 = st.columns([1.5, 1.4, 1.2, 1])
        if b1.button("Start an experiment", type="primary", icon=":material/add:", disabled=not can_create, width="stretch",
                     key="preset_create", help=ui.help("presets.create")):
            _start_experiment(name)
        if b2.button("Paper's results", icon=":material/compare_arrows:", width="stretch", key="preset_to_paper",
                     help=ui.help("presets.to_paper")):
            st.session_state["ref_choice"] = name
            ui.go("paper")
        if b3.button("Save as template", icon=":material/bookmark_add:", disabled=not can_create, width="stretch", key="preset_to_template",
                     help=ui.help("templates.from_preset")):
            _save_as_template(principal, lambda: state.templates().from_preset(principal, name))
        b4.download_button("JSON", json.dumps(cfg, indent=2), file_name=f"{name}.json", mime="application/json", icon=":material/download:",
                           width="stretch", key="preset_download", help=ui.help("presets.download"))


def template_header(principal, t, can_create):
    tp = state.templates(); editable = tp.can_edit(principal, t)
    badges = [ui.badge("shared" if t["shared"] else "private", "blue" if t["shared"] else "gray", ":material/group:" if t["shared"] else ":material/lock:"),
              ui.badge(f"v{t['config_version']}", "gray"), ui.badge(f"owner {t['owner']}", "gray")]
    with ui.card(t["name"], t["description"] or "No description.", key="template_detail", help=ui.help("templates.detail")):
        st.markdown(" ".join(badges) + (f" · from {template_origin_label(t)}" if t.get("origin_kind") else ""))
        _tiles(t["config"])
        b1, b2, b3, b4 = st.columns([1.5, 1.2, 1.2, 1])
        if b1.button("Start an experiment", type="primary", icon=":material/add:", disabled=not can_create or t["archived"], width="stretch",
                     key="template_create", help=ui.help("templates.create")):
            _start_experiment(t["id"])
        if b2.button("Edit template" if editable else "View in editor", icon=":material/edit_note:", width="stretch", key="template_edit",
                     help=ui.help("templates.edit")):
            state.open_template(t["id"]); ui.go("template")
        if b3.button("Duplicate as template", icon=":material/content_copy:", disabled=not can_create, width="stretch", key="template_duplicate",
                     help=ui.help("templates.duplicate")):
            _save_as_template(principal, lambda: tp.duplicate(principal, t["id"]))
        b4.download_button("JSON", json.dumps(t["config"], indent=2), file_name=f"{t['name']}.json", mime="application/json", icon=":material/download:",
                           width="stretch", key="template_download", help=ui.help("presets.download"))


def template_origin_label(t):
    kind, ref = t.get("origin_kind"), t.get("origin_ref")
    if kind == "preset":
        return f"preset {ref}"
    if kind == "template":
        src = state.templates().get(state.principal(), ref)
        return f"template «{src['name']}»" if src else "a template you cannot see"
    if kind == "experiment":
        src = state.experiments().get(ref)
        return f"experiment «{src['name'] if src else 'deleted'}»"
    return ""


def _default_other(key, srcs, others):
    if is_template(key):
        t = srcs[key][1]
        if t.get("origin_kind") in ("preset", "template") and t.get("origin_ref") in others:
            return t["origin_ref"]
        return "paper-v2" if "paper-v2" in others else others[0]
    return BASE.get(key, others[0])


def differences_card(key, cfg, srcs):
    others = [k for k in srcs if k != key]
    with ui.card("Differences from another configuration", "Only the parameters that change; the population is summarised in one row.",
                 help=ui.help("presets.differences")):
        other = st.selectbox("Compared with", others, index=others.index(_default_other(key, srcs, others)), format_func=lambda k: srcs[k][0],
                             key=f"preset_other_{key}")
        diffs = X.config_diff(config_of(other, srcs), cfg)
        if diffs:
            ui.table(pd.DataFrame([{"parameter": p, "other": _show(a), "this": _show(b)} for p, a, b in diffs]),
                     {"parameter": ("Parameter", None, "configure.origin.parameter"), "other": ("Compared with", None, "presets.differences.other"),
                      "this": ("Shown above", None, "presets.differences.this")})
        else:
            st.markdown(ui.badge("same configuration", "green", ":material/check:"))


@st.dialog("New template", on_dismiss=ui.close_dialog)
def new_template_dialog(principal):
    st.caption("A template is your own starting point for experiments. It starts as a copy of a preset or of a template you can see, "
               "is private until you share it, and is edited on the Template editor page.")
    srcs = sources(principal)
    src = st.selectbox("Start from", list(srcs), format_func=lambda k: srcs[k][0], key="new_template_source", help=ui.help("templates.dialog.source"))
    base = srcs[src][1]["name"] if is_template(src) else src
    name = st.text_input("Name", value=f"{base} (template)", key=f"new_template_name_{src}", help=ui.help("templates.dialog.name"))
    c1, c2 = st.columns(2)
    if c1.button("Cancel", key="new_template_cancel", width="stretch"):
        ui.close_dialog(); st.rerun()
    if c2.button("Create template", type="primary", key="new_template_ok", width="stretch"):
        tp = state.templates()
        make = (lambda: tp.duplicate(principal, src, name)) if is_template(src) else (lambda: tp.from_preset(principal, src, name=name))
        ui.close_dialog()
        _save_as_template(principal, make)


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
    with ui.card("Rules and run settings", "Every parameter, with the names used on the Configure page.", help=ui.help("presets.rules")):
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
