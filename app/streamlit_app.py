"""Social LLM-MAS Lab: experiments on outcome-based trust in a society of LLM agents, replayed or run live."""
import copy
import io
import json
import os
import time

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components

from socialmas import access as ACC
from socialmas import bcb_data as B
from socialmas import data as D
from socialmas import experiments as X
from socialmas import live as L
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
        udf = pd.DataFrame(users)[["id", "name", "role_label", "active", "must_change_password", "shared_allowance_usd", "created_at", "updated_at"]]
        udf["spent on shared key"] = [acc.spent(u["id"]) for u in users]
        udf = udf.rename(columns={"role_label": "role", "must_change_password": "temporary password", "shared_allowance_usd": "shared key allowance USD"})
        st.dataframe(udf.style.format({"shared key allowance USD": "{:.2f}", "spent on shared key": "{:.4f}"}), width="stretch", hide_index=True)
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
                allowance = st.number_input("Allowance on the shared OpenAI key, USD (0 = cannot use it)", min_value=0.0, max_value=1000.0,
                                            value=float(u.get("shared_allowance_usd", 0.0)), step=0.05, format="%.2f")
                save = st.form_submit_button("Save")
            if save:
                try:
                    acc.upsert_user(principal, target, name, role, password=newpwd or None, active=active)
                    if abs(allowance - float(u.get("shared_allowance_usd", 0.0))) > 1e-9:
                        acc.set_allowance(principal, target, allowance)
                    st.success("Saved."); st.rerun()
                except ACC.AccessError as e:
                    st.error(str(e))
        else:
            st.caption("Nothing to edit yet.")
    with st.expander("Roles and capabilities"):
        for r, spec in ACC.ROLES.items():
            st.markdown(f"- **{spec['label']}** (`{r}`): " + ", ".join(f"`{c}`" for c in sorted(spec["capabilities"])))
        st.markdown("Capabilities: " + "; ".join(f"`{c}` {d}" for c, d in ACC.CAPABILITIES.items()))
    if principal.can("settings.manage") and not principal.legacy:
        st.subheader("Shared OpenAI key")
        st.caption("One key for the whole laboratory, pasted here by an administrator and stored encrypted on the data disk. It is never shown again "
                   "and never logged. People use it in the Live tab only within the allowance you give them above; every run is charged to their account.")
        status = acc.shared_key_status()
        k1, k2 = st.columns(2)
        with k1:
            if status:
                st.success(f"Key set by {status['set_by']} on {status['set_at'][:16].replace('T', ' ')} UTC (ends with …{status['last4']}).")
            else:
                st.info("No shared key configured.")
            with st.form("shared_key", clear_on_submit=True, border=True):
                newkey = st.text_input("Paste the OpenAI API key" + (" to replace the current one" if status else ""), type="password", autocomplete="off")
                setk = st.form_submit_button("Save key", type="primary")
            if setk:
                try:
                    acc.set_shared_key(principal, newkey); st.success("Shared key saved."); st.rerun()
                except ACC.AccessError as e:
                    st.error(str(e))
            if status and st.button("Remove the shared key"):
                acc.clear_shared_key(principal); st.rerun()
        with k2:
            gcap = st.number_input("Global cap on shared-key spending, USD (all users together, upper cost)", min_value=0.0, max_value=10000.0,
                                   value=float(acc.shared_key_global_cap()), step=0.5, format="%.2f", key="global_cap")
            if st.button("Save global cap"):
                try:
                    acc.set_shared_key_global_cap(principal, gcap); st.success("Saved."); st.rerun()
                except ACC.AccessError as e:
                    st.error(str(e))
            st.caption(f"Spent so far on the shared key: {acc.spent():.4f} USD of {acc.shared_key_global_cap():.2f}.")
            sp = acc.spend_summary()
            if sp:
                st.dataframe(pd.DataFrame(sp).rename(columns={"usd": "upper cost USD"}).style.format({"upper cost USD": "{:.4f}"}), width="stretch", hide_index=True)
    if principal.can("audit.view"):
        st.subheader("Access log")
        ev = acc.events(200)
        if ev:
            st.dataframe(pd.DataFrame(ev), width="stretch", hide_index=True)
        else:
            st.caption("Empty.")



@st.cache_resource(show_spinner=False)
def experiments():
    ex = X.Experiments(access())
    try:
        ex.import_legacy_live_runs()
    except Exception:
        pass
    return ex


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
EX = experiments()

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


# ---- live mode: real LLM calls with the user's own key, graded by the grader service, under a session cap ----
GRADER_URL = os.environ.get("GRADER_URL", "http://social-llm-mas-grader:10000")
GRADER_TOKEN = os.environ.get("GRADER_TOKEN", "")
LIVE_MAX_CAP = float(os.environ.get("SOCIALMAS_LIVE_MAX_CAP", "5"))


