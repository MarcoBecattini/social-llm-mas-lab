"""Sign-in gate: login for everyone, roles decide what is shown (see socialmas/access.py). Sessions are a signed cookie.

The behaviour is the one of the previous single-file app: the same cookie, the same bootstrap flow, the same forced
password change; only the layout of the screens changed."""
import os

import streamlit as st
import streamlit.components.v1 as components

from socialmas import access as ACC


@st.cache_resource(show_spinner=False)
def access():
    return ACC.Access()


def hosted():
    return bool(os.environ.get("RENDER"))


def auth_required():
    return hosted() or os.environ.get("SOCIALMAS_REQUIRE_AUTH", "1") != "0"


def set_cookie(token, max_age=ACC.SESSION_TTL_SECONDS):
    secure = "; Secure" if hosted() else ""
    components.html(f"<script>document.cookie = '{ACC.COOKIE_NAME}={token}; Max-Age={int(max_age)}; Path=/; SameSite=Lax{secure}';</script>", height=0)


def clear_cookie():
    components.html(f"<script>document.cookie = '{ACC.COOKIE_NAME}=; Max-Age=0; Path=/; SameSite=Lax';</script>", height=0)


def current_principal():
    """Principal of this browser session: from session state, else from the signed cookie sent with the page load."""
    if not auth_required():
        return ACC.Principal("local", "Local user (authentication disabled)", "sysadmin")
    acc = access()
    legacy = st.session_state.get("legacy_principal")
    if legacy is not None:
        return legacy
    uid = st.session_state.get("principal_id")
    if uid:
        p = acc.principal_for(uid)
        if p is not None:
            return p
        st.session_state.pop("principal_id", None)
    try:
        token = st.context.cookies.get(ACC.COOKIE_NAME)
    except Exception:
        token = None
    if token:
        p = acc.verify_token(token)
        if p is not None:
            st.session_state.principal_id = p.id
            return p
    return None


def _centered():
    """The middle column of a three-column layout: sign-in screens are narrow cards, not full-width forms."""
    return st.columns([1, 1.2, 1])[1]


def login_screen():
    acc = access()
    with _centered():
        st.title("Social LLM-MAS Lab", anchor=False)
        st.caption("Outcome-based trust and social discovery among LLM agents. Replay over measured outcomes, or live with real calls. Sign in to continue.")
        if acc.persistent_warning:
            st.warning(acc.persistent_warning)
        if not acc.has_users() and not acc.bootstrap_active():
            st.error("No account exists yet and no bootstrap credential is configured. Set SOCIALMAS_ADMIN_USER and "
                     "SOCIALMAS_ADMIN_PASSWORD in the environment, restart, sign in with them and create the first SysAdmin account.")
            st.stop()
        if acc.bootstrap_active():
            st.info("First start: sign in with the bootstrap credential from the environment, then create your own SysAdmin account. "
                    "The bootstrap credential stops working as soon as the first account exists.")
        with st.form("login", border=True):
            st.markdown("**Sign in**")
            username = st.text_input("Username", autocomplete="username")
            password = st.text_input("Password", type="password", autocomplete="current-password")
            submitted = st.form_submit_button("Sign in", type="primary", width="stretch")
        if submitted:
            p = acc.authenticate(username, password)
            if p is None:
                st.error("Wrong username or password.")
            elif p.legacy:
                st.session_state.legacy_principal = p; st.rerun()
            else:
                st.session_state.principal_id = p.id
                set_cookie(acc.issue_token(p)); st.rerun()
    st.stop()


def do_logout(principal):
    access().logout(principal)
    for key in ("principal_id", "legacy_principal", "results"):
        st.session_state.pop(key, None)
    clear_cookie(); st.rerun()


def password_change_form(principal, forced=False):
    acc = access()
    with st.form("change_password", border=True):
        current = st.text_input("Current password", type="password", autocomplete="current-password")
        new = st.text_input(f"New password (at least {ACC.PASSWORD_MIN} characters)", type="password", autocomplete="new-password")
        again = st.text_input("Repeat the new password", type="password", autocomplete="new-password")
        ok = st.form_submit_button("Change password", type="primary")
    if ok:
        if new != again:
            st.error("The two new passwords differ."); return
        try:
            acc.change_password(principal, current, new)
        except ACC.AccessError as e:
            st.error(str(e)); return
        st.success("Password changed." + (" Welcome!" if forced else ""))
        set_cookie(acc.issue_token(acc.principal_for(principal.id)))
        st.rerun()


def gate():
    """The signed-in principal, or the sign-in / forced-password-change screen (which stop the script)."""
    principal = current_principal()
    if principal is None:
        login_screen()
    if principal.must_change_password:
        with _centered():
            st.title("Choose your own password", anchor=False)
            st.info("An administrator set a temporary password for your account. Choose your own to continue.")
            password_change_form(principal, forced=True)
            if st.button("Sign out"):
                do_logout(principal)
        st.stop()
    return principal
