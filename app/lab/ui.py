"""Building blocks shared by the pages: the header with breadcrumb and primary action, cards and section titles, the
context strip of the open experiment, status badges, metric tiles, tables with plain labels, empty states, dialogs, and
the guided help (tooltips from `help.py`, switched off by the expert mode toggle in the sidebar)."""
import html
import re
from contextlib import contextmanager

import streamlit as st

from . import state
from .help import HELP

_MD_SPECIAL = re.compile(r"([\\`*_{}\[\]#+!|~<>])")


def md(text):
    """Escape Markdown so that experiment names and other user texts render literally."""
    return _MD_SPECIAL.sub(r"\\\1", str(text))


# ---- guided help and expert mode ----
def expert_mode():
    return bool(st.session_state.get("expert_mode", False))


def help(key):  # noqa: A001 - the name is the API: every call site reads help=ui.help(key)
    """The tooltip text for `key` in guided mode, None in expert mode. Unknown keys raise, so typos fail loudly."""
    text = HELP[key]
    return None if expert_mode() else text


def mode_toggle():
    """The sidebar switch between guided (tooltips on every page) and expert mode (no tooltips), kept for the session."""
    st.toggle("Expert mode", key="expert_mode", help=HELP["sidebar.expert_mode"])
    st.caption("Tooltips hidden; switch off to show the ⓘ explanations again." if expert_mode()
               else "Hover the ⓘ icons for explanations; switch on to hide them.")


# ---- page structure ----
def page_header(title, crumbs, caption=None, action=None, help=None):  # noqa: A002
    """Breadcrumb, one title, one sentence of purpose and, at the right, the page's primary action.
    `action` is a callable that renders the button and returns its state; the header returns that value."""
    left, right = st.columns([5, 1.7], vertical_alignment="bottom") if action else (st.container(), None)
    with left:
        st.markdown('<div class="lab-eyebrow">' + '<span class="sep">›</span>'.join(html.escape(str(c)) for c in crumbs) + "</div>",
                    unsafe_allow_html=True)
        st.title(title, anchor=False, help=help)
        if caption:
            st.caption(caption)
    if action is None:
        return None
    with right:
        return action()


def section(title, help=None):  # noqa: A002
    """Small-caps title that separates the groups of a page without a rule."""
    st.markdown(f'<div class="lab-section">{html.escape(title)}</div>', unsafe_allow_html=True, help=help)


@contextmanager
def card(title=None, text=None, key=None, help=None):  # noqa: A002
    with st.container(border=True, key=key):
        if title:
            st.markdown(f"**{title}**", help=help)
        if text:
            st.caption(text)
        yield


@contextmanager
def danger(key):
    """A container whose buttons are styled as destructive (see theme CSS)."""
    with st.container(key=f"danger_{key}"):
        yield


def go(name):
    st.switch_page(state.page(name))


# ---- badges and the experiment context ----
def badge(text, color="gray", icon=None):
    return f":{color}-badge[{(icon + ' ') if icon else ''}{text}]"


def saved_badge(exp):
    return badge("Unsaved changes", "orange", ":material/edit:") if state.unsaved(exp) else badge("Saved", "green", ":material/check:")


def status_badges(exp, editable=None, current=False):
    b = []
    if exp.get("origin_preset") or exp.get("origin_template"):
        b.append(badge(f"from {state.origin_label(exp)}", "gray", ":material/bookmark:"))
    b.append(badge(f"v{exp['config_version']}", "gray"))
    if exp.get("archived"):
        b.append(badge("archived", "orange", ":material/archive:"))
    if editable is False:
        b.append(badge("read-only", "gray", ":material/lock:"))
    if current:
        b.append(badge("open", "blue", ":material/folder_open:"))
    return " ".join(b)


def facts(exp, runs=None):
    cfg = exp["config"]
    runs = state.experiments().runs(exp["id"]) if runs is None else runs
    return (f"owner {exp['owner']} · {len(cfg['agents'])} agents · {state.schedule(cfg)} · {len(runs)} runs · "
            f"updated {state.when(exp['updated_at'])} UTC")