@st.cache_data(ttl=30, show_spinner=False)
def grader_health(url):
    import requests
    try:
        r = requests.get(url.rstrip("/") + "/healthz", timeout=5, headers={"X-Grader-Token": GRADER_TOKEN} if GRADER_TOKEN else {})
        return r.json() if r.status_code == 200 else {"ok": False, "error": f"http {r.status_code}"}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"[:200]}


@st.cache_resource(show_spinner=False)
def pricing():
    return json.loads((D.DATA_DIR / "pricing.json").read_text())


def dataset_status():
    path = B.dataset_path(access().data_dir)
    return path if path.exists() else None


def render_replay_results(r):
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



# ---- experiment state: the open experiment, its unsaved draft, the selected runs ----
ss = st.session_state
ss.setdefault("exp_id", None); ss.setdefault("drafts", {}); ss.setdefault("draft_version", {}); ss.setdefault("selected_run", {})


def open_experiment(exp_id):
    exp = EX.get(exp_id)
    if exp is None:
        st.error("Experiment not found."); return
    ss.exp_id = exp_id; ss.drafts[exp_id] = copy.deepcopy(exp["config"])
    ss.draft_version[exp_id] = ss.draft_version.get(exp_id, 0) + 1
    ss.selected_run.pop(exp_id, None)


def current_experiment():
    if ss.exp_id:
        exp = EX.get(ss.exp_id)
        if exp is not None:
            return exp
        ss.exp_id = None
    return None


def draft_of(exp):
    return ss.drafts.setdefault(exp["id"], copy.deepcopy(exp["config"]))


def k(name, exp):
    return f"{name}_{exp['id']}_{ss.draft_version.get(exp['id'], 0)}"


def unsaved(exp):
    return X.normalized_json(draft_of(exp)) != X.normalized_json(exp["config"])


def select_run(exp, kind, run_id):
    ss.selected_run.setdefault(exp["id"], {})[kind] = run_id


def selected_run(exp, kind):
    runs = EX.runs(exp["id"], kind=kind)
    if not runs:
        return None
    wanted = ss.selected_run.get(exp["id"], {}).get(kind)
    return next((r for r in runs if r["id"] == wanted), runs[0])


def selected_replay_results():
    exp = current_experiment()
    if exp is None:
        return None
    run = selected_run(exp, "replay")
    if run is None:
        return None
    try:
        return EX.load_run(run["id"])
    except Exception:
        return None


def paper_default_index():
    exp = current_experiment(); names = D.preset_names()
    return names.index(exp["origin_preset"]) if exp and exp.get("origin_preset") in names else 0


def exp_label(e):
    return f"{e['name']}  ·  {e['owner']}" + (f"  ·  from {e['origin_preset']}" if e.get("origin_preset") else "") + ("  ·  archived" if e.get("archived") else "")


# ---- sidebar ----
with st.sidebar:
    st.title("Social LLM-MAS Lab")
    st.caption("Outcome-based trust and social discovery among LLM agents. Replay over measured outcomes, or live with real calls.")
    if auth_required():
        st.caption(f"Signed in as **{principal.name}** · {principal.role_label}")
        if st.button("Sign out", key="signout", width="stretch"):
            do_logout(principal)
    st.divider()
    sidebar_status = st.empty()          # filled at the end of the script, when the draft reflects this run's edits


tab_names = ["Experiments", "Configure", "Replay"]
if principal.can("live.run"):
    tab_names.append("Live")
tab_names += ["History", "Paper comparison", "Data and method", "Account"]
if principal.can("users.manage"):
    tab_names.append("Administration")
TABS = dict(zip(tab_names, st.tabs(tab_names)))


