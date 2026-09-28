"""Template editor: name, description, sharing and archiving of the open template, and its configuration edited with the
same cards as the Configure page (a per-session draft, saved explicitly; every save bumps the version)."""
import json

import pandas as pd
import streamlit as st

from socialmas import data as D
from socialmas import experiments as X
from socialmas.experiment import validate_config

from .. import state, ui
from . import configure

TITLE = "Template editor"


def render():
    principal = state.principal(); tp = state.templates()
    t = state.current_template()
    if t is None:
        ui.page_header(TITLE, ["Laboratory", TITLE], "Population, rules and run settings of one of your templates.", help=ui.help("templates.editor"))
        if ui.empty_state("No template open", "Open one from the Presets and templates page (Edit template), or create one there with New template "
                          "or Save as template.", button="Go to Presets and templates", key="goto_presets", icon=":material/bookmarks:"):
            ui.go("presets")
        return
    editable = tp.can_edit(principal, t); dis = not editable
    cfg = state.draft_of(t)
    ui.page_header(TITLE, ["Laboratory", "Templates", t["name"]], "Edits a draft; nothing is stored until you save it. Experiments already "
                   "created from the template keep the version they copied.", help=ui.help("templates.editor"))
    if not editable:
        st.info("Read-only: only the owner or an administrator can change this template. Duplicate it from the Presets and templates page "
                "to work on your own copy.", icon=":material/lock:")
    identity_card(tp, principal, t, editable)
    origin_card(t)
    configure.population_card(cfg, editable, t)
    configure.rules_cards(cfg, dis, t)
    configure.run_settings_card(cfg, dis, t)
    action_bar(tp, principal, t, cfg, editable)


def identity_card(tp, principal, t, editable):
    with ui.card("Template", f"Owner {t['owner']} · version {t['config_version']} · updated {state.when(t['updated_at'])} UTC", key="template_identity",
                 help=ui.help("templates.identity")):
        c1, c2 = st.columns([3, 1.2], vertical_alignment="bottom")
        name = c1.text_input("Name", value=t["name"], key=f"tpl_name_{t['id']}", disabled=not editable, help=ui.help("templates.name"))
        shared = c2.toggle("Shared with the laboratory", value=t["shared"], key=f"tpl_shared_{t['id']}", disabled=not editable,
                           help=ui.help("templates.shared"))
        desc = st.text_area("Description", value=t["description"], key=f"tpl_desc_{t['id']}", disabled=not editable, height=80,
                            help=ui.help("templates.description"))
        if not editable:
            return
        if shared != t["shared"]:
            tp.set_shared(principal, t["id"], shared)
            st.toast("Shared: everyone in the laboratory can now see and use it." if shared else "Private again: only you and the administrators see it.")
            st.rerun()
        b1, b2, b3 = st.columns([1.2, 1.4, 1])
        if b1.button("Save name and description", disabled=(name.strip() == t["name"] and desc == t["description"]), width="stretch",
                     key="tpl_save_identity", icon=":material/save:"):
            try:
                if name.strip() != t["name"]:
                    tp.rename(principal, t["id"], name)
                if desc != t["description"]:
                    tp.set_description(principal, t["id"], desc)
            except X.ExperimentError as err:
                st.error(str(err)); return
            st.toast("Saved."); st.rerun()
        if b2.button("Create experiment from this template", width="stretch", key="tpl_new_experiment", icon=":material/add:",
                     disabled=state.unsaved(t), help=ui.help("templates.create")):
            st.session_state["new_preset"] = t["id"]; ui.open_dialog("new"); ui.go("experiments")
        with b3, ui.danger("tpl_archive"):
            if st.button("Archive", width="stretch", key="tpl_archive_btn", icon=":material/archive:", help=ui.help("templates.archive")):
                tp.archive(principal, t["id"]); st.session_state.tpl_id = None
                st.toast(f"Archived {t['name']}."); ui.go("presets")


def origin_card(t):
    kind, ref = t.get("origin_kind"), t.get("origin_ref")
    if kind == "preset" and ref in D.PRESETS:
        origin, label = D.load_preset(ref), f"preset {ref}"
    elif kind == "template" and state.templates().get_any(ref):
        src = state.templates().get_any(ref); origin, label = src["config"], f"template «{src['name']}» (current version)"
    elif kind == "experiment" and state.experiments().get(ref):
        src = state.experiments().get(ref); origin, label = src["config"], f"experiment «{src['name']}» (current configuration)"
    else:
        return
    diffs = X.config_diff(origin, t["config"])
    with ui.card("Origin", f"Created from {label}. The table compares the saved template with it.", help=ui.help("templates.origin")):
        if diffs:
            ui.table(pd.DataFrame([{"parameter": p, "origin": str(a), "this": str(b)} for p, a, b in diffs]),
                     {"parameter": ("Parameter", None, "configure.origin.parameter"), "origin": ("Origin", None, "templates.origin.value"),
                      "this": ("This template", None, "templates.origin.this")})
        else:
            st.markdown(ui.badge("identical to its origin", "green", ":material/check:"))


def action_bar(tp, principal, t, cfg, editable):
    problems = validate_config(cfg, D.load_competence_map()); dirty = state.unsaved(t)
    with st.container(border=True, key="template_action_bar"):
        status, b1, b2 = st.columns([4, 1.3, 1.7], vertical_alignment="center")
        with status:
            if problems:
                st.error("Fix before saving:\n\n- " + "\n- ".join(problems))
            elif dirty:
                st.warning("Unsaved changes: save them to use them in new experiments.", icon=":material/edit:")
            else:
                st.caption(f":material/check_circle: All changes saved · version {t['config_version']}", help=ui.help("templates.state"))
        if editable:
            if b1.button("Discard changes", disabled=not dirty, width="stretch", key="tpl_discard"):
                state.open_template(t["id"]); st.rerun()
            if b2.button("Save template", type="primary", disabled=bool(problems) or not dirty, width="stretch", icon=":material/save:", key="tpl_save",
                         help=ui.help("templates.save")):
                try:
                    tp.update_config(principal, t["id"], cfg); state.open_template(t["id"]); st.toast("Template saved."); st.rerun()
                except X.ExperimentError as err:
                    st.error(str(err))
    with st.expander("Import or export the configuration JSON"):
        st.download_button("Download the draft as JSON", json.dumps(cfg, indent=2), file_name=f"{t['name']}.json", mime="application/json",
                           icon=":material/download:", help=ui.help("configure.download"))
        if editable:
            up = st.file_uploader("Upload a configuration JSON to replace the draft", type="json", key=state.k("upload", t), help=ui.help("configure.upload"))
            if up is not None:
                try:
                    new = json.load(up)
                    if "agents" in new and "social" in new:
                        state.replace_draft(t, new); st.rerun()
                    else:
                        st.error("Not a population configuration (missing `agents` or `social`).")
                except json.JSONDecodeError as e:
                    st.error(f"Invalid JSON: {e}")
