"""Social LLM-MAS Lab: tune and rerun the replay experiment on outcome-based trust in a society of LLM agents."""
import copy
import io
import json
import time

import os

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components

from socialmas import access as ACC
from socialmas import data as D
from socialmas import sim as S
from socialmas.experiment import compare_to_reference, config_hash, estimate_seconds, rules_signature, run_experiment, validate_config
from socialmas.report import decline_frame, differences_frame, headline_frame, markdown_report, selection_frame, windows_frame

st.set_page_config(page_title="Social LLM-MAS Lab", page_icon="🤝", layout="wide")

# ---- palette (validated categorical slots, fixed order; identity never color-alone: dashes and markers too) ----
INK, INK2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e6e5e1", "#fcfcfb"
POLICY_STYLE = {  # slot colours in fixed order; reference lines in ink
    "random": ("#2a78d6", "dot", "circle"), "declared": ("#eb6834", "dash", "square"),
    "social_nobefriend": ("#1baf7a", "dashdot", "triangle-up"), "social_noref": ("#eda100", "longdash", "triangle-down"),
    "social": ("#e87ba4", "solid", "diamond"), "social_refcheck": ("#008300", "solid", "star"),
    "best_fixed": (INK2, "dash", "x"), "oracle": (INK2, "dot", "cross")}
POLICY_LABEL = {"random": "random", "declared": "declared", "best_fixed": "best fixed contact (ref.)", "oracle": "oracle (ref.)",
                "social_noref": "social, no referrals", "social_nobefriend": "social, no new relationships",
                "social": "social (full)", "social_refcheck": "social + referral check"}