# ---- Experiments: list, open, create, duplicate, rename, archive ----
with TABS["Experiments"]:
    st.subheader("Experiments of the laboratory")
    st.caption("An experiment is a named configuration (population, graph, trust rules, run settings) with its history of replay and live runs. "
               "Everyone signed in sees them; the owner and administrators change them; anyone can duplicate one to work on a copy.")
    show_archived = st.checkbox("Show archived", value=False, key="show_archived")
    exps = EX.list(include_archived=show_archived)
    if exps:
        rows = [{"name": e["name"], "owner": e["owner"], "origin": e.get("origin_preset") or "", "version": e["config_version"],
                 "agents": len(e["config"]["agents"]), "runs": len(EX.runs(e["id"])), "updated": e["updated_at"][:16].replace("T", " "),
                 "archived": e["archived"]} for e in exps]
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
        c1, c2 = st.columns([3, 1])
        pick = c1.selectbox("Experiment", exps, format_func=exp_label, key="pick_experiment",
                            index=next((i for i, e in enumerate(exps) if e["id"] == ss.exp_id), 0))
        if c2.button("Open", type="primary", width="stretch"):
            open_experiment(pick["id"]); st.rerun()
        a1, a2, a3 = st.columns(3)
        with a1:
            newname = st.text_input("Duplicate as", value=f"{pick['name']} (copy)", key=f"dup_{pick['id']}")
            if st.button("Duplicate"):
                try:
                    e = EX.duplicate(principal, pick["id"], newname); open_experiment(e["id"]); st.success(f"Created {e['name']}."); st.rerun()
                except X.ExperimentError as err:
                    st.error(str(err))
        if EX.can_edit(principal, pick):
            with a2:
                rn = st.text_input("Rename to", value=pick["name"], key=f"ren_{pick['id']}")
                if st.button("Rename"):
                    try:
                        EX.rename(principal, pick["id"], rn); st.rerun()
                    except X.ExperimentError as err:
                        st.error(str(err))
            with a3:
                st.write("")
                if pick["archived"]:
                    if st.button("Restore"):
                        EX.archive(principal, pick["id"], archived=False); st.rerun()
                elif st.button("Archive"):
                    EX.archive(principal, pick["id"], archived=True)
                    if ss.exp_id == pick["id"]:
                        ss.exp_id = None
                    st.rerun()
    else:
        st.caption("No experiments yet.")
    st.subheader("New experiment from a paper preset")
    st.caption("The six presets reproduce the paper's pre-registered runs and are read-only: a new experiment starts as an exact copy, and the "
               "Configure tab always shows how it differs from its origin.")
    n1, n2 = st.columns([2, 3])
    preset = n1.selectbox("Preset", D.preset_names(), format_func=lambda n: D.PRESETS[n]["label"], key="new_preset")
    name = n2.text_input("Name", value=f"{preset} (my copy)", key=f"new_name_{preset}")
    st.caption(D.PRESETS[preset]["description"])
    if st.button("Create experiment", type="primary"):
        try:
            e = EX.from_preset(principal, preset, name=name); open_experiment(e["id"]); st.success(f"Created {e['name']}: it is now open."); st.rerun()
        except X.ExperimentError as err:
            st.error(str(err))


def need_experiment():
    exp = current_experiment()
    if exp is None:
        st.info("Open or create an experiment in the **Experiments** tab first.")
    return exp


