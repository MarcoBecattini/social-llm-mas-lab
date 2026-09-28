"""Social LLM-MAS Lab: experiments on outcome-based trust in a society of LLM agents, replayed or run live.

Entry point of the interface: theme and wordmark, sign-in gate, sidebar navigation by section, the context card of
the open experiment. The pages live in `lab/views`, one module each; the engine, the stores and the access control
in the `socialmas` package."""
import streamlit as st

from lab import auth, nav, state, theme, ui

st.set_page_config(page_title="Social LLM-MAS Lab", page_icon="🤝", layout="wide", initial_sidebar_state="expanded")
theme.inject()
principal = auth.gate()                       # sign-in and forced password change stop the script here
pages, sections = nav.build(principal)
state.begin_run(principal, pages)
page = st.navigation(sections, expanded=True)

with st.sidebar:
    context_slot = st.empty()                 # filled after the page ran, when the draft reflects this run's edits
    if auth.auth_required():
        st.caption(f"Signed in as **{ui.md(principal.name)}** · {principal.role_label}")
        if st.button("Sign out", key="signout", icon=":material/logout:", width="stretch"):
            auth.do_logout(principal)

page.run()

with context_slot.container():
    ui.sidebar_context(state.current_experiment())
