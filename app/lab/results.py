"""Results screens: headline tiles that answer the paper's questions first (gain of the social policy over random,
decline of unreliable selections, calls and cost of live runs), then the tables and the validated charts."""
import json

import pandas as pd
import streamlit as st

from socialmas import data as D
from socialmas import live as L
from socialmas import sim as S
from socialmas.report import decline_frame, differences_frame, headline_frame, markdown_report, selection_frame, windows_frame

from . import charts, state, ui
from .state import policy_label

HEADLINE_COLUMNS = {"policy": ("Policy", None, "replay.headline.policy"), "success": ("Success", "%.3f", "replay.headline.success"),
                    "success_min": ("Min", "%.3f", "replay.headline.min"), "success_max": ("Max", "%.3f", "replay.headline.max"),
                    "cold_start_success": ("Cold start", "%.3f", "replay.headline.cold"),
                    "cost_usd_per_1000_episodes": ("USD / 1,000 ep.", "%.3f", "replay.headline.cost1000"),
                    "cost_per_success_usd": ("USD / success", "%.5f", "replay.headline.cost_success"),
                    "messages_per_episode": ("Messages / ep.", "%.1f", "replay.headline.messages"),
                    "final_degree_mean": ("Final degree", "%.1f", "replay.headline.degree"),
                    "unreliable_share_first_window": ("Unreliable, first window", "%.3f", "replay.headline.unreliable_first"),
                    "unreliable_share_last_like_window": ("Unreliable, last window", "%.3f", "replay.headline.unreliable_last")}
DIFF_COLUMNS = {"comparison": ("Comparison", None, "replay.differences.comparison"), "points": ("Difference, points", "%+.2f", "replay.differences.points"),
                "ci_low": ("CI 95% low", "%+.2f", "replay.differences.ci_low"), "ci_high": ("CI 95% high", "%+.2f", "replay.differences.ci_high"),
                "seeds_positive": ("Seeds positive", None, "replay.differences.seeds_positive"),
                "cold_start_points": ("Cold start, points", "%+.2f", "replay.differences.cold"),
                "cold_ci_low": ("Cold start CI low", "%+.2f", "replay.differences.cold"), "cold_ci_high": ("Cold start CI high", "%+.2f", "replay.differences.cold")}
DECLINE_COLUMNS = {"policy": ("Policy", None, "replay.headline.policy"), "first_window": ("First window", "%.3f", "replay.decline.first"),
                   "last_like_window": ("Last window, same phase", "%.3f", "replay.decline.last"),
                   "decline_points": ("Decline, points", "%+.2f", "replay.decline.points"),
                   "ci_low": ("CI 95% low", "%+.2f", "replay.differences.ci_low"), "ci_high": ("CI 95% high", "%+.2f", "replay.differences.ci_high")}


def _mean(xs):
    return sum(xs) / len(xs) if xs else float("nan")


def best_social(means):
    """(policy, mean success) of the best social policy among those run, else None."""
    cands = [(p, v) for p, v in means.items() if p in S.SOCIAL_POLICIES and v is not None]
    return max(cands, key=lambda pv: pv[1]) if cands else None


def gain_tile(means):
    """Best social policy against random, in points; falls back to the best policy when one of the two is missing."""
    best = best_social(means); rnd = means.get("random"); tip = ui.help("replay.metric.social_vs_random")
    if best and rnd is not None:
        return {"label": f"{policy_label(best[0])} vs random", "value": f"{(best[1] - rnd) * 100:+.1f} points", "note": f"{best[1]:.3f} vs {rnd:.3f}", "help": tip}
    if best:
        return {"label": policy_label(best[0]), "value": f"{best[1]:.3f}", "note": "success rate; no random baseline in this run", "help": tip}
    known = [(p, v) for p, v in means.items() if v is not None]
    if not known:
        return {"label": "Success", "value": "n/a", "note": "no completed episodes", "help": tip}
    p, v = max(known, key=lambda pv: pv[1])
    return {"label": f"best: {policy_label(p)}", "value": f"{v:.3f}", "note": "success rate", "help": tip}


def replay_tiles(r, reference=False):
    means = {p: v["success_rate"]["mean"] for p, v in r["policies"].items()}
    t = [gain_tile(means)]
    p = (best_social(means) or (max(means, key=means.get), None))[0]; v = r["policies"][p]
    first = _mean(v["per_seed_unreliable_first_window"]); last = _mean(v["per_seed_unreliable_last_like_window"])
    dec = r.get("unreliable_decline", {}).get(p)
    t.append({"label": "Unreliable, first → last window", "value": f"{first:.0%} → {last:.0%}",
              "note": policy_label(p) + (f", {dec['mean_points']:+.1f} pts" if isinstance(dec, dict) else ""), "help": ui.help("replay.metric.unreliable")})
    cfg = r["config"]
    t.append({"label": "Seeds × episodes", "value": f"{cfg['seeds']} × {cfg['episodes']:,}", "note": f"{len(r['policies'])} policies · {len(cfg['agents'])} agents",
              "help": ui.help("replay.metric.schedule")})
    if reference:
        t.append({"label": "Generated", "value": r.get("generated_utc", "")[:10], "note": f"pool {r['ground_truth']['pool_size']} tasks", "help": ui.help("replay.metric.generated")})
    else:
        t.append({"label": "Elapsed", "value": f"{r.get('elapsed_seconds', 0):.1f} s", "note": f"pool {r['ground_truth']['pool_size']} tasks", "help": ui.help("replay.metric.elapsed")})
    return t