# ---- Configure: population, rules and run settings of the open experiment ----
with TABS["Configure"]:
    exp = need_experiment()
    if exp:
        cfg = draft_of(exp); editable = EX.can_edit(principal, exp)
        st.subheader(exp["name"])
        st.caption(f"Owner {exp['owner']} · configuration version {exp['config_version']} · updated {exp['updated_at'][:16].replace('T', ' ')} UTC"
                   + (f" · derived from **{exp['origin_preset']}**" if exp.get("origin_preset") else ""))
        if not editable:
            st.info("You can look and duplicate, but only the owner or an administrator can change this experiment.")
        diffs = EX.diff_from_origin(exp)
        if diffs is not None:
            if diffs:
                st.markdown("**Differences from the origin preset (saved configuration)**")
                st.dataframe(pd.DataFrame([{"parameter": a, "preset": str(b), "this experiment": str(c)} for a, b, c in diffs]), width="stretch", hide_index=True)
            else:
                st.caption("Saved configuration identical to the origin preset.")
        notes = st.text_area("Notes", value=exp["notes"], key=k("notes", exp), disabled=not editable, height=80)
        if editable and notes != exp["notes"] and st.button("Save notes"):
            EX.set_notes(principal, exp["id"], notes); st.rerun()

        st.markdown("**Population**")
        st.caption("Bases: `nano` = gpt-4.1-nano, `mini` = gpt-4.1-mini, as measured in the competence map. `lazy_p` applies to lazy and unstable, "
                   "`phase_length` to unstable, `domains` (comma-separated) to specialists.")
        bases = list(cfg["base_models"])
        edited = st.data_editor(agents_frame(cfg["agents"]), num_rows="dynamic" if editable else "fixed", width="stretch", hide_index=True, key=k("agents", exp),
                                disabled=not editable,
                                column_config={"id": st.column_config.TextColumn("id", required=True, width="small"),
                                               "base": st.column_config.SelectboxColumn("base", options=bases, required=True, width="small"),
                                               "profile": st.column_config.SelectboxColumn("profile", options=list(S.PROFILES), required=True),
                                               "lazy_p": st.column_config.NumberColumn("lazy_p", min_value=0.0, max_value=1.0, step=0.05, format="%.2f"),
                                               "phase_length": st.column_config.NumberColumn("phase_length", min_value=1, step=50),
                                               "domains": st.column_config.TextColumn("domains", help=", ".join(S.DOMAINS))})
        if editable:
            cfg["agents"] = frame_agents(edited)
        with st.expander("Profile glossary"):
            for p_, h in PROFILE_HELP.items():
                st.markdown(f"- **{p_}**: {h}")

        st.markdown("**Rules**")
        c1, c2, c3 = st.columns(3)
        dis = not editable
        with c1:
            st.markdown("Declarations and tasks")
            cfg["declaration_threshold"] = st.slider("Declaration threshold (map pass rate)", 0.0, 1.0, float(cfg["declaration_threshold"]), 0.05, key=k("thr", exp), disabled=dis)
            cfg["task_pool"]["rule"] = st.radio("Task pool", ["all", "discriminating"], index=["all", "discriminating"].index(cfg["task_pool"]["rule"]), key=k("pool", exp), disabled=dis,
                                                help="all: the 350 tasks; discriminating: the 174 passed by at least one base model")
            st.markdown("Graph and discovery")
            cfg["graph"]["degree"] = st.number_input("Initial degree (random connected graph)", 1, max(1, len(cfg["agents"]) - 1), int(min(cfg["graph"]["degree"], max(1, len(cfg["agents"]) - 1))), key=k("deg", exp), disabled=dis)
            cfg["social"]["radius"] = st.radio("Discovery radius", [1, 2], index=[1, 2].index(int(cfg["social"]["radius"])), horizontal=True, key=k("radius", exp), disabled=dis,
                                               help="1: direct contacts only; 2: contacts of contacts too")
            cfg["social"]["befriend_on_success"] = st.checkbox("New relationship after a success", bool(cfg["social"]["befriend_on_success"]), key=k("befriend", exp), disabled=dis)
        with c2:
            st.markdown("Selection")
            cfg["social"]["epsilon"] = st.slider("Exploration ε", 0.0, 0.5, float(cfg["social"]["epsilon"]), 0.01, key=k("eps", exp), disabled=dis)
            cfg["social"]["max_reselections"] = st.number_input("Max reselections after refusals", 0, 10, int(cfg["social"]["max_reselections"]), key=k("resel", exp), disabled=dis)
            cfg["social"]["declared_prior"] = st.slider("Prior score, declared domain", 0.0, 1.0, float(cfg["social"]["declared_prior"]), 0.05, key=k("dp", exp), disabled=dis)
            cfg["social"]["undeclared_prior"] = st.slider("Prior score, undeclared domain", 0.0, 1.0, float(cfg["social"]["undeclared_prior"]), 0.05, key=k("up", exp), disabled=dis)
            cfg["social"]["referral_weight_default"] = st.slider("Referral weight for unknown referrers", 0.0, 1.0, float(cfg["social"]["referral_weight_default"]), 0.05, key=k("rw", exp), disabled=dis)
        with c3:
            st.markdown("Trust (Beta reputation)")
            cfg["social"]["prior_alpha"] = st.number_input("Prior α", 0.1, 20.0, float(cfg["social"]["prior_alpha"]), 0.5, key=k("pa", exp), disabled=dis)
            cfg["social"]["prior_beta"] = st.number_input("Prior β", 0.1, 20.0, float(cfg["social"]["prior_beta"]), 0.5, key=k("pb", exp), disabled=dis)
            cfg["social"]["domain_min_obs"] = st.number_input("Min observations for domain-specific evidence", 1, 20, int(cfg["social"]["domain_min_obs"]), key=k("mo", exp), disabled=dis)
            st.markdown("Analysis")
            cfg["analysis"]["cold_start_episodes"] = st.number_input("Cold-start episodes", 100, 3000, int(cfg["analysis"]["cold_start_episodes"]), 100, key=k("cold", exp), disabled=dis)
            ids = [a["id"] for a in cfg["agents"]]
            cfg["best_fixed_agents"] = st.multiselect("best_fixed agents (first available is used)", ids,
                                                      default=[a for a in cfg.get("best_fixed_agents", []) if a in ids], key=k("bf", exp), disabled=dis)
        st.markdown("**Run settings** (replay)")
        r1, r2, r3, r4 = st.columns(4)
        cfg["seeds"] = r1.slider("Seeds", 1, 20, int(cfg["seeds"]), key=k("seeds", exp), disabled=dis, help="Seed i of your run is seed i of the paper.")
        cfg["episodes"] = r2.select_slider("Episodes per seed and policy", options=list(range(300, 3001, 100)), value=int(cfg["episodes"]), key=k("episodes", exp), disabled=dis)
        cfg["policies"] = r3.multiselect("Policies", list(S.POLICIES), default=[p_ for p_ in cfg["policies"] if p_ in S.POLICIES], format_func=lambda p_: POLICY_LABEL[p_], key=k("policies", exp), disabled=dis)
        cfg["analysis"]["bootstrap_resamples"] = r4.select_slider("Bootstrap resamples", options=[1000, 2000, 5000, 10000], value=int(cfg["analysis"]["bootstrap_resamples"]), key=k("boot", exp), disabled=dis)
        with st.expander("Policy glossary"):
            for p_, h in POLICY_HELP.items():
                st.markdown(f"- **{POLICY_LABEL[p_]}** (`{p_}`): {h}")
        problems = validate_config(cfg, D.load_competence_map())
        if problems:
            st.error("Fix before saving:\n\n- " + "\n- ".join(problems))
        elif unsaved(exp):
            st.warning("Unsaved changes: save them to use them in runs.")
        b1, b2, b3 = st.columns(3)
        if editable and b1.button("Save configuration", type="primary", disabled=bool(problems) or not unsaved(exp), width="stretch"):
            try:
                EX.update_config(principal, exp["id"], cfg); open_experiment(exp["id"]); st.success("Saved."); st.rerun()
            except X.ExperimentError as err:
                st.error(str(err))
        if b2.button("Discard changes", disabled=not unsaved(exp), width="stretch"):
            open_experiment(exp["id"]); st.rerun()
        b3.download_button("Download configuration JSON", json.dumps(cfg, indent=2), file_name=f"{exp['name']}.json", mime="application/json", width="stretch")
        if editable:
            up = st.file_uploader("Upload a configuration JSON to replace the draft", type="json", key=k("upload", exp))
            if up is not None:
                try:
                    new = json.load(up)
                    if "agents" in new and "social" in new:
                        ss.drafts[exp["id"]] = new; ss.draft_version[exp["id"]] += 1; st.rerun()
                    else:
                        st.error("Not a population configuration (missing `agents` or `social`).")
                except json.JSONDecodeError as e:
                    st.error(f"Invalid JSON: {e}")


