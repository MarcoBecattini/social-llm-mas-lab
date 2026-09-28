"""Experiments: the laboratory's list as cards, and the dialogs that create, duplicate, rename and archive them."""
import streamlit as st

from socialmas import data as D
from socialmas import experiments as X

from .. import state, ui
from ..state import policy_label

TITLE = "Experiments"
INTRO = ("An experiment is a named configuration (population, graph, trust rules, run settings) with its history of replay "
         "and live runs. Everyone signed in sees them; the owner and administrators change them; anyone can duplicate one to work on a copy.")


def render():
    ex = state.experiments(); principal = state.principal()
    can_create = principal.can("replay.run") and not principal.legacy

    def action():
        with st.container(horizontal=True, horizontal_alignment="right"):
            return st.button("New experiment", type="primary", icon=":material/add:", disabled=not can_create, key="new_experiment", help=ui.help("experiments.new"))

    if ui.page_header(TITLE, ["Laboratory", TITLE], INTRO, action=action, help=ui.help("experiments.page")):
        ui.open_dialog("new")
    render_dialogs(ex, principal)
    everything = ex.list(include_archived=True)
    if not everything:
        if ui.empty_state("No experiments yet", "Start from one of the six paper presets: the new experiment is an exact copy of the "
                          "pre-registered run, and the Configure page shows how it differs from its origin as you change it.",
                          button="Create the first experiment" if can_create else None, key="create_first"):
            ui.open_dialog("new"); st.rerun()
        return
    f1, f2 = st.columns([3, 1.2], vertical_alignment="center")
    query = f1.text_input("Filter", placeholder="Filter by name, owner or preset", label_visibility="collapsed", key="exp_filter",
                          help=ui.help("experiments.filter")) if len(everything) > 5 else ""
    show_archived = f2.toggle("Show archived", key="show_archived", help=ui.help("experiments.show_archived"))
    exps = [e for e in everything if (show_archived or not e["archived"]) and _matches(e, query)]
    archived = sum(1 for e in everything if e["archived"])
    st.caption(f"{len(exps)} of {len(everything)} experiments" + (f" · {archived} archived" if archived and not show_archived else ""))
    if not exps:
        st.caption("No experiment matches the filter.")
    for e in exps:
        card(ex, principal, e, can_create)


def _matches(e, query):
    q = (query or "").strip().lower()
    return not q or q in e["name"].lower() or q in e["owner"].lower() or q in (e.get("origin_preset") or "").lower()


def _last_replay(runs):
    r = next((r for r in runs if r["kind"] == "replay"), None)
    if r is None:
        return None
    pol = r["summary"]["policies"]
    shown = [p for p in ("social", "social_refcheck", "random") if p in pol] or list(pol)[:2]
    return f"last replay {state.when(r['ts'])}: " + " · ".join(f"{policy_label(p)} {pol[p]:.3f}" for p in shown)


def card(ex, principal, e, can_create):
    runs = ex.runs(e["id"]); editable = ex.can_edit(principal, e); current = e["id"] == st.session_state.exp_id
    with st.container(border=True):
        main, side = st.columns([5, 1.5], vertical_alignment="center")
        with main:
            st.markdown(f"**{ui.md(e['name'])}** &nbsp; " + ui.status_badges(e, None if editable else False, current), help=ui.help("experiments.card"))
            st.caption(ui.facts(e, runs), help=ui.help("experiments.card.facts"))
            last = _last_replay(runs)
            if last:
                st.caption(":material/play_circle: " + last, help=ui.help("experiments.card.last_replay"))
        with side:
            if st.button("Open", key=f"open_{e['id']}", type="primary", icon=":material/folder_open:", width="stretch", help=ui.help("experiments.open")):
                state.open_experiment(e["id"]); ui.go("configure")
            with st.popover("More", icon=":material/more_horiz:", width="stretch", help=ui.help("experiments.more")):
                if can_create and st.button("Duplicate", key=f"dup_{e['id']}", icon=":material/content_copy:", width="stretch"):
                    ui.open_dialog("duplicate", exp_id=e["id"]); st.rerun()
                if editable and st.button("Rename", key=f"ren_{e['id']}", icon=":material/edit:", width="stretch"):
                    ui.open_dialog("rename", exp_id=e["id"]); st.rerun()
                if editable and e["archived"] and st.button("Restore", key=f"restore_{e['id']}", icon=":material/unarchive:", width="stretch"):
                    ex.archive(principal, e["id"], archived=False); st.toast(f"Restored {e['name']}."); st.rerun()
                if editable and not e["archived"]:
                    with ui.danger(f"arch_{e['id']}"):
                        if st.button("Archive", key=f"archive_{e['id']}", icon=":material/archive:", width="stretch"):
                            ui.open_dialog("archive", exp_id=e["id"]); st.rerun()


