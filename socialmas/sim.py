"""Replay simulator for social discovery and outcome-based trust over a measured competence map.

Engine of the pre-registered experiments (v2, 11 agents; v3, 30 agents with lying referrers). The code below the
imports is the validated engine from the research repository (`scripts/social_sim.py`), kept verbatim so that the
published results reproduce bit for bit; only the command-line entry point moved to `socialmas.cli`.

Policies never read the map: they only see declarations, their own trust records, referral opinions and episode
outcomes. Only `oracle` and `best_fixed` read or assume ground truth (reference lines, not social policies)."""
import json
import random
from collections import defaultdict

PROFILES = ("honest", "boaster", "impostor", "lazy", "specialist", "unstable", "liar")
DOMAINS = ["Cryptography", "Network", "Time", "System", "Visualization", "General", "Computation"]
POLICIES = ("random", "declared", "best_fixed", "oracle", "social_noref", "social_nobefriend", "social", "social_refcheck")
SOCIAL_POLICIES = ("social_noref", "social_nobefriend", "social", "social_refcheck")


class Agent:
    def __init__(self, spec, declared):
        self.id = spec["id"]; self.base = spec["base"]; self.profile = spec["profile"]
        self.lazy_p = spec.get("lazy_p", 0.0); self.phase_length = spec.get("phase_length", 0)
        self.declared = set(declared)
        self.liar = spec["profile"] == "liar"          # honest worker, inverted referral reports (v3)
        self.calls = 0


