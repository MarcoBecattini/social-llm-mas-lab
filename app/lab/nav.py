"""The pages of the laboratory and the sidebar sections each role sees.

Page objects are created once per run (st.navigation marks the current one on them) and kept in session state by
`state.begin_run`, so that pages can switch to each other with `st.switch_page`."""
import streamlit as st

from .views import account, admin, configure, experiments, history, live, method, paper, presets, replay, template

SPECS = [("experiments", experiments.render, "Experiments", ":material/science:"),
         ("presets", presets.render, "Presets and templates", ":material/bookmarks:"),
         ("template", template.render, "Template editor", ":material/edit_note:"),
         ("configure", configure.render, "Configure", ":material/tune:"),
         ("replay", replay.render, "Replay", ":material/play_circle:"),
         ("live", live.render, "Live", ":material/bolt:"),
         ("history", history.render, "History", ":material/history:"),
         ("paper", paper.render, "Paper comparison", ":material/compare_arrows:"),
         ("method", method.render, "Data and method", ":material/menu_book:"),
         ("account", account.render, "Account", ":material/person:"),
         ("admin", admin.render, "Administration", ":material/admin_panel_settings:")]


def build(principal):
    """(pages by name, sections for st.navigation) for this principal's role."""
    pages = {name: st.Page(fn, title=title, icon=icon, url_path=name, default=(name == "experiments")) for name, fn, title, icon in SPECS}
    if not principal.can("live.run"):
        pages.pop("live")
    if not principal.can("users.manage"):
        pages.pop("admin")
    sections = {"Laboratory": [pages["experiments"], pages["presets"], pages["template"]],
                "Open experiment": [pages[n] for n in ("configure", "replay", "live", "history") if n in pages],
                "Reference": [pages["paper"], pages["method"]],
                "You": [pages["account"]]}
    if "admin" in pages:
        sections["Administration"] = [pages["admin"]]
    return pages, sections
