"""Run a full configuration (all policies, all seeds) and produce the paper's results structure.

`run_experiment` is the library form of the research script's entry point: same policies loop, same summaries, same
paired bootstrap comparisons, same ground-truth block. It adds a progress callback for interactive use and a
configuration validator so that a hand-edited population fails early with a readable message."""
import copy
import datetime as dt
import hashlib
import json

from . import sim as S
from .data import competence_map_path, load_map_for

# Paired comparisons reported by the paper (only those whose policies were run are computed).
PAIRS = [("social", "random"), ("social", "declared"), ("social", "social_noref"), ("social", "social_nobefriend"),
         ("social_nobefriend", "declared"), ("social", "best_fixed"), ("oracle", "social"),
         ("social_refcheck", "social"), ("social_refcheck", "social_noref"), ("social_refcheck", "random"),
         ("social_refcheck", "declared")]

BASES = ("nano", "mini")


def config_hash(cfg):
    """Stable hash of a configuration (key order independent)."""
    return hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest()


def rules_signature(cfg):
    """Hash of what defines the population and the rules (not seeds, episodes, policies or analysis settings), with
    numbers normalised so that 1 and 1.0 agree. Two configurations with the same signature reproduce each other's
    per-seed numbers for every policy they share."""
    def norm(x):
        if isinstance(x, bool):
            return x
        if isinstance(x, (int, float)):
            return round(float(x), 9)
        if isinstance(x, dict):
            return {k: norm(v) for k, v in sorted(x.items())}
        if isinstance(x, list):
            return [norm(v) for v in x]
        return x
    agents = [norm({k: v for k, v in a.items()}) for a in cfg.get("agents", [])]
    core = {"agents": agents, "base_models": cfg.get("base_models"), "declaration_threshold": cfg.get("declaration_threshold"),
            "task_pool_rule": cfg.get("task_pool", {}).get("rule"), "degree": cfg.get("graph", {}).get("degree"),
            "social": cfg.get("social"), "best_fixed_agents": cfg.get("best_fixed_agents"),
            "unreliable_profiles": cfg.get("analysis", {}).get("unreliable_profiles"),
            "cold_start_episodes": cfg.get("analysis", {}).get("cold_start_episodes")}
    return hashlib.sha256(json.dumps(norm(core), sort_keys=True).encode()).hexdigest()


def validate_config(cfg, cmap=None):
    """Return a list of human-readable problems; empty means the configuration can run."""
    errors = []
    episodes = cfg.get("episodes", 0)
    if not isinstance(episodes, int) or episodes < 100 or episodes % 100:
        errors.append("episodes must be a positive multiple of 100 (the analysis window)")
    if not isinstance(cfg.get("seeds"), int) or cfg["seeds"] < 1:
        errors.append("seeds must be at least 1")
    agents = cfg.get("agents", [])
    if len(agents) < 2:
        errors.append("at least two agents are needed")
    ids = [a.get("id") for a in agents]
    if len(set(ids)) != len(ids) or any(not i for i in ids):
        errors.append("agent ids must be unique and non-empty")
    bases = cfg.get("base_models", {})
    for a in agents:
        if a.get("base") not in bases:
            errors.append(f"agent {a.get('id')}: base '{a.get('base')}' is not one of {sorted(bases)}")
        if a.get("profile") not in S.PROFILES:
            errors.append(f"agent {a.get('id')}: profile '{a.get('profile')}' is not one of {S.PROFILES}")
        if a.get("profile") in ("lazy", "unstable") and not (0.0 <= float(a.get("lazy_p", -1)) <= 1.0):
            errors.append(f"agent {a.get('id')}: lazy_p must be between 0 and 1")
        if a.get("profile") == "unstable" and int(a.get("phase_length", 0) or 0) < 1:
            errors.append(f"agent {a.get('id')}: unstable agents need phase_length >= 1")
        if a.get("profile") == "specialist":
            bad = [d for d in a.get("domains", []) if d not in S.DOMAINS]
            if not a.get("domains") or bad:
                errors.append(f"agent {a.get('id')}: specialist domains must be a non-empty subset of {S.DOMAINS}")
    if cmap is not None:
        models = set(next(iter(cmap["tasks"].values()))["outcomes"])
        for b, m in bases.items():
            if m not in models:
                errors.append(f"base '{b}' points to model '{m}' which is not in the competence map {sorted(models)}")
    degree = cfg.get("graph", {}).get("degree", 0)
    if not isinstance(degree, int) or degree < 1 or (agents and degree > len(agents) - 1):
        errors.append("graph degree must be between 1 and the number of agents minus one")
    for p in cfg.get("policies", []):
        if p not in S.POLICIES:
            errors.append(f"unknown policy '{p}'")
    if not cfg.get("policies"):
        errors.append("select at least one policy")
    if "best_fixed" in cfg.get("policies", []) and not any(a in ids for a in cfg.get("best_fixed_agents", [])):
        errors.append("best_fixed needs at least one existing agent in best_fixed_agents")
    soc = cfg.get("social", {})
    if soc.get("radius") not in (1, 2):
        errors.append("social.radius must be 1 or 2")
    if not (0.0 <= float(soc.get("epsilon", -1)) <= 1.0):
        errors.append("social.epsilon must be between 0 and 1")
    for k in ("prior_alpha", "prior_beta"):
        if float(soc.get(k, 0)) <= 0:
            errors.append(f"social.{k} must be positive")
    if cfg.get("task_pool", {}).get("rule") not in ("all", "discriminating"):
        errors.append("task_pool.rule must be 'all' or 'discriminating'")
    if not (0.0 <= float(cfg.get("declaration_threshold", -1)) <= 1.0):
        errors.append("declaration_threshold must be between 0 and 1")
    an = cfg.get("analysis", {})
    if int(an.get("bootstrap_resamples", 0)) < 100:
        errors.append("analysis.bootstrap_resamples must be at least 100")
    if not (0 < int(an.get("cold_start_episodes", 0)) <= episodes):
        errors.append("analysis.cold_start_episodes must be between 1 and episodes")
    return errors