# ---- Replay: run the saved configuration, browse the experiment's replay runs ----
with TABS["Replay"]:
    exp = need_experiment()
    if exp:
        st.subheader(f"Replay · {exp['name']}")
        cfg = exp["config"]
        if unsaved(exp):
            st.warning("The Configure tab has unsaved changes: runs use the **saved** configuration.")
        est = estimate_seconds(cfg) * server_speed_factor()
        st.caption(f"Saved configuration: {len(cfg['agents'])} agents, {cfg['seeds']} seeds × {cfg['episodes']} episodes × {len(cfg['policies'])} policies. "
                   f"Estimated time on this server: about {est:.0f} s.")
        if principal.can("replay.run") and st.button("Run replay", type="primary"):
            problems = validate_config(cfg, D.load_competence_map())
            if problems:
                st.error("Saved configuration invalid:\n\n- " + "\n- ".join(problems))
            else:
                key_ = config_hash(cfg); store = results_store()
                if key_ in store:
                    results = store[key_]; st.caption("Identical configuration already computed on this server: results served from memory.")
                else:
                    bar = st.progress(0.0, text="starting"); t0 = time.perf_counter()

                    def progress(done, total, policy, seed):
                        el = time.perf_counter() - t0; eta = el / done * (total - done)
                        bar.progress(done / total, text=f"{done}/{total}: {POLICY_LABEL[policy]}, seed {seed}; {el:.0f} s elapsed, about {eta:.0f} s left")
                    results = run_experiment(cfg, D.load_competence_map(), progress=progress)
                    results["elapsed_seconds"] = round(time.perf_counter() - t0, 2)
                    if len(store) >= 64:
                        store.pop(next(iter(store)))
                    store[key_] = results
                    bar.progress(1.0, text=f"done in {results['elapsed_seconds']:.1f} s")
                rid = EX.record_run(principal, exp["id"], "replay", results); select_run(exp, "replay", rid); st.rerun()
        runs = EX.runs(exp["id"], kind="replay")
        if not runs:
            st.info("No replay run yet for this experiment. Press **Run replay**. The paper's own numbers are in the **Paper comparison** tab.")
        else:
            def run_label(r):
                pol = ", ".join(f"{p_} {v:.3f}" for p_, v in r["summary"]["policies"].items())
                return f"{r['ts'][:16].replace('T', ' ')} UTC · {r['user']} · v{r['config_version']} · {r['summary']['seeds']} seeds × {r['summary']['episodes']} · {pol}"
            sel = selected_run(exp, "replay")
            chosen = st.selectbox("Replay run", runs, format_func=run_label, index=next(i for i, r in enumerate(runs) if r["id"] == sel["id"]), key=f"replay_pick_{exp['id']}")
            if chosen["id"] != sel["id"]:
                select_run(exp, "replay", chosen["id"]); st.rerun()
            if EX.current_run_matches(exp, chosen):
                st.success("This run was made with the current saved configuration.")
            else:
                st.warning("The saved configuration has changed since this run (version " + str(chosen["config_version"]) + f" then, {exp['config_version']} now).")
            try:
                render_replay_results(EX.load_run(chosen["id"]))
            except Exception as e:
                st.error(f"Could not load this run: {e}")