# ---- dialogs ----
def render_dialogs(ex, principal):
    d = ui.dialog_state()
    if not d:
        return
    if d["kind"] == "new":
        new_dialog(ex, principal); return
    exp = ex.get(d.get("exp_id"))
    if exp is None:
        ui.close_dialog(); return
    {"duplicate": duplicate_dialog, "rename": rename_dialog, "archive": archive_dialog}[d["kind"]](ex, principal, exp)


def _buttons(primary, key, danger=False):
    c1, c2 = st.columns(2)
    cancel = c1.button("Cancel", key=f"{key}_cancel", width="stretch")
    if danger:
        with c2, ui.danger(key):
            ok = st.button(primary, key=f"{key}_ok", type="primary", width="stretch")
    else:
        ok = c2.button(primary, key=f"{key}_ok", type="primary", width="stretch")
    if cancel:
        ui.close_dialog(); st.rerun()
    return ok


@st.dialog("New experiment", on_dismiss=ui.close_dialog)
def new_dialog(ex, principal):
    st.caption("Start from one of the paper's presets (read-only, they reproduce the pre-registered runs) or from a template you can see: "
               "the new experiment starts as an exact copy, and the Configure page always shows how it differs from its origin.")
    tp = state.templates()
    tpls = {t["id"]: t for t in tp.list(principal)}
    options = D.preset_names() + list(tpls)
    if st.session_state.get("new_preset") not in options:
        st.session_state.pop("new_preset", None)
    preset = st.selectbox("Start from", options, format_func=lambda n: f"Template · {tpls[n]['name']} ({tpls[n]['owner']}, v{tpls[n]['config_version']})"
                          if n in tpls else D.PRESETS[n]["label"], key="new_preset", help=ui.help("dialog.new.preset"))
    st.caption((tpls[preset]["description"] or "Template without a description.") if preset in tpls else D.PRESETS[preset]["description"])
    base = tpls[preset]["name"] if preset in tpls else preset
    name = st.text_input("Name", value=f"{base} (my copy)", key=f"new_name_{preset}", help=ui.help("dialog.new.name"))
    if _buttons("Create experiment", "new"):
        try:
            e = tp.new_experiment(principal, preset, name=name) if preset in tpls else ex.from_preset(principal, preset, name=name)
        except X.ExperimentError as err:
            st.error(str(err)); return
        state.open_experiment(e["id"]); ui.close_dialog(); st.toast(f"Created {e['name']}: it is now open.")
        ui.go("configure")


@st.dialog("Duplicate experiment", on_dismiss=ui.close_dialog)
def duplicate_dialog(ex, principal, exp):
    st.caption(f"A copy of **{ui.md(exp['name'])}** with the same configuration and notes, owned by you, without its runs.")
    name = st.text_input("Name of the copy", value=f"{exp['name']} (copy)", key=f"dup_name_{exp['id']}", help=ui.help("dialog.duplicate.name"))
    if _buttons("Duplicate", "dup"):
        try:
            e = ex.duplicate(principal, exp["id"], name)
        except X.ExperimentError as err:
            st.error(str(err)); return
        state.open_experiment(e["id"]); ui.close_dialog(); st.toast(f"Created {e['name']}: it is now open.")
        ui.go("configure")


@st.dialog("Rename experiment", on_dismiss=ui.close_dialog)
def rename_dialog(ex, principal, exp):
    name = st.text_input("New name", value=exp["name"], key=f"ren_name_{exp['id']}", help=ui.help("dialog.rename.name"))
    if _buttons("Rename", "ren"):
        try:
            ex.rename(principal, exp["id"], name)
        except X.ExperimentError as err:
            st.error(str(err)); return
        ui.close_dialog(); st.toast("Renamed."); st.rerun()


@st.dialog("Archive experiment", on_dismiss=ui.close_dialog)
def archive_dialog(ex, principal, exp):
    st.markdown(f"Archive **{ui.md(exp['name'])}**?")
    st.caption("It leaves the list and, if open, is closed. Its configuration and runs are kept: it can be restored at any time "
               "from the list with *Show archived*.")
    if _buttons("Archive", "arch", danger=True):
        try:
            ex.archive(principal, exp["id"], archived=True)
        except X.ExperimentError as err:
            st.error(str(err)); return
        if st.session_state.exp_id == exp["id"]:
            state.close_experiment()
        ui.close_dialog(); st.toast(f"Archived {exp['name']}."); st.rerun()