def estimate_seconds(cfg):
    """Rough wall-clock estimate on one modern core: social policies cost more with more agents and episodes."""
    n = len(cfg.get("agents", [])); ep = cfg.get("episodes", 3000); seeds = cfg.get("seeds", 1)
    per_social = 0.30 * (n / 11) ** 1.4 * (ep / 3000)
    per_plain = 0.04 * (n / 11) * (ep / 3000)
    total = sum(per_social if p in S.SOCIAL_POLICIES else per_plain for p in cfg.get("policies", [])) * seeds
    return total


def run_experiment(cfg, cmap=None, progress=None, log=None):
    """Run every policy for every seed. `progress(done, total, policy, seed)` is called after each run.
    Returns the results dict with the same structure as the paper's provenance files."""
    cfg = copy.deepcopy(cfg)
    if cmap is None:
        cmap = load_map_for(cfg)
    problems = validate_config(cfg, cmap)
    if problems:
        raise ValueError("; ".join(problems))
    try:
        map_sha = hashlib.sha256(competence_map_path(cfg).read_bytes()).hexdigest()
    except FileNotFoundError:
        map_sha = None
    results = {"generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(), "config": cfg,
               "competence_map_sha256": map_sha, "config_sha256": config_hash(cfg), "policies": {}}
    total = len(cfg["policies"]) * cfg["seeds"]; done = 0
    truth = None
    for policy in cfg["policies"]:
        per_seed = []
        for seed in range(cfg["seeds"]):
            stats, world = S.run_policy(policy, cfg, cmap, seed, log)
            stats["success_rate"] = stats["success"] / stats["episodes"]; stats["msg_per_ep"] = stats["messages"] / stats["episodes"]
            stats["cold_rate"] = stats["cold_success"] / stats["cold_n"] if stats["cold_n"] else 0.0
            stats["cost_per_success"] = stats["cost"] / stats["success"] if stats["success"] else float("inf")
            stats["like_window"] = S.last_like_window(cfg)
            per_seed.append(stats)
            if truth is None:
                truth = {"pool_rule": cfg["task_pool"]["rule"], "pool_size": len(world.pool), "hard_size": len(world.hard),
                         "map_rate": world.map_rate, "pool_rate": world.base_rate,
                         "declarations": {a: sorted(world.agents[a].declared) for a in world.ids},
                         "true_overall_rate": {a: round(world.true_overall(a), 4) for a in world.ids},
                         "true_rate_by_domain": {a: {d: round(world.true_rate(a, d), 3) for d in S.DOMAINS} for a in world.ids},
                         "initial_degree_mean": round(sum(len(v) for v in S.World(cfg, cmap, 0).friends.values()) / len(world.ids), 3)}
            done += 1
            if progress:
                progress(done, total, policy, seed)
        results["policies"][policy] = S.summarize(per_seed)
    B = cfg["analysis"]["bootstrap_resamples"]
    results["paired_differences"] = {}
    for a, b in PAIRS:
        if a in results["policies"] and b in results["policies"]:
            pa, pb = results["policies"][a], results["policies"][b]
            results["paired_differences"][f"{a} - {b}"] = {
                "overall": S.paired_bootstrap(pa["per_seed_success_rate"], pb["per_seed_success_rate"], B),
                "cold_start": S.paired_bootstrap(pa["per_seed_cold_rate"], pb["per_seed_cold_rate"], B)}
    results["unreliable_decline"] = {p: S.paired_bootstrap(v["per_seed_unreliable_first_window"], v["per_seed_unreliable_last_like_window"], B)
                                     for p, v in results["policies"].items()}
    gap = results["policies"].get("social_refcheck", {}).get("per_seed_referral_weight_gap")
    if gap:
        results["referral_weight_gap_honest_minus_liar"] = S.paired_bootstrap(gap, [0.0] * len(gap), B)
    results["unreliable_decline"]["_note"] = (f"first window minus window {S.last_like_window(cfg) + 1} (same unstable phase), "
                                              "in points; positive = fewer unreliable selections")
    results["ground_truth"] = truth
    return results


def compare_to_reference(results, reference):
    """Per-policy differences between a run and a reference run (success rate, in points), plus whether the
    per-seed series coincide exactly on the seeds both share."""
    out = {}
    for p, v in results["policies"].items():
        r = reference["policies"].get(p)
        if not r:
            continue
        k = min(len(v["per_seed_success_rate"]), len(r["per_seed_success_rate"]))
        out[p] = {"run_mean": v["success_rate"]["mean"], "reference_mean": r["success_rate"]["mean"],
                  "delta_points": round((v["success_rate"]["mean"] - r["success_rate"]["mean"]) * 100, 2),
                  "shared_seeds": k,
                  "exact_on_shared_seeds": all(abs(x - y) < 1e-12 for x, y in
                                               zip(v["per_seed_success_rate"][:k], r["per_seed_success_rate"][:k]))}
    return out
