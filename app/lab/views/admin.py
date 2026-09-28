"""Administration: accounts and roles, the shared OpenAI key with per-user allowances and a global cap, the access log."""
import pandas as pd
import streamlit as st

from socialmas import access as ACC

from .. import auth, state, ui

TITLE = "Administration"
USER_COLUMNS = {"id": "Id", "name": "Name", "role_label": ("Role", None, "admin.accounts.role"), "active": ("Active", "bool", "admin.accounts.active"),
                "must_change_password": ("Temporary password", "bool", "admin.accounts.temporary"),
                "shared_allowance_usd": ("Shared key allowance USD", "%.2f", "admin.accounts.allowance"), "spent": ("Spent on shared key", "%.4f", "admin.accounts.spent"),
                "created_at": "Created", "updated_at": "Updated"}


def render():
    acc = auth.access(); principal = state.principal()
    ui.page_header(TITLE, [TITLE], "Accounts and roles, the shared OpenAI key with per-user allowances, and the access log.", help=ui.help("admin.page"))
    if acc.persistent_warning:
        st.warning(acc.persistent_warning)
    if principal.legacy:
        st.info("You are signed in with the bootstrap credential. Create your own SysAdmin account below, then sign out and in with it.", icon=":material/info:")
    render_dialogs(acc, principal)
    names = ["Accounts"]
    key_tab = principal.can("settings.manage") and not principal.legacy
    if key_tab:
        names.append("Shared key")
    if principal.can("audit.view"):
        names.append("Access log")
    tabs = dict(zip(names, st.tabs(names)))
    with tabs["Accounts"]:
        accounts_tab(acc, principal)
    if key_tab:
        with tabs["Shared key"]:
            shared_key_tab(acc, principal)
    if "Access log" in tabs:
        with tabs["Access log"]:
            log_tab(acc)


def accounts_tab(acc, principal):
    users = acc.list_users()
    st.subheader("Accounts", anchor=False, help=ui.help("admin.accounts"))
    if users:
        udf = pd.DataFrame(users); udf["spent"] = [acc.spent(u["id"]) for u in users]
        udf["created_at"] = udf["created_at"].map(state.when); udf["updated_at"] = udf["updated_at"].map(state.when)
        ui.table(udf, USER_COLUMNS)
    else:
        st.caption("No accounts yet.")
    roles = list(ACC.ROLES)
    c1, c2 = st.columns(2)
    with c1, ui.card("Add an account", "No self sign-up: the person must change the temporary password at the first login.", help=ui.help("admin.add")):
        with st.form("add_user", clear_on_submit=True, border=False):
            uid = st.text_input("Id (lowercase letters, digits, dots, dashes, underscores)", max_chars=ACC.ID_MAX, help=ui.help("admin.add.id"))
            name = st.text_input("Name", max_chars=ACC.NAME_MAX, help=ui.help("admin.add.name"))
            role = st.selectbox("Role", roles, format_func=lambda r: f"{ACC.ROLES[r]['label']}: " + ", ".join(sorted(ACC.ROLES[r]["capabilities"])), help=ui.help("admin.add.role"))
            pwd = st.text_input(f"Temporary password (at least {ACC.PASSWORD_MIN} characters)", type="password", help=ui.help("admin.add.password"))
            add = st.form_submit_button("Create account", type="primary", icon=":material/person_add:")
        if add:
            try:
                acc.upsert_user(principal, uid, name, role, password=pwd)
                st.toast(f"Account {uid.strip().lower()} created."); st.rerun()
            except ACC.AccessError as e:
                st.error(str(e))
    with c2, ui.card("Edit an account", "Deactivation ends the person's sessions; prefer it to removal.", help=ui.help("admin.edit")):
        ids = [u["id"] for u in users]
        if ids:
            target = st.selectbox("Account", ids, key="edit_target")
            u = acc.get_user(target)
            with st.form("edit_user", border=False):
                name = st.text_input("Name", value=u["name"], max_chars=ACC.NAME_MAX, help=ui.help("admin.add.name"))
                role = st.selectbox("Role", roles, index=roles.index(u["role"]) if u["role"] in roles else 0, format_func=lambda r: ACC.ROLES[r]["label"], help=ui.help("admin.add.role"))
                active = st.checkbox("Active (unchecked = deactivated: cannot sign in, sessions end)", value=u["active"], help=ui.help("admin.edit.active"))
                newpwd = st.text_input("Set a temporary password (leave empty to keep the current one)", type="password", help=ui.help("admin.edit.password"))
                allowance = st.number_input("Allowance on the shared OpenAI key, USD (0 = cannot use it)", min_value=0.0, max_value=1000.0,
                                            value=float(u.get("shared_allowance_usd", 0.0)), step=0.05, format="%.2f", help=ui.help("admin.edit.allowance"))
                save = st.form_submit_button("Save account", type="primary", icon=":material/save:")
            if save:
                try:
                    acc.upsert_user(principal, target, name, role, password=newpwd or None, active=active)
                    if abs(allowance - float(u.get("shared_allowance_usd", 0.0))) > 1e-9:
                        acc.set_allowance(principal, target, allowance)
                    st.toast("Account saved."); st.rerun()
                except ACC.AccessError as e:
                    st.error(str(e))
        else:
            st.caption("Nothing to edit yet.")
    with st.expander("Roles and capabilities"):
        st.caption("Roles are fixed bundles of capabilities", help=ui.help("admin.roles"))
        for r, spec in ACC.ROLES.items():
            st.markdown(f"- **{spec['label']}** (`{r}`): " + ", ".join(f"`{c}`" for c in sorted(spec["capabilities"])))
        st.markdown("Capabilities: " + "; ".join(f"`{c}` {d}" for c, d in ACC.CAPABILITIES.items()))