# ---- Live ----
def live_panel(principal, exp):
    cfg = exp["config"]
    pr = pricing(); pool = D.load_pool("bcb-live-pool.json"); ref = D.load_reference_file("social-live-v1-results.json")
    st.subheader(f"Live · {exp['name']}")
    st.markdown(
        "Same population, graph, trust rules and policies as the replay, but every honest-type execution is a **real call to an OpenAI key** on one of "
        "the 121 out-of-sample tasks of the paper's live validation, graded by the isolated grader service before the trust update. Lazy shirking, "
        "impostor and refused episodes make no call and cost nothing. Keys stay in the server-side session memory for the run and are never stored or logged.")
    if unsaved(exp):
        st.warning("The Configure tab has unsaved changes: live runs use the **saved** configuration.")
    c1, c2 = st.columns(2)
    with c1:
        h = grader_health(GRADER_URL)
        if h.get("ok"):
            st.success(f"Grader reachable: {h.get('version')}, {h.get('workers')} workers, {h.get('busy')} busy.")
        else:
            st.error(f"Grader not reachable at {GRADER_URL}: {h.get('error')}. Live runs are disabled.")
    with c2:
        ds = dataset_status()
        if ds:
            st.success("Task dataset present (BigCodeBench v0.1.4, hash verified).")
        else:
            st.warning("Task dataset not fetched yet (2.3 MB from Hugging Face, verified against the frozen SHA-256).")
            if st.button("Fetch dataset"):
                try:
                    B.ensure_dataset(access().data_dir); st.rerun()
                except Exception as e:
                    st.error(f"Could not fetch the dataset: {e}")
    with st.expander("Reference: the paper's live validation (27 September 2026, 1,029 real calls, 0.29 USD)"):
        pooled_ref = ref.get("pooled", {}); transfer = ref.get("transfer", {})
        rows = [{"policy": pol, "episodes": v.get("episodes"), "success rate": v.get("success_rate"), "calls": v.get("calls")}
                for pol, v in pooled_ref.items() if isinstance(v, dict) and "success_rate" in v]
        if rows:
            st.dataframe(pd.DataFrame(rows).style.format({"success rate": "{:.3f}"}), width="stretch", hide_index=True)
        if transfer:
            st.caption("Base models on unseen tasks: " + "; ".join(f"{b} live {v['live_rate']:.3f} vs map {v['map_rate']:.3f} ({v['live_calls']} calls)"
                                                                    for b, v in transfer.items() if isinstance(v, dict) and "live_rate" in v))
    st.markdown("**New live run**")
    st.caption(f"Saved configuration: {len(cfg['agents'])} agents, degree {cfg['graph']['degree']}, radius {cfg['social']['radius']}. Only the two measured base models can run live.")
    f1, f2, f3 = st.columns(3)
    episodes = f1.select_slider("Episodes per seed and policy", options=[100, 200, 300], value=100, key="live_episodes")
    seeds = f2.multiselect("Seeds", [0, 1, 2, 3, 4], default=[0], key="live_seeds")
    policies = f3.multiselect("Policies", list(L.LIVE_POLICIES), default=["random", "social"], format_func=lambda p_: POLICY_LABEL[p_], key="live_policies")
    q = L.quote(pr, episodes, seeds or [0], policies or ["random"])
    st.info(f"Quote from the paper's live run: about {q['expected_calls']} real calls over {q['episodes']} episodes, expected upper cost about "
            f"{q['expected_upper_usd']:.3f} USD. Suggested cap {q['suggested_cap_usd']:.3f} USD. The run stops before any call that could cross the cap.")
    acc = access()
    shared_ok = bool(acc.shared_key_status()) and not principal.legacy and auth_required()
    remaining = acc.remaining_allowance(principal.id) if shared_ok else 0.0
    sources = ["My own key"] + ([f"Shared laboratory key (remaining allowance {remaining:.2f} USD)"] if shared_ok and remaining > 0 else [])
    if shared_ok and remaining <= 0:
        st.caption("A shared laboratory key exists, but you have no remaining allowance on it: ask an administrator.")
    with st.form("live_run", border=True):
        source = st.radio("Key to use", sources, index=len(sources) - 1, horizontal=True)
        key = st.text_input("Your OpenAI API key (kept in memory for this run only; ignored when the shared key is chosen)", type="password", autocomplete="off")
        default_cap = float(min(LIVE_MAX_CAP, max(0.01, q["suggested_cap_usd"])))
        if len(sources) > 1:
            default_cap = float(min(default_cap, remaining))
        cap = st.number_input("Spending cap, USD (upper cost, never crossed)", min_value=0.01, max_value=LIVE_MAX_CAP, value=max(0.01, default_cap), step=0.01, format="%.2f")
        start = st.form_submit_button("Start live run", type="primary", disabled=not grader_health(GRADER_URL).get("ok"))
    if start:
        problems = validate_config(cfg, D.load_competence_map())
        use_shared = source != "My own key"
        if use_shared:
            try:
                key = acc.shared_key_for(principal, f"{cap:.2f}")
            except ACC.AccessError as e:
                st.error(str(e)); return
        if not key.strip():
            st.error("Enter your API key or choose the shared key."); return
        if not seeds or not policies:
            st.error("Choose at least one seed and one policy."); return
        if problems:
            st.error("Saved configuration invalid:\n\n- " + "\n- ".join(problems)); return
        bases = set(cfg["base_models"].values()) - set(pr["models"])
        if bases:
            st.error(f"Live mode supports only the measured base models; unknown: {sorted(bases)}"); return
        try:
            path = B.ensure_dataset(acc.data_dir); tasks = B.load_tasks(path, pool["task_order"])
        except Exception as e:
            st.error(f"Dataset problem: {e}"); return
        ledger = L.SessionLedger(pr, f"{cap:.2f}")
        executor = L.HttpLiveExecutor(key.strip(), pr, ledger, tasks, cfg["base_models"], GRADER_URL, GRADER_TOKEN)
        total = episodes * len(seeds) * len(policies)
        bar = st.progress(0.0, text="starting"); t0 = time.perf_counter(); count = {"n": 0}

        def on_episode(record, stats):
            count["n"] += 1; el = time.perf_counter() - t0
            bar.progress(min(1.0, count["n"] / total), text=f"{count['n']}/{total} episodes; {stats['policy']} seed {stats['seed']}; "
                         f"{ledger.summary()['calls']} calls, upper cost {float(ledger.upper):.4f} USD; {el:.0f} s")
        results = L.run_live(cfg, D.load_competence_map(), pool, executor, episodes, seeds, policies, on_episode=on_episode)
        del key
        results["elapsed_seconds"] = round(time.perf_counter() - t0, 1); results["user"] = principal.id
        results["key_source"] = "shared" if use_shared else "own"; results["cap_usd"] = f"{cap:.2f}"
        results["config"] = cfg; results["config_sha256"] = config_hash(cfg); results["experiment"] = exp["id"]
        results["grader"] = grader_health(GRADER_URL)
        if auth_required():
            acc.record_spend(principal, results["key_source"], results["ledger"]["upper_cost_usd"], results["ledger"]["calls"], results["status"], f"{cap:.2f}")
        print(json.dumps({"event": "live_run", "user": principal.id, "experiment": exp["id"], "status": results["status"], "episodes": total,
                          **results["ledger"], "seconds": results["elapsed_seconds"]}), flush=True)
        rid = EX.record_run(principal, exp["id"], "live", results); select_run(exp, "live", rid)
        bar.progress(1.0, text=f"{results['status']} in {results['elapsed_seconds']} s"); st.rerun()
    runs = EX.runs(exp["id"], kind="live")
    if not runs:
        st.caption("No live run yet for this experiment."); return
    def live_label(r):
        sm = r["summary"]; pol = ", ".join(f"{p_} {v:.3f}" for p_, v in sm["policies"].items() if v is not None)
        return f"{r['ts'][:16].replace('T', ' ')} UTC · {r['user']} · {sm.get('status')} · {sm.get('calls')} calls · {float(sm.get('upper_cost_usd') or 0):.4f} USD · {sm.get('key_source')} key · {pol}"
    sel = selected_run(exp, "live")
    chosen = st.selectbox("Live run", runs, format_func=live_label, index=next(i for i, r in enumerate(runs) if r["id"] == sel["id"]), key=f"live_pick_{exp['id']}")
    if chosen["id"] != sel["id"]:
        select_run(exp, "live", chosen["id"]); st.rerun()
    if chosen["config_sha256"] and EX.current_run_matches(exp, chosen):
        st.success("This run was made with the current saved configuration.")
    else:
        st.warning("Made with an earlier configuration of this experiment.")
    try:
        res = EX.load_run(chosen["id"])
    except Exception as e:
        st.error(f"Could not load this run: {e}"); return
    led = res.get("ledger", {})
    st.markdown(f"Status **{res.get('status')}**{(': ' + res.get('message', '')) if res.get('message') else ''}. "
                f"{led.get('calls')} real calls, upper cost **{float(led.get('upper_cost_usd') or 0):.4f} USD** (estimated with caching {float(led.get('estimated_cost_usd') or 0):.4f}), "
                f"cap {led.get('cap_usd')} USD, {res.get('elapsed_seconds')} s.")
    pl = L.pooled(res)
    prow = [{"policy": POLICY_LABEL.get(p_, p_), "episodes": v["episodes"], "success rate": v["success_rate"], "calls": v["calls"],
             "unreliable share, first window": (v["unreliable_share_by_window"] or [None])[0],
             "unreliable share, last window": (v["unreliable_share_by_window"] or [None])[-1]} for p_, v in pl["policies"].items()]
    if prow:
        st.dataframe(pd.DataFrame(prow).style.format({"success rate": "{:.3f}", "unreliable share, first window": "{:.3f}", "unreliable share, last window": "{:.3f}"}, na_rep="n/a"),
                     width="stretch", hide_index=True)
    if "social" in pl["policies"] and "random" in pl["policies"]:
        d = (pl["policies"]["social"]["success_rate"] or 0) - (pl["policies"]["random"]["success_rate"] or 0)
        st.caption(f"social minus random in this run: {d * 100:+.1f} points (the paper's live run: +2.8 points over 600 episodes per policy).")
    base_rows = [{"base model": b, "calls": v["calls"], "live success rate": v["live_rate"], "map rate": D.load_competence_map()["models"].get(b, {}).get("pass_rate")}
                 for b, v in pl["by_base"].items()]
    if base_rows:
        st.dataframe(pd.DataFrame(base_rows).style.format({"live success rate": "{:.3f}", "map rate": "{:.3f}"}, na_rep="n/a"), width="stretch", hide_index=True)
    wrows = [{"policy": p_, "episode": 100 * (i + 1), "value": x} for p_, v in pl["policies"].items() for i, x in enumerate(v["success_by_window"])]
    if wrows:
        st.plotly_chart(line_chart(pd.DataFrame(wrows), "Live success by window", "success rate"), width="stretch")
    calls = executor_entries(res)
    with st.expander("Calls ledger"):
        if calls:
            st.dataframe(pd.DataFrame(calls), width="stretch", hide_index=True)
        else:
            st.caption("No calls.")
    d1, d2 = st.columns(2)
    d1.download_button("Live results JSON (no code, no key)", json.dumps(res, indent=1), file_name="live-results.json", mime="application/json")
    d2.download_button("Episode log CSV", pd.DataFrame([rec for r in res.get("runs", []) for rec in r.get("records", [])]).to_csv(index=False),
                       file_name="live-episodes.csv", mime="text/csv")