PROFILE_ORDER = ["honest", "boaster", "impostor", "lazy", "specialist", "unstable", "liar"]
PROFILE_COLOR = dict(zip(PROFILE_ORDER, ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7"]))
MODEL_COLOR = ["#2a78d6", "#eb6834", "#1baf7a"]
LAYOUT = dict(template="simple_white", paper_bgcolor=SURFACE, plot_bgcolor=SURFACE, font=dict(color=INK, size=13),
              margin=dict(l=10, r=10, t=60, b=10), title_y=0.97, title_yanchor="top", hoverlabel=dict(bgcolor="white"))


def legend_below(n_series):
    """Horizontal legend under the x axis, with a bottom margin that fits it even when the chart is narrow."""
    rows = -(-n_series // 2)
    return dict(legend=dict(orientation="h", yanchor="top", y=-0.2, x=0, font=dict(size=11)),
                margin=dict(l=10, r=10, t=60, b=50 + 24 * rows))

PROFILE_HELP = {
    "honest": "declares the domains where its base model passes at least the declaration threshold; outcome = measured map",
    "boaster": "declares all seven domains; works like honest (a mild false claim)",
    "impostor": "declares all seven domains, always fails, still bills the call",
    "lazy": "declares like honest; with probability lazy_p returns an empty answer and still bills",
    "specialist": "declares only its listed domains and refuses tasks outside them (no cost, one extra message)",
    "unstable": "declares like honest; alternates phases of phase_length episodes: honest, lazy with lazy_p, honest, ...",
    "liar": "honest worker; when asked for opinions it reports the opposite verdict, amplified (malicious recommender)"}
POLICY_HELP = {
    "random": "uniform choice among reachable agents",
    "declared": "uniform choice among reachable agents that declare the task's domain",
    "best_fixed": "reference line: always the same best honest agent (assumes knowing who is best)",
    "oracle": "reference line: verified per-domain competence from a central registry",
    "social_noref": "own outcome-based trust, new relationships after success, no referral opinions",
    "social_nobefriend": "own trust plus referral opinions, but the graph never changes",
    "social": "own trust, referral opinions weighted by trust in the referrer as a worker, new relationships after success",
    "social_refcheck": "as social, but referrals are weighted by the referrer's past referral accuracy (defence against liars)"}


# ---- accounts: login for everyone, roles decide what is shown (see socialmas/access.py) ----
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


def login_screen():
    acc = access()
    st.title("Social LLM-MAS Lab")
    st.caption("Outcome-based trust and social discovery among LLM agents. Sign in to continue.")
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
        username = st.text_input("Username", autocomplete="username")
        password = st.text_input("Password", type="password", autocomplete="current-password")
        submitted = st.form_submit_button("Sign in", type="primary")
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


def admin_panel(principal):
    acc = access()
    st.subheader("Accounts")
    if acc.persistent_warning:
        st.warning(acc.persistent_warning)
    if principal.legacy:
        st.info("You are signed in with the bootstrap credential. Create your own SysAdmin account below, then sign out and in with it.")
    users = acc.list_users()
    if users:
        udf = pd.DataFrame(users)[["id", "name", "role_label", "active", "must_change_password", "created_at", "updated_at"]]
        udf = udf.rename(columns={"role_label": "role", "must_change_password": "temporary password"})
        st.dataframe(udf, width="stretch", hide_index=True)
    else:
        st.caption("No accounts yet.")
    roles = list(ACC.ROLES)
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Add an account**")
        with st.form("add_user", clear_on_submit=True, border=True):
            uid = st.text_input("id (lowercase; letters, digits, . _ -)", max_chars=ACC.ID_MAX)
            name = st.text_input("Name", max_chars=ACC.NAME_MAX)
            role = st.selectbox("Role", roles, format_func=lambda r: f"{ACC.ROLES[r]['label']}: " + ", ".join(sorted(ACC.ROLES[r]["capabilities"])))
            pwd = st.text_input(f"Temporary password (at least {ACC.PASSWORD_MIN} characters; the person must change it at first login)", type="password")
            add = st.form_submit_button("Create account", type="primary")
        if add:
            try:
                acc.upsert_user(principal, uid, name, role, password=pwd)
                st.success(f"Account {uid.strip().lower()} created."); st.rerun()
            except ACC.AccessError as e:
                st.error(str(e))
    with c2:
        st.markdown("**Edit an account**")
        ids = [u["id"] for u in users]
        if ids:
            target = st.selectbox("Account", ids, key="edit_target")
            u = acc.get_user(target)
            with st.form("edit_user", border=True):
                name = st.text_input("Name", value=u["name"], max_chars=ACC.NAME_MAX)
                role = st.selectbox("Role", roles, index=roles.index(u["role"]) if u["role"] in roles else 0,
                                    format_func=lambda r: ACC.ROLES[r]["label"])
                active = st.checkbox("Active (unchecked = deactivated: cannot sign in, sessions end)", value=u["active"])
                newpwd = st.text_input("Set a temporary password (leave empty to keep the current one)", type="password")
                save = st.form_submit_button("Save")
            if save:
                try:
                    acc.upsert_user(principal, target, name, role, password=newpwd or None, active=active)
                    st.success("Saved."); st.rerun()
                except ACC.AccessError as e:
                    st.error(str(e))
        else:
            st.caption("Nothing to edit yet.")
    with st.expander("Roles and capabilities"):
        for r, spec in ACC.ROLES.items():
            st.markdown(f"- **{spec['label']}** (`{r}`): " + ", ".join(f"`{c}`" for c in sorted(spec["capabilities"])))
        st.markdown("Capabilities: " + "; ".join(f"`{c}` {d}" for c, d in ACC.CAPABILITIES.items()))
    if principal.can("audit.view"):
        st.subheader("Access log")
        ev = acc.events(200)
        if ev:
            st.dataframe(pd.DataFrame(ev), width="stretch", hide_index=True)
        else:
            st.caption("Empty.")


principal = current_principal()
if principal is None:
    login_screen()
if principal.must_change_password:
    st.title("Choose your own password")
    st.info("An administrator set a temporary password for your account. Choose your own to continue.")
    password_change_form(principal, forced=True)
    if st.button("Sign out"):
        do_logout(principal)
    st.stop()


# ---- process-wide resources: server speed factor and a results store shared by all sessions ----
@st.cache_resource(show_spinner=False)
def server_speed_factor():
    """How much slower this server is than the reference machine on which the estimates were calibrated."""
    c = D.load_preset("paper-v2"); c["episodes"] = 1000
    t0 = time.perf_counter(); S.run_policy("social", c, D.load_competence_map(), 0); dt = time.perf_counter() - t0
    return max(1.0, dt / 0.095)


@st.cache_resource(show_spinner=False)
def results_store():
    return {}


# ---- state ----
def _init(preset="paper-v2"):
    st.session_state.cfg = D.load_preset(preset)
    st.session_state.preset = preset
    st.session_state.version = st.session_state.get("version", 0) + 1
    st.session_state.pop("results", None)


if "cfg" not in st.session_state:
    _init()
cfg = st.session_state.cfg
V = st.session_state.version  # widget keys carry the version so that loading a preset resets them


def k(name):
    return f"{name}_{V}"


# ---- sidebar ----
with st.sidebar:
    st.title("Social LLM-MAS Lab")
    st.caption("Outcome-based trust and social discovery among LLM agents. Replay over measured outcomes; no API key needed.")
    if auth_required():
        st.caption(f"Signed in as **{principal.name}** · {principal.role_label}")
        if st.button("Sign out", key="signout", width="stretch"):
            do_logout(principal)
    names = D.preset_names()
    chosen = st.selectbox("Paper preset", names, index=names.index(st.session_state.preset),
                          format_func=lambda n: D.PRESETS[n]["label"])
    if st.button("Load preset (discards edits)", width="stretch"):
        _init(chosen); st.rerun()
    st.caption(D.PRESETS[st.session_state.preset]["description"])
    mode = st.radio("Mode", ["Replay (measured outcomes)", "Live (real LLM calls)"], index=0)
    if mode.startswith("Live"):
        st.info("Live mode (your own OpenAI key, a spending cap, an isolated grader) is the next release. "
                "Replay mode uses the outcomes measured once for the paper.")
    st.divider()
    st.subheader("Run")
    cfg["seeds"] = st.slider("Seeds", 1, 20, int(cfg["seeds"]), key=k("seeds"),
                             help="Seed i of your run is seed i of the paper: shared seeds reproduce bit for bit.")
    cfg["episodes"] = st.select_slider("Episodes per seed and policy", options=list(range(300, 3001, 100)),
                                       value=int(cfg["episodes"]), key=k("episodes"))
    cfg["policies"] = st.multiselect("Policies", list(S.POLICIES), default=[p for p in cfg["policies"] if p in S.POLICIES],
                                     format_func=lambda p: POLICY_LABEL[p], key=k("policies"))
    cfg["analysis"]["bootstrap_resamples"] = st.select_slider("Bootstrap resamples", options=[1000, 2000, 5000, 10000],
                                                              value=int(cfg["analysis"]["bootstrap_resamples"]), key=k("boot"))
    est = estimate_seconds(cfg) * server_speed_factor()
    st.caption(f"Estimated time on this server: about {est:.0f} s." + (" Tip: 5 seeds give a first look in a fraction of the time; "
               "the paper comparison tab already holds the 20-seed reference." if est > 60 else ""))
    run_clicked = st.button("Run replay", type="primary", width="stretch")


# ---- charts ----
def line_chart(df, title, ytitle, yrange=None, ref_line=None):
    fig = go.Figure()
    for p in [q for q in S.POLICIES if q in set(df["policy"])]:
        d = df[df["policy"] == p]; color, dash, sym = POLICY_STYLE[p]
        n = len(d)
        fig.add_trace(go.Scatter(x=d["episode"], y=d["value"], name=POLICY_LABEL[p], mode="lines+markers",
                                 line=dict(color=color, width=2, dash=dash),
                                 marker=dict(symbol=sym, size=8, color=color, line=dict(color=SURFACE, width=1),
                                             opacity=[1.0 if i % max(1, n // 5) == 0 or i == n - 1 else 0.0 for i in range(n)]),
                                 hovertemplate="%{y:.3f}<extra>" + POLICY_LABEL[p] + "</extra>"))
    if ref_line is not None:
        fig.add_hline(y=ref_line, line=dict(color=GRID, width=1, dash="dash"))
    n = len(fig.data)
    fig.update_layout(title=dict(text=title, x=0, font=dict(size=15)), xaxis_title="episode", yaxis_title=ytitle,
                      hovermode="x unified", height=380 + 24 * (-(-n // 2)), **{**LAYOUT, **legend_below(n)})
    fig.update_yaxes(range=yrange, gridcolor=GRID, showgrid=True); fig.update_xaxes(showgrid=False)
    return fig


def forest_chart(df, title, min_effect=2.0):
    if df.empty:
        return None
    fig = go.Figure()
    ys = list(range(len(df)))[::-1]
    fig.add_trace(go.Scatter(x=df["points"], y=ys, mode="markers+text", text=[f"{v:+.1f}" for v in df["points"]],
                             textposition="top center", textfont=dict(color=INK2, size=11),
                             marker=dict(color="#2a78d6", size=9, line=dict(color="white", width=1)),
                             error_x=dict(type="data", symmetric=False, array=df["ci_high"] - df["points"],
                                          arrayminus=df["points"] - df["ci_low"], color="#2a78d6", thickness=2, width=0),
                             customdata=df[["comparison", "ci_low", "ci_high", "seeds_positive"]].values,
                             hovertemplate="%{customdata[0]}: %{x:+.2f} points (95%% CI %{customdata[1]:+.2f}, %{customdata[2]:+.2f}); "
                                           "seeds positive %{customdata[3]}<extra></extra>", showlegend=False))
    fig.add_vline(x=0, line=dict(color=INK2, width=1))
    fig.add_vline(x=min_effect, line=dict(color=GRID, width=1, dash="dash"), annotation_text=f"{min_effect:g} points",
                  annotation_position="top", annotation_font=dict(color=INK2, size=11))
    fig.update_layout(title=dict(text=title, x=0, font=dict(size=15)), xaxis_title="paired difference in success, percentage points (95% bootstrap CI over seeds)",
                      yaxis=dict(tickmode="array", tickvals=ys, ticktext=list(df["comparison"])), height=150 + 44 * len(df), **LAYOUT)
    fig.update_xaxes(gridcolor=GRID, showgrid=True, zeroline=False)
    return fig


def selection_chart(df, title):
    fig = go.Figure()
    pols = [q for q in S.POLICIES if q in set(df["policy"])]
    for prof in [p for p in PROFILE_ORDER if p in set(df["profile"])]:
        d = df[df["profile"] == prof].set_index("policy").reindex(pols)
        fig.add_trace(go.Bar(y=[POLICY_LABEL[p] for p in pols], x=d["share"], name=prof, orientation="h",
                             marker=dict(color=PROFILE_COLOR[prof], line=dict(color=SURFACE, width=2)),
                             text=[f"{v:.0%}" if v >= 0.08 else "" for v in d["share"]], textposition="inside",
                             insidetextfont=dict(color="white", size=11),
                             hovertemplate=prof + ": %{x:.1%}<extra></extra>"))
    n = len(fig.data)
    fig.update_layout(barmode="stack", title=dict(text=title, x=0, font=dict(size=15)), xaxis=dict(tickformat=".0%", range=[0, 1]),
                      height=140 + 40 * len(pols) + 24 * (-(-n // 2)), **{**LAYOUT, **legend_below(n)})
    fig.update_yaxes(autorange="reversed", categoryorder="array", categoryarray=[POLICY_LABEL[p] for p in pols])
    return fig


def map_chart(cmap):
    fig = go.Figure()
    models = list(cmap["models"])
    for i, m in enumerate(models):
        vals = [cmap["models"][m]["per_domain_drawn"][d]["pass"] for d in S.DOMAINS]
        fig.add_trace(go.Bar(x=S.DOMAINS, y=vals, name=m, marker=dict(color=MODEL_COLOR[i % 3], line=dict(color=SURFACE, width=2)),
                             text=vals, textposition="outside", textfont=dict(color=INK2, size=11), hovertemplate="%{y} of 50<extra>" + m + "</extra>"))
    fig.update_layout(barmode="group", title=dict(text="Competence map: tasks solved per domain (50 drawn per domain)", x=0, font=dict(size=15)),
                      yaxis_title="tasks solved", yaxis=dict(range=[0, 34]), height=420, **{**LAYOUT, **legend_below(len(models))})
    fig.update_yaxes(gridcolor=GRID, showgrid=True); fig.update_xaxes(showgrid=False)
    return fig


def fmt_headline(df):
    view = df.rename(columns={"success": "success", "success_min": "min", "success_max": "max", "cold_start_success": "cold start",
                              "cost_usd_per_1000_episodes": "USD / 1,000 ep.", "cost_per_success_usd": "USD / success",
                              "messages_per_episode": "messages / ep.", "final_degree_mean": "final degree",
                              "unreliable_share_first_window": "unreliable, first window", "unreliable_share_last_like_window": "unreliable, last like window"})
    view["policy"] = view["policy"].map(POLICY_LABEL)
    return view.style.format({"success": "{:.3f}", "min": "{:.3f}", "max": "{:.3f}", "cold start": "{:.3f}", "USD / 1,000 ep.": "{:.3f}",
                              "USD / success": "{:.5f}", "messages / ep.": "{:.1f}", "final degree": "{:.1f}",
                              "unreliable, first window": "{:.3f}", "unreliable, last like window": "{:.3f}"}, na_rep="n/a")


# ---- population editor ----
def agents_frame(agents):
    rows = []
    for a in agents:
        rows.append({"id": a["id"], "base": a["base"], "profile": a["profile"], "lazy_p": a.get("lazy_p"),
                     "phase_length": a.get("phase_length"), "domains": ", ".join(a.get("domains", []))})
    return pd.DataFrame(rows, columns=["id", "base", "profile", "lazy_p", "phase_length", "domains"])


def frame_agents(df):
    agents = []
    for _, r in df.iterrows():
        if not isinstance(r["id"], str) or not r["id"].strip():
            continue
        a = {"id": r["id"].strip(), "base": r["base"], "profile": r["profile"]}
        if r["profile"] in ("lazy", "unstable"):
            a["lazy_p"] = float(r["lazy_p"]) if pd.notna(r["lazy_p"]) else 0.5
        if r["profile"] == "unstable":
            a["phase_length"] = int(r["phase_length"]) if pd.notna(r["phase_length"]) else 300
        if r["profile"] == "specialist":
            a["domains"] = [d.strip() for d in str(r["domains"] or "").split(",") if d.strip()]
        agents.append(a)
    return agents


tab_names = ["Population and rules", "Results", "Paper comparison", "Data and method", "Account"]
if principal.can("users.manage"):
    tab_names.append("Administration")
tabs = st.tabs(tab_names)
tab_pop, tab_res, tab_paper, tab_data, tab_account = tabs[:5]
tab_admin = tabs[5] if principal.can("users.manage") else None

with tab_pop:
    st.subheader("Population")
    st.caption("Edit, add or delete agents. Bases: `nano` = gpt-4.1-nano, `mini` = gpt-4.1-mini, as measured in the competence map. "
               "`lazy_p` applies to lazy and unstable, `phase_length` to unstable, `domains` (comma-separated) to specialists.")
    bases = list(cfg["base_models"])
    edited = st.data_editor(agents_frame(cfg["agents"]), num_rows="dynamic", width="stretch", hide_index=True, key=k("agents"),
                            column_config={"id": st.column_config.TextColumn("id", required=True, width="small"),
                                           "base": st.column_config.SelectboxColumn("base", options=bases, required=True, width="small"),
                                           "profile": st.column_config.SelectboxColumn("profile", options=list(S.PROFILES), required=True),
                                           "lazy_p": st.column_config.NumberColumn("lazy_p", min_value=0.0, max_value=1.0, step=0.05, format="%.2f"),
                                           "phase_length": st.column_config.NumberColumn("phase_length", min_value=1, step=50),
                                           "domains": st.column_config.TextColumn("domains", help=", ".join(S.DOMAINS))})
    cfg["agents"] = frame_agents(edited)
    with st.expander("Profile glossary"):
        for p, h in PROFILE_HELP.items():
            st.markdown(f"- **{p}**: {h}")

    st.subheader("Rules")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("**Declarations and tasks**")
        cfg["declaration_threshold"] = st.slider("Declaration threshold (map pass rate)", 0.0, 1.0, float(cfg["declaration_threshold"]), 0.05, key=k("thr"))
        cfg["task_pool"]["rule"] = st.radio("Task pool", ["all", "discriminating"], index=["all", "discriminating"].index(cfg["task_pool"]["rule"]), key=k("pool"),
                                            help="all: the 350 tasks; discriminating: the 174 passed by at least one base model")
        st.markdown("**Graph and discovery**")
        cfg["graph"]["degree"] = st.number_input("Initial degree (random connected graph)", 1, max(1, len(cfg["agents"]) - 1), int(cfg["graph"]["degree"]), key=k("deg"))
        cfg["social"]["radius"] = st.radio("Discovery radius", [1, 2], index=[1, 2].index(int(cfg["social"]["radius"])), horizontal=True, key=k("radius"),
                                           help="1: direct contacts only; 2: contacts of contacts too")
        cfg["social"]["befriend_on_success"] = st.checkbox("New relationship after a success", bool(cfg["social"]["befriend_on_success"]), key=k("befriend"))
    with c2:
        st.markdown("**Selection**")
        cfg["social"]["epsilon"] = st.slider("Exploration ε", 0.0, 0.5, float(cfg["social"]["epsilon"]), 0.01, key=k("eps"))
        cfg["social"]["max_reselections"] = st.number_input("Max reselections after refusals", 0, 10, int(cfg["social"]["max_reselections"]), key=k("resel"))
        cfg["social"]["declared_prior"] = st.slider("Prior score, declared domain", 0.0, 1.0, float(cfg["social"]["declared_prior"]), 0.05, key=k("dp"))
        cfg["social"]["undeclared_prior"] = st.slider("Prior score, undeclared domain", 0.0, 1.0, float(cfg["social"]["undeclared_prior"]), 0.05, key=k("up"))
        cfg["social"]["referral_weight_default"] = st.slider("Referral weight for unknown referrers", 0.0, 1.0, float(cfg["social"]["referral_weight_default"]), 0.05, key=k("rw"))
    with c3:
        st.markdown("**Trust (Beta reputation)**")
        cfg["social"]["prior_alpha"] = st.number_input("Prior α", 0.1, 20.0, float(cfg["social"]["prior_alpha"]), 0.5, key=k("pa"))
        cfg["social"]["prior_beta"] = st.number_input("Prior β", 0.1, 20.0, float(cfg["social"]["prior_beta"]), 0.5, key=k("pb"))
        cfg["social"]["domain_min_obs"] = st.number_input("Min observations for domain-specific evidence", 1, 20, int(cfg["social"]["domain_min_obs"]), key=k("mo"))
        st.markdown("**Analysis**")
        cfg["analysis"]["cold_start_episodes"] = st.number_input("Cold-start episodes", 100, 3000, int(cfg["analysis"]["cold_start_episodes"]), 100, key=k("cold"))
        ids = [a["id"] for a in cfg["agents"]]
        cfg["best_fixed_agents"] = st.multiselect("best_fixed agents (first available is used)", ids,
                                                  default=[a for a in cfg.get("best_fixed_agents", []) if a in ids], key=k("bf"))
    with st.expander("Policy glossary"):
        for p, h in POLICY_HELP.items():
            st.markdown(f"- **{POLICY_LABEL[p]}** (`{p}`): {h}")

    problems = validate_config(cfg, D.load_competence_map())
    if problems:
        st.error("Fix before running:\n\n- " + "\n- ".join(problems))
    else:
        st.success("Configuration valid.")
    with st.expander("Configuration as JSON (download, or upload one to replace it)"):
        st.download_button("Download configuration", json.dumps(cfg, indent=2), file_name="population.json", mime="application/json")
        up = st.file_uploader("Upload a configuration JSON", type="json", key=k("upload"))
        if up is not None:
            try:
                new = json.load(up)
                if "agents" in new and "social" in new:
                    st.session_state.cfg = new; st.session_state.version += 1; st.session_state.pop("results", None); st.rerun()
                else:
                    st.error("Not a population configuration (missing `agents` or `social`).")
            except json.JSONDecodeError as e:
                st.error(f"Invalid JSON: {e}")
        st.code(json.dumps(cfg, indent=2), language="json")

# ---- run ----
if run_clicked:
    problems = validate_config(cfg, D.load_competence_map())
    if problems:
        st.error("Configuration problems:\n\n- " + "\n- ".join(problems))
    else:
        key = config_hash(cfg); store = results_store()
        if key in store:
            st.session_state.results = store[key]
            st.sidebar.success("Same configuration already run on this server: results served from memory.")
        else:
            bar = st.sidebar.progress(0.0, text="starting")
            t0 = time.perf_counter()

            def progress(done, total, policy, seed):
                el = time.perf_counter() - t0; eta = el / done * (total - done)
                bar.progress(done / total, text=f"{done}/{total}: {POLICY_LABEL[policy]}, seed {seed}; {el:.0f} s elapsed, about {eta:.0f} s left")
            results = run_experiment(cfg, D.load_competence_map(), progress=progress)
            results["elapsed_seconds"] = round(time.perf_counter() - t0, 2)
            if len(store) >= 64:
                store.pop(next(iter(store)))
            store[key] = results
            st.session_state.results = results
            bar.progress(1.0, text=f"done in {results['elapsed_seconds']:.1f} s")

results = st.session_state.get("results")

with tab_res:
    if not results:
        st.info("No run yet. Choose a preset or edit the population, then press **Run replay** in the sidebar. "
                "The pre-registered results of every preset are in the **Paper comparison** tab without running anything.")
    else:
        r = results
        st.caption(f"Run of {r['config']['seeds']} seeds × {r['config']['episodes']} episodes × {len(r['policies'])} policies, "
                   f"{len(r['config']['agents'])} agents, pool {r['ground_truth']['pool_size']} tasks; configuration {r['config_sha256'][:12]}; "
                   f"{r.get('elapsed_seconds', 0):.1f} s.")
        hf = headline_frame(r)
        st.markdown("**Headline** (means over seeds; unreliable = lazy, impostor, unstable in a lazy phase)")
        st.dataframe(fmt_headline(hf), width="stretch", hide_index=True)
        df = differences_frame(r)
        if not df.empty:
            st.plotly_chart(forest_chart(df, "Paired differences by seed", float(r["config"]["analysis"].get("min_effect_points", 2.0))), width="stretch")
            with st.expander("Paired differences, table"):
                st.dataframe(df, width="stretch", hide_index=True)
        c1, c2 = st.columns(2)
        with c1:
            st.plotly_chart(line_chart(windows_frame(r, "success_by_window"), "Success over time (100-episode windows)", "success rate"), width="stretch")
        with c2:
            st.plotly_chart(line_chart(windows_frame(r, "unreliable_share_by_window"), "Unreliable selections over time", "share of selections", yrange=[0, None]), width="stretch")
        c1, c2 = st.columns(2)
        with c1:
            st.plotly_chart(line_chart(windows_frame(r, "messages_by_window"), "Messages per episode over time", "messages"), width="stretch")
        with c2:
            st.plotly_chart(selection_chart(selection_frame(r), "Who gets selected, by profile"), width="stretch")
        st.markdown("**Decline of unreliable selections** (first window against the last window in the same unstable phase)")
        st.dataframe(decline_frame(r).style.format({"first_window": "{:.3f}", "last_like_window": "{:.3f}", "decline_points": "{:+.2f}", "ci_low": "{:+.2f}", "ci_high": "{:+.2f}"}),
                     width="stretch", hide_index=True)
        with st.expander("Trust calibration and referral weights (evaluation only: compares learned trust with ground truth after the run)"):
            for p, v in r["policies"].items():
                c = v.get("calibration")
                if c:
                    st.markdown(f"- **{POLICY_LABEL[p]}**: mean absolute error {c['mean_abs_error']}; mean trust by profile " +
                                ", ".join(f"{a} {b:.3f}" for a, b in c["mean_trust_by_profile"].items()) +
                                (f"; referral weight honest {v['referral_weight_by_referrer'].get('honest_referrer')} vs liar {v['referral_weight_by_referrer'].get('liar')}"
                                 if v.get("referral_weight_by_referrer") else ""))
            if r.get("referral_weight_gap_honest_minus_liar"):
                g = r["referral_weight_gap_honest_minus_liar"]
                st.markdown(f"- Referral weight gap honest minus liar: {g['mean_points'] / 100:+.3f} (95% CI {g['ci95'][0] / 100:+.3f}, {g['ci95'][1] / 100:+.3f})")
        with st.expander("Ground truth of this population (never visible to the policies)"):
            gt = r["ground_truth"]
            tdf = pd.DataFrame(gt["true_rate_by_domain"]).T
            tdf.insert(0, "overall", pd.Series(gt["true_overall_rate"]))
            tdf.insert(1, "declares", pd.Series({a: ", ".join(d) for a, d in gt["declarations"].items()}))
            st.dataframe(tdf.style.format({c: "{:.2f}" for c in tdf.columns if c != "declares"}), width="stretch")
            st.caption(f"Pool rule {gt['pool_rule']}: {gt['pool_size']} tasks sampled, {gt['hard_size']} failed by both base models; initial mean degree {gt.get('initial_degree_mean')}.")
        st.markdown("**Download**")
        d1, d2, d3 = st.columns(3)
        d1.download_button("Results JSON (paper format)", json.dumps(r, indent=2), file_name="results.json", mime="application/json")
        d2.download_button("Headline CSV", hf.to_csv(index=False), file_name="headline.csv", mime="text/csv")
        d3.download_button("Markdown report", markdown_report(r), file_name="report.md", mime="text/markdown")

with tab_paper:
    st.subheader("Pre-registered results of the paper")
    ref_name = st.selectbox("Reference run", D.preset_names(), index=D.preset_names().index(st.session_state.preset),
                            format_func=lambda n: D.PRESETS[n]["label"], key="ref_choice")
    ref = D.load_reference(ref_name)
    st.caption(D.PRESETS[ref_name]["description"] + f" Generated {ref['generated_utc'][:10]}; competence map sha256 {ref['competence_map_sha256'][:12]}.")
    st.dataframe(fmt_headline(headline_frame(ref)), width="stretch", hide_index=True)
    st.plotly_chart(forest_chart(differences_frame(ref), "Paired differences, paper run"), width="stretch")
    c1, c2 = st.columns(2)
    with c1:
        st.plotly_chart(line_chart(windows_frame(ref, "success_by_window"), "Success over time, paper run", "success rate"), width="stretch")
    with c2:
        st.plotly_chart(line_chart(windows_frame(ref, "unreliable_share_by_window"), "Unreliable selections, paper run", "share of selections", yrange=[0, None]), width="stretch")
    if ref_name.startswith("paper-v3"):
        cmpv3 = D.load_reference_file("social-v3-compare.json")
        st.markdown("**Liars against the twin without liars** (paired by seed)")
        rows = [("damage to social: no liars − liars", cmpv3["damage_social_noliars_minus_liars"]),
                ("damage to social_refcheck: no liars − liars", cmpv3["refcheck_noliars_minus_liars"]),
                ("defence with liars: refcheck − social", cmpv3["defence_refcheck_minus_social_with_liars"]),
                ("defence cost without liars: refcheck − social", cmpv3["defence_cost_refcheck_minus_social_without_liars"])]
        st.dataframe(pd.DataFrame([{"comparison": n, "points": v["mean_points"], "ci_low": v["ci95"][0], "ci_high": v["ci95"][1],
                                    "seeds_positive": f"{v['seeds_positive']}/{v['n']}"} for n, v in rows]), width="stretch", hide_index=True)
        rw = cmpv3["referral_weight_by_referrer"]
        st.caption(f"Referral weight learned by `social_refcheck`: honest referrers {rw['honest_referrer']}, liars {rw['liar']}.")
    if results:
        st.subheader("Your run against this reference")
        cmp = compare_to_reference(results, ref)
        same_cfg = rules_signature(results["config"]) == rules_signature(ref["config"])
        cdf = pd.DataFrame([{"policy": POLICY_LABEL[p], "your run": v["run_mean"], "paper": v["reference_mean"], "delta (points)": v["delta_points"],
                             "shared seeds": v["shared_seeds"], "identical on shared seeds": v["exact_on_shared_seeds"]} for p, v in cmp.items()])
        st.dataframe(cdf.style.format({"your run": "{:.3f}", "paper": "{:.3f}", "delta (points)": "{:+.2f}"}), width="stretch", hide_index=True)
        if same_cfg and results["config"]["episodes"] == ref["config"]["episodes"]:
            st.success("Same population and rules as the paper: shared seeds are identical, as the simulator is deterministic." if all(v["exact_on_shared_seeds"] for v in cmp.values())
                       else "Same configuration but different per-seed numbers: please report this as a bug.")
        else:
            st.info("Your configuration differs from the paper's (population, rules or episodes), so the deltas measure your change, not noise.")

with tab_data:
    cmap = D.load_competence_map()
    st.subheader("What the replay uses")
    st.markdown(
        "Every worker in the simulation is backed by a **measured** outcome table: three OpenAI models answered the same 350 "
        "BigCodeBench-Instruct tasks (50 drawn per domain, seven domains), graded by the official evaluator in an isolated container, "
        "at temperature 0. An agent's answer in a domain is replayed with replacement from its base model's row for that domain. "
        "Policies never read this table: they see declarations, their own trust records, referral opinions and episode outcomes. "
        "Only the two reference lines (`best_fixed`, `oracle`) assume ground truth.")
    st.plotly_chart(map_chart(cmap), width="stretch")
    mrows = [{"model": m, "tasks": v["tasks"], "passed": v["passed"], "pass rate": v["pass_rate"], "upper cost USD (350 tasks)": float(v["upper_cost_usd"])}
             for m, v in cmap["models"].items()]
    st.dataframe(pd.DataFrame(mrows).style.format({"pass rate": "{:.3f}", "upper cost USD (350 tasks)": "{:.4f}"}), width="stretch", hide_index=True)
    comp = cmap["complementarity"]
    st.caption(f"Tasks solved by k of the three models: {comp['solved_by_k_models']}. Map generated {cmap['generated_utc'][:10]}; "
               f"manifest sha256 {cmap['manifest_sha256'][:12]}.")
    st.subheader("Provenance and licence")
    st.markdown(
        "- Code: Apache-2.0. Data files: task identifiers, domains, library names and per-model outcomes only; no prompts, tests or "
        "solutions of BigCodeBench are redistributed (the dataset itself is Apache-2.0).\n"
        "- Reference results are the pre-registered runs of the paper, byte for byte; every preset reproduces them from the bundled map "
        "because the simulator is deterministic given the seed.\n"
        "- The live pool of 121 unseen tasks used for the paper's live validation is bundled for the coming live mode.\n"
        "- Source and issues: https://github.com/MarcoBecattini/social-llm-mas-lab")


with tab_account:
    st.subheader("Your account")
    st.markdown(f"**{principal.name}** (`{principal.id}`), role **{principal.role_label}**. You can: " +
                ", ".join(f"`{c}`" for c in sorted(principal.capabilities)) + ".")
    if auth_required() and not principal.legacy:
        st.markdown("**Change password**")
        password_change_form(principal)
    elif principal.legacy:
        st.info("The bootstrap credential has no account: create yours in the Administration tab.")

if tab_admin is not None:
    with tab_admin:
        admin_panel(principal)
