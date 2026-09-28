"""Tables from a results dict: pandas frames for the app and a Markdown report for the command line."""
import pandas as pd


def fmt(x, nd=3):
    return "n/a" if x is None else (f"{x:.{nd}f}" if isinstance(x, float) else str(x))


def headline_frame(results):
    rows = []
    for p, v in results["policies"].items():
        sr = v["success_rate"]; cps = v.get("cost_per_success_usd") or {}
        rows.append({"policy": p, "success": sr["mean"], "success_min": sr["min"], "success_max": sr["max"],
                     "cold_start_success": v["cold_start_success_rate"]["mean"],
                     "cost_usd_per_1000_episodes": v["cost_usd"]["mean"] * 1000 / results["config"]["episodes"],
                     "cost_per_success_usd": cps.get("mean"), "messages_per_episode": v["messages_per_episode"]["mean"],
                     "final_degree_mean": v["final_degree_mean"]["mean"],
                     "unreliable_share_first_window": sum(v["per_seed_unreliable_first_window"]) / len(v["per_seed_unreliable_first_window"]),
                     "unreliable_share_last_like_window": sum(v["per_seed_unreliable_last_like_window"]) / len(v["per_seed_unreliable_last_like_window"])})
    return pd.DataFrame(rows)


def differences_frame(results):
    rows = []
    for k, v in results.get("paired_differences", {}).items():
        o, c = v["overall"], v["cold_start"]
        rows.append({"comparison": k, "points": o["mean_points"], "ci_low": o["ci95"][0], "ci_high": o["ci95"][1],
                     "seeds_positive": f"{o['seeds_positive']}/{o['n']}", "cold_start_points": c["mean_points"],
                     "cold_ci_low": c["ci95"][0], "cold_ci_high": c["ci95"][1]})
    return pd.DataFrame(rows)


def windows_frame(results, key="success_by_window"):
    rows = []
    for p, v in results["policies"].items():
        for i, x in enumerate(v[key]):
            rows.append({"policy": p, "episode": 100 * (i + 1), "value": x})
    return pd.DataFrame(rows)


def selection_frame(results):
    rows = []
    for p, v in results["policies"].items():
        for prof, share in v["selection_share_by_profile"].items():
            rows.append({"policy": p, "profile": prof, "share": share})
    return pd.DataFrame(rows)


def decline_frame(results):
    rows = []
    dec = results.get("unreliable_decline", {})
    for p, v in results["policies"].items():
        d = dec.get(p)
        if not d:
            continue
        first = sum(v["per_seed_unreliable_first_window"]) / len(v["per_seed_unreliable_first_window"])
        last = sum(v["per_seed_unreliable_last_like_window"]) / len(v["per_seed_unreliable_last_like_window"])
        rows.append({"policy": p, "first_window": first, "last_like_window": last, "decline_points": d["mean_points"],
                     "ci_low": d["ci95"][0], "ci_high": d["ci95"][1]})
    return pd.DataFrame(rows)


def markdown_report(results):
    pols = list(results["policies"])
    lines = ["| Policy | Success, mean (min–max) | Cost USD / 1,000 episodes | Cost per success, USD | Messages per episode | Final mean degree |",
             "|---|---|---:|---:|---:|---:|"]
    ep = results["config"]["episodes"]
    for p in pols:
        v = results["policies"][p]; sr = v["success_rate"]; cps = v.get("cost_per_success_usd") or {}
        lines.append(f"| `{p}` | {fmt(sr['mean'])} ({fmt(sr['min'])}–{fmt(sr['max'])}) | {fmt(v['cost_usd']['mean'] * 1000 / ep, 4)} | "
                     f"{fmt(cps.get('mean'), 5)} | {fmt(v['messages_per_episode']['mean'], 2)} | {fmt(v['final_degree_mean']['mean'], 2)} |")
    lines.append("")
    W = len(results["policies"][pols[0]]["success_by_window"])
    cols = [i for i in range(W) if i in (0, 1, 2, 4, 6, 9) or i == W - 1]
    lines.append("| Policy | " + " | ".join(f"window {i + 1}" for i in cols) + " |")
    lines.append("|---|" + "---:|" * len(cols))
    for p in pols:
        w = results["policies"][p]["success_by_window"]
        lines.append(f"| `{p}` success | " + " | ".join(fmt(w[i]) for i in cols) + " |")
    for p in pols:
        w = results["policies"][p]["unreliable_share_by_window"]
        lines.append(f"| `{p}` unreliable share | " + " | ".join(fmt(w[i]) for i in cols) + " |")
    lines.append("")
    profiles = sorted({k for p in pols for k in results["policies"][p]["selection_share_by_profile"]})
    lines.append("| Policy | " + " | ".join(profiles) + " |")
    lines.append("|---|" + "---:|" * len(profiles))
    for p in pols:
        sh = results["policies"][p]["selection_share_by_profile"]
        lines.append(f"| `{p}` | " + " | ".join(fmt(sh.get(k, 0.0)) for k in profiles) + " |")
    lines.append("")
    lines.append("| Comparison | Difference, points (95% CI) | Seeds positive | Cold start, points (95% CI) |")
    lines.append("|---|---|---:|---|")
    for k, v in results.get("paired_differences", {}).items():
        o, c = v["overall"], v["cold_start"]
        lines.append(f"| {k} | {o['mean_points']:+.2f} ({o['ci95'][0]:+.2f}, {o['ci95'][1]:+.2f}) | {o['seeds_positive']}/{o['n']} | "
                     f"{c['mean_points']:+.2f} ({c['ci95'][0]:+.2f}, {c['ci95'][1]:+.2f}) |")
    lines.append("")
    lines.append("| Policy | Unreliable share, first window | Last window in the same phase | Decline, points (95% CI) |")
    lines.append("|---|---:|---:|---|")
    for _, r in decline_frame(results).iterrows():
        lines.append(f"| `{r['policy']}` | {r['first_window']:.3f} | {r['last_like_window']:.3f} | {r['decline_points']:+.2f} ({r['ci_low']:+.2f}, {r['ci_high']:+.2f}) |")
    lines.append("")
    for p in pols:
        c = results["policies"][p].get("calibration")
        if c:
            lines.append(f"- `{p}`: mean absolute error trust vs competence {fmt(c['mean_abs_error'])}; mean trust by profile " +
                         ", ".join(f"{k} {fmt(v)}" for k, v in c["mean_trust_by_profile"].items()))
    truth = results["ground_truth"]["true_overall_rate"]
    lines.append("- True overall competence per agent (evaluation only): " + ", ".join(f"{a} {fmt(v)}" for a, v in truth.items()))
    return "\n".join(lines)