def executor_entries(res):
    return [{k_: rec.get(k_) for k_ in ("policy", "seed", "e", "call", "model", "task", "input_tokens", "output_tokens", "upper_cost_usd",
                                        "response_status", "latency_seconds", "grade_status", "grade_seconds")}
            for r in res.get("runs", []) for rec in r.get("records", []) if rec.get("effect") == "call"]


if "Live" in TABS:
    with TABS["Live"]:
        exp = need_experiment()
        if exp:
            live_panel(principal, exp)


# ---- History: every run of the open experiment ----
with TABS["History"]:
    exp = need_experiment()
    if exp:
        st.subheader(f"History · {exp['name']}")
        runs = EX.runs(exp["id"])
        if not runs:
            st.caption("No runs yet.")
        else:
            rows = []
            for r in runs:
                sm = r["summary"]
                rows.append({"when (UTC)": r["ts"][:16].replace("T", " "), "kind": r["kind"], "by": r["user"], "status": r["status"],
                             "config version": r["config_version"], "matches current": EX.current_run_matches(exp, r),
                             "policies": ", ".join(f"{p_} {v:.3f}" for p_, v in sm.get("policies", {}).items() if v is not None),
                             "seeds": sm.get("seeds") if isinstance(sm.get("seeds"), int) else len(sm.get("seeds") or []), "episodes": sm.get("episodes"),
                             "calls": sm.get("calls"), "upper cost USD": sm.get("upper_cost_usd"), "key": sm.get("key_source")})
            st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
            pick = st.selectbox("Run", runs, format_func=lambda r: f"{r['ts'][:16].replace('T', ' ')} · {r['kind']} · {r['user']} · {r['status']}", key=f"hist_{exp['id']}")
            if st.button("Select this run in its tab"):
                select_run(exp, pick["kind"], pick["id"]); st.success(f"Selected: open the **{pick['kind'].capitalize()}** tab."); 


