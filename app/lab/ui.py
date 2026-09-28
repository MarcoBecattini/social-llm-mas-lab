"""Building blocks shared by the pages: the header with breadcrumb and primary action, cards and section titles, the
context strip of the open experiment, status badges, metric tiles, tables with plain labels, empty states, dialogs."""
import html
import re
from contextlib import contextmanager

import streamlit as st

from . import state

_MD_SPECIAL = re.compile(r"([\\`*_{}\[\]#+!|~<>])")


def md(text):
    """Escape Markdown so that experiment names and other user texts render literally."""
    return _MD_SPECIAL.sub(r"\\\1", str(text))


# ---- page structure ----
def page_header(title, crumbs, caption=None, action=None):
    """Breadcrumb, one title, one sentence of purpose and, at the right, the page's primary action.
    `action` is a callable that renders the button and returns its state; the header returns that value."""
    left, right = st.columns([5, 1.7], vertical_alignment="bottom") if action else (st.container(), None)
    with left:
        st.markdown('<div class="lab-eyebrow">' + '<span class="sep">›</span>'.join(html.escape(str(c)) for c in crumbs) + "</div>",
                    unsafe_allow_html=True)
        st.title(title, anchor=False)
        if caption:
            st.caption(caption)
    if action is None:
        return None
    with right:
        return action()


def section(title):
    """Small-caps title that separates the groups of a page without a rule."""
    st.markdown(f'<div class="lab-section">{html.escape(title)}</div>', unsafe_allow_html=True)


@contextmanager
def card(title=None, help=None, key=None):
    with st.container(border=True, key=key):
        if title:
            st.markdown(f"**{title}**")
        if help:
            st.caption(help)
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
    if exp.get("origin_preset"):
        b.append(badge(f"from {exp['origin_preset']}", "gray", ":material/bookmark:"))
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
            st.subheader(exp["name"], anchor=False, width="content")
            st.markdown(status_badges(exp, editable) + " " + saved_badge(exp), width="content")
        st.caption(facts(exp))


def sidebar_context(exp):
    with st.container(border=True, key="sidebar_context"):
        if exp is None:
            st.caption("No experiment open")
            st.page_link(state.page("experiments"), label="Open or create one", icon=":material/arrow_forward:")
        else:
            st.caption("Open experiment")
            st.markdown(f"**{md(exp['name'])}**")
            st.caption(f"owner {exp['owner']} · v{exp['config_version']}" + (f" · from {exp['origin_preset']}" if exp.get("origin_preset") else ""))
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
    """A row of metric tiles: label, value and a note in secondary ink (no arrow, no colour)."""
    for col, it in zip(st.columns(len(items)), items):
        with col:
            st.metric(it["label"], it["value"], delta=it.get("note"), delta_color="off", delta_arrow="off", border=True, help=it.get("help"))


def table(df, columns=None, **kwargs):
    """`columns` maps frame columns to a label or to (label, format): a printf format for numbers ("%.3f"), "bool" for
    checkboxes, None for text. Listed columns are shown in that order; the others are hidden."""
    cfg = {}; order = None
    if columns:
        order = [c for c in columns if c in df.columns]
        for col, spec in columns.items():
            label, fmt = (spec, None) if isinstance(spec, str) else spec
            if fmt == "bool":
                cfg[col] = st.column_config.CheckboxColumn(label)
            elif fmt:
                cfg[col] = st.column_config.NumberColumn(label, format=fmt)
            else:
                cfg[col] = st.column_config.TextColumn(label)
    st.dataframe(df, hide_index=True, width="stretch", column_config=cfg or None, column_order=order, **kwargs)


def downloads(items):
    """A row of download buttons: (label, data, file name, mime)."""
    for col, (label, data, name, mime) in zip(st.columns(len(items)), items):
        col.download_button(label, data, file_name=name, mime=mime, icon=":material/download:", width="stretch")


# ---- dialogs: opened through session state so that a full rerun keeps them open; dismissing closes them ----
def open_dialog(kind, **payload):
    st.session_state["dialog"] = {"kind": kind, **payload}


def close_dialog():
    st.session_state.pop("dialog", None)


def dialog_state():
    return st.session_state.get("dialog")
