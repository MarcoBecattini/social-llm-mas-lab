"""Plotly figures of the laboratory, unchanged from the validated originals: policies keep fixed colour slots and
are also told apart by dash and marker; reference lines are drawn in secondary ink."""
import plotly.graph_objects as go

from socialmas import sim as S

from .state import POLICY_LABEL, PROFILE_ORDER
from .theme import GRID, INK, INK2, SLOTS, SURFACE

POLICY_STYLE = {  # slot colours in fixed order; reference lines in ink
    "random": (SLOTS[0], "dot", "circle"), "declared": (SLOTS[1], "dash", "square"),
    "social_nobefriend": (SLOTS[2], "dashdot", "triangle-up"), "social_noref": (SLOTS[3], "longdash", "triangle-down"),
    "social": (SLOTS[4], "solid", "diamond"), "social_refcheck": (SLOTS[5], "solid", "star"),
    "best_fixed": (INK2, "dash", "x"), "oracle": (INK2, "dot", "cross")}
PROFILE_COLOR = dict(zip(PROFILE_ORDER, SLOTS))
MODEL_COLOR = SLOTS[:3]
LAYOUT = dict(template="simple_white", paper_bgcolor=SURFACE, plot_bgcolor=SURFACE, font=dict(color=INK, size=13),
              margin=dict(l=10, r=10, t=60, b=10), title_y=0.97, title_yanchor="top", hoverlabel=dict(bgcolor="white"))


def legend_below(n_series):
    """Horizontal legend under the x axis, with a bottom margin that fits it even when the chart is narrow."""
    rows = -(-n_series // 2)
    return dict(legend=dict(orientation="h", yanchor="top", y=-0.2, x=0, font=dict(size=11)),
                margin=dict(l=10, r=10, t=60, b=50 + 24 * rows))


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
                             marker=dict(color=SLOTS[0], size=9, line=dict(color="white", width=1)),
                             error_x=dict(type="data", symmetric=False, array=df["ci_high"] - df["points"],
                                          arrayminus=df["points"] - df["ci_low"], color=SLOTS[0], thickness=2, width=0),
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