with TABS["Paper comparison"]:
    st.subheader("Pre-registered results of the paper")
    ref_name = st.selectbox("Reference run", D.preset_names(), index=paper_default_index(),
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
    results = selected_replay_results()
    if results:
        st.subheader("The open experiment's selected replay run against this reference")
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



with TABS["Data and method"]:
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


with TABS["Account"]:
    st.subheader("Your account")
    st.markdown(f"**{principal.name}** (`{principal.id}`), role **{principal.role_label}**. You can: " +
                ", ".join(f"`{c}`" for c in sorted(principal.capabilities)) + ".")
    if auth_required() and not principal.legacy:
        st.markdown("**Change password**")
        password_change_form(principal)
    elif principal.legacy:
        st.info("The bootstrap credential has no account: create yours in the Administration tab.")

if "Administration" in TABS:
    with TABS["Administration"]:
        admin_panel(principal)


with sidebar_status.container():
    exp = current_experiment()
    if exp:
        st.markdown(f"**Open experiment**  \n{exp['name']}")
        st.caption(f"owner {exp['owner']} · version {exp['config_version']}" + (f" · from {exp['origin_preset']}" if exp.get("origin_preset") else "")
                   + (" · **unsaved changes**" if unsaved(exp) else ""))
    else:
        st.info("No experiment open. Create or open one in the **Experiments** tab.")