class World:
    """Tasks, agents, graph and ground truth. Policies must only use `discover`, `execute` and their own memory."""

    def __init__(self, cfg, cmap, seed):
        self.cfg = cfg
        self.rng_world = random.Random(f"world:{seed}")
        bases = cfg["base_models"]
        self.outcome = {b: {} for b in bases}; self.cost = {b: {} for b in bases}; self.domain = {}
        for tid, row in cmap["tasks"].items():
            self.domain[tid] = row["drawn_for_domain"]
            for b, model in bases.items():
                o = row["outcomes"][model]
                self.outcome[b][tid] = o["status"] == "pass"
                self.cost[b][tid] = float(o["upper_cost_usd"] or 0)
        all_tasks = sorted(cmap["tasks"])
        discriminating = [t for t in all_tasks if any(self.outcome[b][t] for b in bases)]
        self.hard = [t for t in all_tasks if t not in set(discriminating)]
        self.pool = all_tasks if cfg["task_pool"]["rule"] == "all" else discriminating
        self.by_domain = {d: [t for t in self.pool if self.domain[t] == d] for d in DOMAINS}
        # declarations use the published map (all tasks); ground truth uses the pool actually sampled
        self.map_rate = {b: {d: self._rate(b, d, all_tasks) for d in DOMAINS} for b in bases}
        self.base_rate = {b: {d: self._rate(b, d, self.pool) for d in DOMAINS} for b in bases}
        thr = cfg["declaration_threshold"]
        self.agents = {}
        for spec in cfg["agents"]:
            honest_decl = {d for d in DOMAINS if self.map_rate[spec["base"]][d] >= thr}
            declared = {"honest": honest_decl, "lazy": honest_decl, "unstable": honest_decl, "liar": honest_decl,
                        "boaster": set(DOMAINS), "impostor": set(DOMAINS),
                        "specialist": set(spec.get("domains", []))}[spec["profile"]]
            self.agents[spec["id"]] = Agent(spec, declared)
        self.ids = sorted(self.agents)
        self.friends = self._connected_graph(cfg["graph"]["degree"])
        self.episode = 0
        # per-worker draw streams: the k-th call of a worker yields the same task and coin under every policy
        self.lazy_rng = {a: random.Random(f"lazy:{seed}:{a}") for a in self.ids}
        self.task_rng = {a: random.Random(f"task:{seed}:{a}") for a in self.ids}

    def _rate(self, base, domain, tasks):
        ts = [t for t in tasks if self.domain[t] == domain]
        return sum(self.outcome[base][t] for t in ts) / len(ts) if ts else 0.0

    def _connected_graph(self, degree):
        ids = list(self.ids); rng = self.rng_world
        friends = {a: set() for a in ids}
        order = ids[:]; rng.shuffle(order)
        for i in range(1, len(order)):                      # spanning tree guarantees connectivity, under the degree cap
            eligible = [j for j in range(i) if len(friends[order[j]]) < degree + 1] or list(range(i))
            j = rng.choice(eligible); friends[order[i]].add(order[j]); friends[order[j]].add(order[i])
        target = degree * len(ids) // 2
        edges = sum(len(v) for v in friends.values()) // 2
        attempts = 0
        while edges < target and attempts < 10000:
            a, b = rng.sample(ids, 2); attempts += 1
            if b not in friends[a] and len(friends[a]) < degree + 1 and len(friends[b]) < degree + 1:
                friends[a].add(b); friends[b].add(a); edges += 1
        return friends

    # ---- ground truth (reference lines and evaluation only) ----
    def lazy_phase(self, agent):
        return agent.profile == "lazy" or (agent.profile == "unstable" and (self.episode // agent.phase_length) % 2 == 1)

    def true_rate(self, agent_id, domain):
        a = self.agents[agent_id]; r = self.base_rate[a.base][domain]
        if a.profile == "impostor":
            return 0.0
        if a.profile == "specialist":
            return r if domain in a.declared else 0.0
        if a.profile == "lazy":
            return r * (1 - a.lazy_p)
        if a.profile == "unstable":
            return r * (1 - a.lazy_p * self.lazy_share(a))
        return r

    def lazy_share(self, agent):
        """Fraction of episodes in which an unstable agent is in a lazy phase, given the configured run length."""
        episodes = self.cfg["episodes"]
        lazy = sum(1 for e in range(episodes) if (e // agent.phase_length) % 2 == 1)
        return lazy / episodes

    def true_overall(self, agent_id):
        return sum(self.true_rate(agent_id, d) * len(self.by_domain[d]) for d in DOMAINS) / len(self.pool)

    def unreliable_now(self, agent_id):
        a = self.agents[agent_id]; spec = set(self.cfg["analysis"]["unreliable_profiles"])
        return a.profile in spec or ("unstable_lazy_phase" in spec and a.profile == "unstable" and self.lazy_phase(a))

    # ---- environment interface ----
    def execute(self, worker_id, domain):
        """Replay with replacement: the worker's outcome is resampled from the measured table for that domain."""
        a = self.agents[worker_id]; a.calls += 1
        if a.profile == "specialist" and domain not in a.declared:
            return {"success": False, "cost": 0.0, "refused": True, "task": None}
        task = self.task_rng[worker_id].choice(self.by_domain[domain])
        if a.profile == "impostor":
            return {"success": False, "cost": self.cost[a.base][task], "refused": False, "task": task}
        if self.lazy_phase(a) and self.lazy_rng[worker_id].random() < a.lazy_p:
            return {"success": False, "cost": self.cost[a.base][task], "refused": False, "lazy": True, "task": task}
        return {"success": self.outcome[a.base][task], "cost": self.cost[a.base][task], "refused": False, "task": task}

    def report(self, referrer, worker, domain, trust):
        """What `referrer` reports about `worker` in `domain`: honest agents report their evidence; a liar reports the
        opposite verdict, amplified. "Bad" is relative to the liar's own experience: a worker whose overall estimate is
        at or below the liar's mean estimate over the workers it knows is promoted as (n+2, 0); a better-than-average
        worker is denigrated as (0, n+2)."""
        rs, rf = trust[referrer].evidence(worker, domain)
        if rs + rf == 0:
            return 0, 0
        if self.agents[referrer].liar:
            book = trust[referrer]
            known = [book.overall_estimate(w) for w in book.obs if book.n(w) > 0]
            mean_known = sum(known) / len(known)
            n = rs + rf + 2
            return (n, 0) if book.overall_estimate(worker) <= mean_known else (0, n)
        return rs, rf

    def reachable(self, requester, radius):
        direct = set(self.friends[requester])
        if radius < 2:
            return direct, direct
        fof = set().union(*(self.friends[f] for f in direct)) if direct else set()
        return direct, (direct | fof) - {requester}

    def befriend(self, a, b):
        self.friends[a].add(b); self.friends[b].add(a)


class Trust:
    """Beta reputation held by one requester about workers, overall and per domain. Refusals are not failures."""

    def __init__(self, cfg):
        self.a0 = cfg["prior_alpha"]; self.b0 = cfg["prior_beta"]; self.min_obs = cfg["domain_min_obs"]
        self.obs = defaultdict(lambda: {"overall": [0, 0], "domain": defaultdict(lambda: [0, 0])})
        self.refusals = defaultdict(lambda: defaultdict(int))
        self.ref_acc = defaultdict(lambda: [0, 0])      # per referrer: [reports confirmed, reports contradicted]
        self.scored = set()                              # (referrer, worker) pairs already scored by this requester

    def note_referral(self, referrer, report_estimate, own_estimate, tolerance=0.2):
        """Score a referrer's report against the requester's own posterior on the same worker (hit if within tolerance)."""
        self.ref_acc[referrer][0 if abs(report_estimate - own_estimate) <= tolerance else 1] += 1

    def referral_weight(self, referrer):
        hit, miss = self.ref_acc[referrer]
        return (self.a0 + hit) / (self.a0 + self.b0 + hit + miss)

    def update(self, worker, domain, success):
        rec = self.obs[worker]; k = 0 if success else 1
        rec["overall"][k] += 1; rec["domain"][domain][k] += 1

    def note_refusal(self, worker, domain):
        self.refusals[worker][domain] += 1

    def evidence(self, worker, domain):
        """(successes, failures) direct evidence: domain-specific if enough observations, else overall."""
        rec = self.obs.get(worker)
        if rec is None:
            return 0, 0
        s, f = rec["domain"][domain]
        if s + f < self.min_obs:
            s, f = rec["overall"]
        return s, f

    def n(self, worker):
        rec = self.obs.get(worker)
        return sum(rec["overall"]) if rec else 0

    def overall_estimate(self, worker):
        rec = self.obs.get(worker)
        if rec is None or sum(rec["overall"]) == 0:
            return None
        s, f = rec["overall"]
        return (self.a0 + s) / (self.a0 + self.b0 + s + f)


def oracle_pick(world, cands, domain, rng):
    """Central registry with verified per-domain competence: reference upper bound, not a social policy."""
    best = max(world.true_rate(w, domain) for w in cands)
    return rng.choice([w for w in cands if world.true_rate(w, domain) == best])


def referral_opinions(requester, w, domain, world, trust, direct):
    """What each direct contact reports about w: (referrer, successes, failures) as REPORTED through World.report."""
    out = []
    for fr in sorted(direct):                          # sorted: float sums must not depend on set order
        if fr == w or w not in world.friends[fr]:
            continue
        rs, rf = world.report(fr, w, domain, trust)
        if rs + rf == 0:
            continue
        out.append((fr, rs, rf))
    return out


def social_score(requester, w, domain, world, trust, direct, social, use_ref, refcheck=False):
    """Beta estimate from direct evidence pooled with discounted referral evidence; declaration prior if nothing.
    Referral weight: the requester's trust in the referrer as a worker (v2), or in `refcheck` mode the referrer's
    past referral accuracy as experienced by the requester (v3)."""
    s, f = trust[requester].evidence(w, domain)
    if use_ref:
        for fr, rs, rf in referral_opinions(requester, w, domain, world, trust, direct):
            if refcheck:
                wgt = trust[requester].referral_weight(fr)
            else:
                wgt = trust[requester].overall_estimate(fr)
                wgt = social["referral_weight_default"] if wgt is None else wgt
            s += wgt * rs; f += wgt * rf
    if trust[requester].refusals[w][domain]:
        return social["undeclared_prior"]                 # a known refuser in this domain is not asked again by choice
    if s + f == 0:
        return social["declared_prior"] if domain in world.agents[w].declared else social["undeclared_prior"]
    return (social["prior_alpha"] + s) / (social["prior_alpha"] + social["prior_beta"] + s + f)


def run_policy(policy, cfg, cmap, seed, log=None):
    world = World(cfg, cmap, seed)
    sched = random.Random(f"schedule:{seed}"); choice = random.Random(f"policy:{seed}:{policy}")
    social = cfg["social"]; trust = {a: Trust(social) for a in world.ids}
    use_trust = policy in SOCIAL_POLICIES; use_ref = policy in ("social", "social_refcheck"); refcheck = policy == "social_refcheck"
    befriend = use_trust and policy != "social_nobefriend" and social["befriend_on_success"]
    profiles = sorted({a.profile for a in world.agents.values()})   # metric only, after the decision
    def new_window():
        return {"n": 0, "success": 0, "cost": 0.0, "messages": 0, "unreliable": 0, "reach": 0,
                "by_profile": {p: 0 for p in profiles}}
    stats = {"episodes": 0, "success": 0, "cost": 0.0, "messages": 0, "refusals": 0, "reselect_failures": 0,
             "by_window": [], "by_profile": defaultdict(lambda: {"selected": 0, "success": 0}),
             "by_domain": defaultdict(lambda: {"n": 0, "success": 0}), "cold_success": 0, "cold_n": 0}
    window = new_window(); cold = cfg["analysis"]["cold_start_episodes"]
    for e in range(cfg["episodes"]):
        world.episode = e
        requester = sched.choice(world.ids)
        d = world.domain[sched.choice(world.pool)]          # domain frequency follows the pool composition
        if policy in ("oracle", "best_fixed"):
            direct, reach = set(), set(world.ids) - {requester}; messages = 2
        else:
            direct, reach = world.reachable(requester, social["radius"]); messages = 2 * len(direct)
        cands = sorted(reach)
        out = None; worker = None; refusals_here = 0
        for attempt in range(social["max_reselections"] + 1):
            if not cands:
                break
            declared = [w for w in cands if d in world.agents[w].declared]
            if policy == "random":
                worker = choice.choice(cands)
            elif policy == "declared":
                worker = choice.choice(declared or cands)
            elif policy == "best_fixed":
                fixed = [a for a in cfg["best_fixed_agents"] if a in cands]     # A01, else its clone A02
                worker = fixed[0] if fixed else choice.choice(cands)
            elif policy == "oracle":
                worker = oracle_pick(world, cands, d, choice)   # the only policy allowed to read ground truth
            else:
                scores = {w: social_score(requester, w, d, world, trust, direct, social, use_ref, refcheck) for w in cands}
                if choice.random() < social["epsilon"]:
                    worker = choice.choice(cands)
                else:
                    top = max(scores.values()); worker = choice.choice([w for w in cands if scores[w] == top])
            out = world.execute(worker, d)
            if not out["refused"]:
                break
            stats["refusals"] += 1; messages += 1; refusals_here += 1   # one extra message to ask someone else
            if use_trust:
                trust[requester].note_refusal(worker, d)
            cands = [w for w in cands if w != worker]
        if out is None or out["refused"]:
            stats["reselect_failures"] += 1
            out = {"success": False, "cost": 0.0, "refused": True, "task": None}
            worker = worker or ""
        opinions_used = referral_opinions(requester, worker, d, world, trust, direct) if (use_ref and worker and not out["refused"]) else []
        if use_trust and worker and not out["refused"]:
            trust[requester].update(worker, d, out["success"])
            if use_ref:                                   # score each contact's report against own posterior, once per pair
                own = trust[requester].overall_estimate(worker)
                if trust[requester].n(worker) >= social["domain_min_obs"]:
                    for fr, rs, rf in opinions_used:
                        if (fr, worker) not in trust[requester].scored:
                            trust[requester].scored.add((fr, worker))
                            trust[requester].note_referral(fr, (1 + rs) / (2 + rs + rf), own)
            if out["success"] and befriend:
                world.befriend(requester, worker)
        prof = world.agents[worker].profile if worker else "none"   # metric only, after the decision
        liar_opinions = sum(1 for fr, _, _ in opinions_used if world.agents[fr].liar)                     # metric only, after the decision
        liar_promoted = any(world.agents[fr].liar and rs > rf for fr, rs, rf in opinions_used) and bool(worker) and world.unreliable_now(worker)   # metric only, after the decision
        unreliable = bool(worker) and world.unreliable_now(worker)   # metric only, after the decision
        stats["liar_opinions"] = stats.get("liar_opinions", 0) + liar_opinions
        stats["liar_promoted_unreliable"] = stats.get("liar_promoted_unreliable", 0) + liar_promoted
        stats["episodes"] += 1; stats["success"] += out["success"]; stats["cost"] += out["cost"]; stats["messages"] += messages
        if e < cold:
            stats["cold_n"] += 1; stats["cold_success"] += out["success"]
        stats["by_profile"][prof]["selected"] += 1; stats["by_profile"][prof]["success"] += out["success"]
        stats["by_domain"][d]["n"] += 1; stats["by_domain"][d]["success"] += out["success"]
        window["n"] += 1; window["success"] += out["success"]; window["cost"] += out["cost"]; window["messages"] += messages
        window["unreliable"] += unreliable; window["reach"] += len(reach)
        if prof in window["by_profile"]:
            window["by_profile"][prof] += 1
        if log is not None:
            log.write(json.dumps({"policy": policy, "seed": seed, "e": e, "requester": requester, "worker": worker,
                                  "profile": prof, "domain": d, "task": out["task"], "success": out["success"],
                                  "cost": out["cost"], "messages": messages, "refused": out["refused"],
                                  "direct": len(direct), "refusals": refusals_here, "unreliable": unreliable}) + "\n")
        if window["n"] == 100:
            stats["by_window"].append(window); window = new_window()
    calib = None
    # --- evaluation only: ground truth may be read below this line ---
    if use_trust:
        errs, by_prof = [], defaultdict(list)
        for r in world.ids:
            for w in world.ids:
                if w == r or trust[r].n(w) == 0:
                    continue
                est = trust[r].overall_estimate(w); truth = world.true_overall(w)
                errs.append(abs(est - truth)); by_prof[world.agents[w].profile].append(est)
        calib = {"pairs_with_evidence": len(errs), "mean_abs_error": round(sum(errs) / len(errs), 4) if errs else None,
                 "mean_trust_by_profile": {p: round(sum(v) / len(v), 4) for p, v in by_prof.items()}}
        if refcheck:
            wts = defaultdict(list)
            for r in world.ids:
                for fr, (hit, miss) in trust[r].ref_acc.items():
                    if hit + miss:
                        wts["liar" if world.agents[fr].liar else "honest_referrer"].append(trust[r].referral_weight(fr))
            calib["referral_weight_by_referrer"] = {k: {"n": len(v), "mean": round(sum(v) / len(v), 4)} for k, v in wts.items()}
    stats["calibration"] = calib
    stats["final_degree_mean"] = round(sum(len(v) for v in world.friends.values()) / len(world.ids), 3)
    stats["pool_size"] = len(world.pool); stats["hard_size"] = len(world.hard)
    stats["by_profile"] = dict(stats["by_profile"]); stats["by_domain"] = dict(stats["by_domain"])
    return stats, world


def summarize(per_seed):
    n = len(per_seed)
    def mean(key):
        vals = [s[key] for s in per_seed]; return {"mean": round(sum(vals) / n, 4), "min": round(min(vals), 4), "max": round(max(vals), 4)}
    for s_ in per_seed:
        if s_["cost_per_success"] == float("inf"):
            s_["cost_per_success"] = None
    def mean_opt(key):
        vals = [s[key] for s in per_seed if s[key] is not None]
        return {"mean": round(sum(vals) / len(vals), 6), "min": round(min(vals), 6), "max": round(max(vals), 6)} if vals else None
    out = {"seeds": n, "success_rate": mean("success_rate"), "cold_start_success_rate": mean("cold_rate"),
           "cost_usd": mean("cost"), "cost_per_success_usd": mean_opt("cost_per_success"), "messages_per_episode": mean("msg_per_ep"),
           "refusals": mean("refusals"), "reselect_failures": mean("reselect_failures"), "final_degree_mean": mean("final_degree_mean")}
    W = min(len(s["by_window"]) for s in per_seed)
    def win(key, nd=4):
        return [round(sum(s["by_window"][i][key] / s["by_window"][i]["n"] for s in per_seed) / n, nd) for i in range(W)]
    out["success_by_window"] = win("success"); out["unreliable_share_by_window"] = win("unreliable")
    out["messages_by_window"] = win("messages", 3); out["reach_by_window"] = win("reach", 3)
    profiles = sorted({p for s in per_seed for p in s["by_profile"]})
    total = sum(s["episodes"] for s in per_seed)
    out["selection_share_by_profile"] = {p: round(sum(s["by_profile"].get(p, {"selected": 0})["selected"] for s in per_seed) / total, 4) for p in profiles}
    out["selection_share_by_profile_by_window"] = {p: [round(sum(s["by_window"][i]["by_profile"].get(p, 0) / s["by_window"][i]["n"] for s in per_seed) / n, 4) for i in range(W)] for p in profiles}
    cal = [s["calibration"] for s in per_seed if s["calibration"]]
    if cal:
        valid = [c["mean_abs_error"] for c in cal if c["mean_abs_error"] is not None]
        out["calibration"] = {"mean_abs_error": round(sum(valid) / len(valid), 4) if valid else None,
                              "mean_trust_by_profile": {p: round(sum(c["mean_trust_by_profile"][p] for c in cal if p in c["mean_trust_by_profile"]) /
                                                                  max(1, sum(p in c["mean_trust_by_profile"] for c in cal)), 4)
                                                        for p in profiles if any(p in c["mean_trust_by_profile"] for c in cal)}}
    out["liar_opinions_per_episode"] = round(sum(s.get("liar_opinions", 0) for s in per_seed) / total, 4)
    out["liar_promoted_unreliable_share"] = round(sum(s.get("liar_promoted_unreliable", 0) for s in per_seed) / total, 4)
    rw = [s["calibration"]["referral_weight_by_referrer"] for s in per_seed if s["calibration"] and "referral_weight_by_referrer" in s["calibration"]]
    if rw:
        out["referral_weight_by_referrer"] = {k: round(sum(x[k]["mean"] for x in rw if k in x) / max(1, sum(k in x for x in rw)), 4)
                                             for k in ("honest_referrer", "liar") if any(k in x for x in rw)}
        out["per_seed_referral_weight_gap"] = [x["honest_referrer"]["mean"] - x["liar"]["mean"] for x in rw if "liar" in x and "honest_referrer" in x]
    out["per_seed_success_rate"] = [s["success_rate"] for s in per_seed]
    out["per_seed_cold_rate"] = [s["cold_rate"] for s in per_seed]
    out["per_seed_unreliable_first_window"] = [s["by_window"][0]["unreliable"] / s["by_window"][0]["n"] for s in per_seed]
    out["per_seed_unreliable_last_like_window"] = [s["by_window"][s["like_window"]]["unreliable"] / s["by_window"][s["like_window"]]["n"] for s in per_seed]
    return out


def last_like_window(cfg):
    """Index of the last 100-episode window whose unstable-agent phase matches the first window's (honest)."""
    unstable = [a for a in cfg["agents"] if a["profile"] == "unstable"]
    if not unstable:
        return cfg["episodes"] // 100 - 1
    L = unstable[0]["phase_length"]; W = cfg["episodes"] // 100
    return max(i for i in range(W) if (100 * i // L) % 2 == 0 and ((100 * i + 99) // L) % 2 == 0)


def paired_bootstrap(a, b, resamples, seed=0):
    """Percentile bootstrap CI over seeds of mean(a - b), in percentage points; a and b paired by seed."""
    rng = random.Random(f"bootstrap:{seed}"); n = len(a)
    diffs = [(x - y) * 100 for x, y in zip(a, b)]
    means = []
    for _ in range(resamples):
        sample = [diffs[rng.randrange(n)] for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()
    return {"mean_points": round(sum(diffs) / n, 3), "ci95": [round(means[int(0.025 * resamples)], 3), round(means[int(0.975 * resamples) - 1], 3)],
            "seeds_positive": sum(d > 0 for d in diffs), "n": n}