def context_strip(exp, slot=None, editable=None):
    """Name, badges and facts of the open experiment. With `slot` (an st.empty), rendered there at the end of the run,
    so that the unsaved state reflects the edits of this interaction."""
    host = slot.container() if slot is not None else st.container()
    with host, st.container(border=True, key="context_strip"):
        with st.container(horizontal=True, vertical_alignment="center", gap="medium"):
            st.subheader(exp["name"], anchor=False, width="content", help=help("configure.strip"))
            st.markdown(status_badges(exp, editable) + " " + saved_badge(exp), width="content")
        st.caption(facts(exp), help=help("experiments.card.facts"))


def sidebar_context(exp):
    with st.container(border=True, key="sidebar_context"):
        if exp is None:
            st.caption("No experiment open", help=help("sidebar.context"))
            st.page_link(state.page("experiments"), label="Open or create one", icon=":material/arrow_forward:")
        else:
            st.caption("Open experiment", help=help("sidebar.context"))
            st.markdown(f"**{md(exp['name'])}**")
            origin = state.origin_label(exp)
            st.caption(f"owner {exp['owner']} · v{exp['config_version']}" + (f" · from {origin}" if origin else ""))
            st.markdown(saved_badge(exp))


def require_experiment(title, caption=None):
    """The open experiment, or the page's empty state with the way to get one."""
    exp = state.current_experiment()
    if exp is None:
        page_header(title, ["Open experiment", title], caption)
        if empty_state("No experiment open", "Open one from the Experiments page, or create a new one from a paper preset; "
                       "this page then works on it.", button="Go to Experiments", key=f"goto_experiments_{title}"):
            go("experiments")
    return exp


# ---- content blocks ----
def empty_state(title, text, button=None, key=None, icon=":material/science:"):
    with st.container(border=True):
        st.markdown(f"{icon} **{title}**")
        st.caption(text)
        if button:
            return st.button(button, type="primary", key=key)
    return False


def tiles(items):
    """A row of metric tiles: label, value, a note in secondary ink (no arrow, no colour) and a tooltip."""
    for col, it in zip(st.columns(len(items)), items):
        with col:
            st.metric(it["label"], it["value"], delta=it.get("note"), delta_color="off", delta_arrow="off", border=True, help=it.get("help"))


def table(df, columns=None, help=None, **kwargs):  # noqa: A002
    """`columns` maps frame columns to a label, or to (label, format[, help key]): a printf format for numbers ("%.3f"),
    "bool" for checkboxes, None for text. Listed columns are shown in that order; the others are hidden. `help`, a
    text, is shown as a caption with a tooltip above the table in guided mode."""
    cfg = {}; order = None
    if columns:
        order = [c for c in columns if c in df.columns]
        for col, spec in columns.items():
            label, fmt, key = (spec, None, None) if isinstance(spec, str) else (tuple(spec) + (None, None))[:3]
            tip = globals()["help"](key) if key else None
            if fmt == "bool":
                cfg[col] = st.column_config.CheckboxColumn(label, help=tip)
            elif fmt:
                cfg[col] = st.column_config.NumberColumn(label, format=fmt, help=tip)
            else:
                cfg[col] = st.column_config.TextColumn(label, help=tip)
    if help:
        st.caption("How to read this table", help=help)
    st.dataframe(df, hide_index=True, width="stretch", column_config=cfg or None, column_order=order, **kwargs)


def chart(fig, help=None):  # noqa: A002
    """A Plotly figure with, in guided mode, a caption carrying the tooltip that explains how to read it."""
    st.plotly_chart(fig, width="stretch")
    if help:
        st.caption("How to read this chart", help=help)


def downloads(items):
    """A row of download buttons: (label, data, file name, mime[, help])."""
    for col, it in zip(st.columns(len(items)), items):
        label, data, name, mime = it[:4]
        col.download_button(label, data, file_name=name, mime=mime, icon=":material/download:", width="stretch", help=it[4] if len(it) > 4 else None)


# ---- dialogs: opened through session state so that a full rerun keeps them open; dismissing closes them ----
def open_dialog(kind, **payload):
    st.session_state["dialog"] = {"kind": kind, **payload}


def close_dialog():
    st.session_state.pop("dialog", None)


def dialog_state():
    return st.session_state.get("dialog")