def render_replay(r, reference=False):
    ui.tiles(replay_tiles(r, reference))
    st.caption("Means over seeds; unreliable = lazy, impostor, unstable in a lazy phase. "
               f"{state.schedule(r['config'])}, {len(r['config']['agents'])} agents, pool {r['ground_truth']['pool_size']} tasks; "
               f"configuration {r['config_sha256'][:12]}.")
    hf = headline_frame(r)
    st.markdown("**Headline**", help=ui.help("replay.headline"))
    ui.table(hf.assign(policy=hf["policy"].map(policy_label)), HEADLINE_COLUMNS)
    df = differences_frame(r)
    if not df.empty:
        ui.chart(charts.forest_chart(df, "Paired differences by seed", float(r["config"]["analysis"].get("min_effect_points", 2.0))), help=ui.help("replay.differences"))
        with st.expander("Paired differences, table"):
            ui.table(df, DIFF_COLUMNS)
    c1, c2 = st.columns(2)
    with c1:
        ui.chart(charts.line_chart(windows_frame(r, "success_by_window"), "Success over time (100-episode windows)", "success rate"), help=ui.help("replay.success_windows"))
    with c2:
        ui.chart(charts.line_chart(windows_frame(r, "unreliable_share_by_window"), "Unreliable selections over time", "share of selections", yrange=[0, None]),
                 help=ui.help("replay.unreliable_windows"))
    c1, c2 = st.columns(2)
    with c1:
        ui.chart(charts.line_chart(windows_frame(r, "messages_by_window"), "Messages per episode over time", "messages"), help=ui.help("replay.messages_windows"))
    with c2:
        ui.chart(charts.selection_chart(selection_frame(r), "Who gets selected, by profile"), help=ui.help("replay.selection"))
    st.markdown("**Decline of unreliable selections** (first window against the last window in the same unstable phase)", help=ui.help("replay.decline"))
    dec = decline_frame(r)
    if not dec.empty:
        ui.table(dec.assign(policy=dec["policy"].map(policy_label)), DECLINE_COLUMNS)
    with st.expander("Trust calibration and referral weights (evaluation only: compares learned trust with ground truth after the run)"):
        st.caption("Evaluation only", help=ui.help("replay.calibration"))
        for p, v in r["policies"].items():
            c = v.get("calibration")
            if c:
                st.markdown(f"- **{policy_label(p)}**: mean absolute error {c['mean_abs_error']}; mean trust by profile " +
                            ", ".join(f"{a} {b:.3f}" for a, b in c["mean_trust_by_profile"].items()) +
                            (f"; referral weight honest {v['referral_weight_by_referrer'].get('honest_referrer')} vs liar {v['referral_weight_by_referrer'].get('liar')}"
                             if v.get("referral_weight_by_referrer") else ""))
        if r.get("referral_weight_gap_honest_minus_liar"):
            g = r["referral_weight_gap_honest_minus_liar"]
            st.markdown(f"- Referral weight gap honest minus liar: {g['mean_points'] / 100:+.3f} (95% CI {g['ci95'][0] / 100:+.3f}, {g['ci95'][1] / 100:+.3f})")
    with st.expander("Ground truth of this population (never visible to the policies)"):
        st.caption("Never visible to the policies", help=ui.help("replay.ground_truth"))
        gt = r["ground_truth"]
        tdf = pd.DataFrame(gt["true_rate_by_domain"]).T
        tdf.insert(0, "overall", pd.Series(gt["true_overall_rate"]))
        tdf.insert(1, "declares", pd.Series({a: ", ".join(d) for a, d in gt["declarations"].items()}))
        st.dataframe(tdf.style.format({c: "{:.2f}" for c in tdf.columns if c != "declares"}), width="stretch")
        st.caption(f"Pool rule {gt['pool_rule']}: {gt['pool_size']} tasks sampled, {gt['hard_size']} failed by both base models; initial mean degree {gt.get('initial_degree_mean')}.")
    if not reference:
        ui.downloads([("Results JSON (paper format)", json.dumps(r, indent=2), "results.json", "application/json", ui.help("replay.download.json")),
                      ("Headline CSV", hf.to_csv(index=False), "headline.csv", "text/csv", ui.help("replay.download.csv")),
                      ("Markdown report", markdown_report(r), "report.md", "text/markdown", ui.help("replay.download.md"))])