def shared_key_tab(acc, principal):
    st.subheader("Shared OpenAI key", anchor=False, help=ui.help("admin.shared_key"))
    st.caption("One key for the whole laboratory, pasted here by an administrator and stored encrypted on the data disk. It is never shown again "
               "and never logged. People use it on the Live page only within the allowance you give them in Accounts; every run is charged to their account.")
    status = acc.shared_key_status()
    k1, k2 = st.columns(2)
    with k1, ui.card("Key"):
        if status:
            st.success(f"Key set by {status['set_by']} on {state.when(status['set_at'])} UTC (ends with …{status['last4']}).", icon=":material/key:")
        else:
            st.info("No shared key configured.", icon=":material/key_off:")
        with st.form("shared_key", clear_on_submit=True, border=False):
            newkey = st.text_input("Paste the OpenAI API key" + (" to replace the current one" if status else ""), type="password", autocomplete="off",
                                   help=ui.help("admin.key_input"))
            setk = st.form_submit_button("Save key", type="primary", icon=":material/save:")
        if setk:
            try:
                acc.set_shared_key(principal, newkey); st.toast("Shared key saved."); st.rerun()
            except ACC.AccessError as e:
                st.error(str(e))
        if status:
            with ui.danger("remove_key"):
                if st.button("Remove the shared key", icon=":material/delete:", help=ui.help("admin.remove_key")):
                    ui.open_dialog("remove_key"); st.rerun()
    with k2, ui.card("Spending", f"Spent so far on the shared key: {acc.spent():.4f} USD of {acc.shared_key_global_cap():.2f}.", help=ui.help("admin.spending")):
        gcap = st.number_input("Global cap on shared-key spending, USD (all users together, upper cost)", min_value=0.0, max_value=10000.0,
                               value=float(acc.shared_key_global_cap()), step=0.5, format="%.2f", key="global_cap", help=ui.help("admin.global_cap"))
        if st.button("Save global cap", icon=":material/save:"):
            try:
                acc.set_shared_key_global_cap(principal, gcap); st.toast("Global cap saved."); st.rerun()
            except ACC.AccessError as e:
                st.error(str(e))
        sp = acc.spend_summary()
        if sp:
            ui.table(pd.DataFrame(sp), {"user": "User", "source": ("Key", None, "history.key"), "runs": ("Runs", "%d"), "usd": ("Upper cost USD", "%.4f", "history.cost"),
                                        "calls": ("Calls", "%d", "history.calls"), "last": "Last run"})


def log_tab(acc):
    st.subheader("Access log", anchor=False, help=ui.help("admin.log"))
    ev = acc.events(200)
    if ev:
        df = pd.DataFrame(ev)
        ui.table(df, {"ts": "When (UTC)", "actor": ("Actor", None, "admin.log.actor"), "action": ("Action", None, "admin.log.action"),
                      **{c: c.replace("_", " ") for c in df.columns if c not in ("ts", "actor", "action")}})
    else:
        st.caption("Empty.")


def render_dialogs(acc, principal):
    d = ui.dialog_state()
    if d and d["kind"] == "remove_key":
        remove_key_dialog(acc, principal)


@st.dialog("Remove the shared key", on_dismiss=ui.close_dialog)
def remove_key_dialog(acc, principal):
    st.markdown("Remove the shared laboratory key?")
    st.caption("Nobody will be able to run live episodes on it until an administrator pastes a key again. Allowances and the spending record are kept.")
    c1, c2 = st.columns(2)
    if c1.button("Cancel", width="stretch", key="rk_cancel"):
        ui.close_dialog(); st.rerun()
    with c2, ui.danger("rk"):
        if st.button("Remove key", type="primary", width="stretch", key="rk_ok"):
            acc.clear_shared_key(principal); ui.close_dialog(); st.toast("Shared key removed."); st.rerun()
