"""Account: who you are, what your role allows, and your password."""
import streamlit as st

from socialmas import access as ACC

from .. import auth, state, ui

TITLE = "Account"


def render():
    principal = state.principal()
    ui.page_header(TITLE, ["You", TITLE], "Your identity in the laboratory and what your role allows.")
    with ui.card("Profile", help=ui.help("account.profile")):
        st.markdown(f"**{ui.md(principal.name)}** &nbsp; `{principal.id}` &nbsp; " + ui.badge(principal.role_label, "blue", ":material/badge:"))
        st.markdown("You can: " + " ".join(ui.badge(c, "gray") for c in sorted(principal.capabilities)), help=ui.help("account.capabilities"))
        with st.expander("What each capability means"):
            for c in sorted(principal.capabilities):
                st.markdown(f"- `{c}`: {ACC.CAPABILITIES[c]}")
    if auth.auth_required() and not principal.legacy:
        with ui.card("Change password", f"At least {ACC.PASSWORD_MIN} characters. Changing it signs out your other sessions.", help=ui.help("account.password")):
            auth.password_change_form(principal)
    elif principal.legacy:
        st.info("The bootstrap credential has no account: create yours on the Administration page.", icon=":material/info:")