# ---- live runs ----
def executor_entries(res):
    return [{k_: rec.get(k_) for k_ in ("policy", "seed", "e", "call", "model", "task", "input_tokens", "output_tokens", "upper_cost_usd",
                                        "response_status", "latency_seconds", "grade_status", "grade_seconds")}
            for r in res.get("runs", []) for rec in r.get("records", []) if rec.get("effect") == "call"]


def live_tiles(res, pl):
    led = res.get("ledger", {})
    seeds = res.get("seeds") or []
    means = {p: v["success_rate"] for p, v in pl["policies"].items()}
    status_tip = ui.help("live.metric.status")
    if res.get("message"):
        status_tip = (status_tip + " " if status_tip else "") + f"Message: {res['message']}"
    cost_tip = ui.help("live.metric.cost")
    if cost_tip:
        cost_tip += f" Estimate with caching for this run: {float(led.get('estimated_cost_usd') or 0):.4f} USD."
    return [{"label": "Status", "value": str(res.get("status", "n/a")), "note": f"{res.get('elapsed_seconds', 0)} s", "help": status_tip},
            {"label": "Real calls", "value": f"{led.get('calls', 0)}",
             "note": f"{res.get('episodes_per_run', '?')} ep. × {len(seeds)} seeds × {len(pl['policies'])} pol.", "help": ui.help("live.metric.calls")},
            {"label": "Upper cost", "value": f"{float(led.get('upper_cost_usd') or 0):.4f} USD", "note": f"cap {led.get('cap_usd')} USD", "help": cost_tip},
            gain_tile(means)]


def render_live(res):
    pl = L.pooled(res)
    ui.tiles(live_tiles(res, pl))
    if "social" in pl["policies"] and "random" in pl["policies"]:
        d = (pl["policies"]["social"]["success_rate"] or 0) - (pl["policies"]["random"]["success_rate"] or 0)
        st.caption(f"social minus random in this run: {d * 100:+.1f} points (the paper's live run: +2.8 points over 600 episodes per policy).")
    prow = [{"policy": policy_label(p), "episodes": v["episodes"], "success_rate": v["success_rate"], "calls": v["calls"],
             "first": (v["unreliable_share_by_window"] or [None])[0], "last": (v["unreliable_share_by_window"] or [None])[-1]}
            for p, v in pl["policies"].items()]
    if prow:
        ui.table(pd.DataFrame(prow), {"policy": ("Policy", None, "replay.headline.policy"), "episodes": ("Episodes", "%d"),
                                      "success_rate": ("Success rate", "%.3f", "replay.headline.success"), "calls": ("Calls", "%d", "live.policies_table.calls"),
                                      "first": ("Unreliable, first window", "%.3f", "replay.headline.unreliable_first"),
                                      "last": ("Unreliable, last window", "%.3f", "replay.headline.unreliable_last")}, help=ui.help("live.policies_table"))
    cmap = D.load_competence_map()
    base_rows = [{"base": b, "calls": v["calls"], "live_rate": v["live_rate"], "map_rate": cmap["models"].get(b, {}).get("pass_rate")}
                 for b, v in pl["by_base"].items()]
    if base_rows:
        ui.table(pd.DataFrame(base_rows), {"base": "Base model", "calls": ("Calls", "%d"), "live_rate": ("Live success rate", "%.3f"),
                                           "map_rate": ("Map rate", "%.3f", "live.base_models.map_rate")}, help=ui.help("live.base_models"))
    wrows = [{"policy": p, "episode": 100 * (i + 1), "value": x} for p, v in pl["policies"].items() for i, x in enumerate(v["success_by_window"])]
    if wrows:
        ui.chart(charts.line_chart(pd.DataFrame(wrows), "Live success by window", "success rate"), help=ui.help("live.success_windows"))
    calls = executor_entries(res)
    with st.expander(f"Calls ledger ({len(calls)} calls)"):
        if calls:
            ui.table(pd.DataFrame(calls), {"policy": "Policy", "seed": "Seed", "e": "Episode", "call": "Call", "model": "Model", "task": "Task",
                                           "input_tokens": ("Input tokens", "%d"), "output_tokens": ("Output tokens", "%d"),
                                           "upper_cost_usd": ("Upper cost USD", None, "live.ledger.upper_cost"), "response_status": "Response",
                                           "latency_seconds": ("Latency s", "%.2f"), "grade_status": ("Grade", None, "live.ledger.grade"),
                                           "grade_seconds": ("Grading s", "%.2f")}, help=ui.help("live.ledger"))
        else:
            st.caption("No calls.")
    ui.downloads([("Live results JSON (no code, no key)", json.dumps(res, indent=1), "live-results.json", "application/json", ui.help("live.download.json")),
                  ("Episode log CSV", pd.DataFrame([rec for r in res.get("runs", []) for rec in r.get("records", [])]).to_csv(index=False),
                   "live-episodes.csv", "text/csv", ui.help("live.download.csv"))])
