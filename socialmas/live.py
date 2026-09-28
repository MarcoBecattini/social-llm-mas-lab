"""Live mode: the same population, graph, trust and policies as the replay (imported from `sim`), but every honest-type
execution is a real LLM call on an out-of-sample task, graded by the grader service before the trust update.

Ported from the paper's `scripts/social_live.py` (run of 27 September 2026) with two changes for a hosted, per-user
setting: (1) a session ledger in memory with a user-chosen cap, checked before every call against the settled upper
cost plus a bound for the next call, so the cap is never exceeded; (2) grading over HTTP to the grader service instead
of a local container. Lazy shirking, impostor and refused episodes make no API call and cost 0, as in the paper's live
validation. The API key lives only in the executor object for the duration of the run."""
import json
import random
import time
from collections import defaultdict
from decimal import Decimal

from . import sim as S
from .bcb_data import PROMPT_VERSION, build_messages, calibrated_solution, extract_code

MILLION = Decimal(1_000_000)
LIVE_POLICIES = ("random", "declared", "social_noref", "social_nobefriend", "social")


class LiveStop(RuntimeError):
    pass


class CapStop(LiveStop):
    pass


class SessionLedger:
    """Per-run accounting in memory. Upper cost = every input token at the uncached price + every output token at the
    output price. `admit(model, prompt_chars)` refuses a call whose worst realistic cost would cross the cap."""

    def __init__(self, pricing, cap_usd):
        self.models = pricing["models"]; self.cap = Decimal(str(cap_usd))
        self.upper = Decimal(0); self.estimate = Decimal(0); self.entries = []; self.blocked = False

    def bound(self, model, prompt_chars):
        m = self.models[model]
        est_input = int(prompt_chars / 3) + 64          # generous: about 3 characters per token, plus the system prompt overhead
        return (Decimal(est_input * 2) * Decimal(m["input_usd_per_million"])
                + Decimal(m["max_output_tokens"]) * Decimal(m["output_usd_per_million"])) / MILLION

    def admit(self, model, prompt_chars):
        if self.blocked:
            raise LiveStop("ledger blocked after an unexpected billing response")
        b = self.bound(model, prompt_chars)
        if self.upper + b > self.cap:
            raise CapStop(f"cap of {self.cap} USD would be crossed by the next call (settled {self.upper}, bound {b:.6f})")
        return b

    def settle(self, model, response):
        m = self.models[model]
        try:
            usage = response["usage"]
            inp, out, total = usage["input_tokens"], usage["output_tokens"], usage["total_tokens"]
            cached = usage["input_tokens_details"]["cached_tokens"]
            if not all(type(v) is int and v >= 0 for v in (inp, out, total, cached)) or inp + out != total or cached > inp:
                raise ValueError("inconsistent token counts")
            if response.get("model") != model or response.get("store") is not False:
                raise ValueError("unexpected model or stored response")
            status = response.get("status")
            truncated = status == "incomplete" and (response.get("incomplete_details") or {}).get("reason") == "max_output_tokens"
            if status != "completed" and not truncated:
                raise ValueError(f"response status {status}")
        except (KeyError, TypeError, ValueError):
            self.blocked = True
            raise LiveStop("unexpected billing response; run stopped") from None
        upper = (inp * Decimal(m["input_usd_per_million"]) + out * Decimal(m["output_usd_per_million"])) / MILLION
        estimate = ((inp - cached) * Decimal(m["input_usd_per_million"]) + cached * Decimal(m["cached_input_usd_per_million"])
                    + out * Decimal(m["output_usd_per_million"])) / MILLION
        self.upper += upper; self.estimate += estimate
        entry = {"call": len(self.entries) + 1, "model": model, "input_tokens": inp, "output_tokens": out, "cached_tokens": cached,
                 "upper_cost_usd": str(upper), "estimated_cost_usd": str(estimate), "response_status": status, "response_id": response.get("id")}
        self.entries.append(entry)
        return entry

    def summary(self):
        return {"calls": len(self.entries), "upper_cost_usd": str(self.upper), "estimated_cost_usd": str(self.estimate),
                "cap_usd": str(self.cap), "blocked": self.blocked}


def quote(pricing, episodes, seeds, policies, safety=2.0):
    """Expected upper cost from the paper's live run (calls per episode and mean cost per call), times a safety factor."""
    ref = pricing["paper_live_run"]
    n = episodes * len(seeds) * len(policies)
    calls = n * ref["calls_per_episode"]
    expected = calls * float(ref["mean_upper_cost_per_call_usd"])
    return {"episodes": n, "expected_calls": round(calls), "expected_upper_usd": round(expected, 4), "suggested_cap_usd": round(expected * safety, 3)}


def build_request(pricing, model, messages):
    m = pricing["models"][model]
    return {**m.get("request_params", {}), "model": model, "input": messages, "store": False,
            "max_output_tokens": m["max_output_tokens"], "service_tier": m["service_tier"]}


class HttpLiveExecutor:
    """One real call per invocation through the session ledger, then grading over HTTP. Never retries."""

    def __init__(self, api_key, pricing, ledger, tasks, base_models, grader_url, grader_token="", session=None,
                 api_url=None, timeout=(10, 120), grade_timeout=260):
        self._key = api_key; self.pricing = pricing; self.ledger = ledger; self.tasks = tasks; self.base_models = base_models
        self.grader_url = grader_url.rstrip("/"); self.grader_token = grader_token
        self.api_url = api_url or pricing["api"]; self.timeout = timeout; self.grade_timeout = grade_timeout
        if session is None:
            import requests
            session = requests.Session(); session.trust_env = False
        self.session = session
        self.calls = 0; self.records = []

    def grade(self, task, code):
        headers = {"X-Grader-Token": self.grader_token} if self.grader_token else {}
        r = self.session.post(self.grader_url + "/grade", json={"solution": calibrated_solution(task, code), "test": task["test"],
                                                                "entry_point": task["entry_point"]}, headers=headers, timeout=(10, self.grade_timeout))
        if r.status_code != 200:
            raise RuntimeError(f"grader_http_{r.status_code}")
        return r.json()

    def __call__(self, base, tid):
        model = self.base_models[base]; task = self.tasks[tid]
        messages = build_messages(task)
        self.ledger.admit(model, sum(len(m["content"]) for m in messages))
        body = build_request(self.pricing, model, messages)
        started = time.monotonic()
        response = self.session.post(self.api_url, json=body, headers={"Authorization": "Bearer " + self._key},
                                     timeout=self.timeout, allow_redirects=False)
        if response.status_code != 200:
            self.ledger.blocked = True                     # unknown whether we were billed: stop the run
            raise LiveStop(f"api_http_{response.status_code}")
        data = response.json()
        entry = self.ledger.settle(model, data)
        self.calls += 1
        latency = round(time.monotonic() - started, 3)
        text = "\n".join(part["text"] for item in data.get("output", []) if item.get("type") == "message"
                         for part in item.get("content", []) if part.get("type") == "output_text")
        code = extract_code(text)
        record = {"cost": float(entry["upper_cost_usd"]), "call": self.calls, "model": model, "task_id": tid,
                  "upper_cost_usd": entry["upper_cost_usd"], "estimated_cost_usd": entry["estimated_cost_usd"],
                  "input_tokens": entry["input_tokens"], "output_tokens": entry["output_tokens"],
                  "response_status": entry["response_status"], "latency_seconds": latency, "fenced": code != text}
        try:
            graded = self.grade(task, code)
            status = graded.get("status", "grader_error"); record["grade_seconds"] = graded.get("seconds")
        except Exception as error:                           # grader failure is a technical non-outcome
            status = "grader_error"; record["grader_error"] = type(error).__name__
        record.update(success=status == "pass", grade_status=status)
        self.records.append(record)
        return record


class LiveWorld(S.World):
    """Replay world for declarations, graph and profiles; tasks and outcomes come from the live pool and real calls."""

    def __init__(self, cfg, cmap, seed, live_manifest, executor):
        super().__init__(cfg, cmap, seed)
        self.live_domain = {tid: rec["drawn_for_domain"] for tid, rec in live_manifest["tasks"].items()}
        self.pool = list(live_manifest["task_order"])
        self.by_domain = {d: [t for t in self.pool if self.live_domain[t] == d] for d in S.DOMAINS}
        self.domain.update(self.live_domain)
        self.executor = executor

    def execute(self, worker_id, domain):
        a = self.agents[worker_id]; a.calls += 1
        if a.profile == "specialist" and domain not in a.declared:
            return {"success": False, "cost": 0.0, "refused": True, "task": None, "effect": "refused"}
        if not self.by_domain[domain]:
            return {"success": False, "cost": 0.0, "refused": True, "task": None, "effect": "refused"}
        task = self.task_rng[worker_id].choice(self.by_domain[domain])
        if a.profile == "impostor":
            return {"success": False, "cost": 0.0, "refused": False, "task": task, "effect": "impostor"}
        if self.lazy_phase(a) and self.lazy_rng[worker_id].random() < a.lazy_p:
            return {"success": False, "cost": 0.0, "refused": False, "task": task, "effect": "lazy"}
        res = self.executor(a.base, task)
        return {"success": res["success"], "cost": res["cost"], "refused": False, "task": task, "effect": "call", "call": res}


def run_live_policy(policy, cfg, cmap, seed, live_manifest, executor, episodes, on_episode=None):
    """One policy for one seed. `on_episode(record, stats)` is called after every episode. Stops cleanly on LiveStop."""
    if policy not in LIVE_POLICIES:
        raise ValueError(f"policy not supported live: {policy}")
    world = LiveWorld(cfg, cmap, seed, live_manifest, executor)
    sched = random.Random(f"schedule:{seed}"); choice = random.Random(f"policy:{seed}:{policy}")
    social = cfg["social"]; trust = {a: S.Trust(social) for a in world.ids}
    use_trust = policy in S.SOCIAL_POLICIES; use_ref = policy == "social"
    befriend = use_trust and policy != "social_nobefriend" and social["befriend_on_success"]
    stats = {"policy": policy, "seed": seed, "episodes": 0, "success": 0, "cost": 0.0, "messages": 0, "refusals": 0, "calls": 0,
             "grade_statuses": defaultdict(int), "grader_errors": 0, "by_window": [], "by_profile": defaultdict(lambda: {"selected": 0, "success": 0}),
             "by_base": defaultdict(lambda: {"calls": 0, "success": 0}), "status": "running", "records": []}
    window = {"n": 0, "success": 0, "unreliable": 0, "calls": 0}
    try:
        for e in range(episodes):
            world.episode = e
            requester = sched.choice(world.ids)
            d = world.domain[sched.choice(world.pool)]
            direct, reach = world.reachable(requester, social["radius"]); messages = 2 * len(direct)
            cands = sorted(reach); out = None; worker = None; refusals_here = 0
            for attempt in range(social["max_reselections"] + 1):
                if not cands:
                    break
                declared = [w for w in cands if d in world.agents[w].declared]
                if policy == "random":
                    worker = choice.choice(cands)
                elif policy == "declared":
                    worker = choice.choice(declared or cands)
                else:
                    scores = {w: S.social_score(requester, w, d, world, trust, direct, social, use_ref) for w in cands}
                    if choice.random() < social["epsilon"]:
                        worker = choice.choice(cands)
                    else:
                        top = max(scores.values()); worker = choice.choice([w for w in cands if scores[w] == top])
                out = world.execute(worker, d)
                if not out["refused"]:
                    break
                stats["refusals"] += 1; messages += 1; refusals_here += 1
                if use_trust:
                    trust[requester].note_refusal(worker, d)
                cands = [w for w in cands if w != worker]
            if out is None or out["refused"]:
                out = {"success": False, "cost": 0.0, "refused": True, "task": None, "effect": "unfilled"}; worker = worker or ""
            if use_trust and worker and not out["refused"]:
                trust[requester].update(worker, d, out["success"])
                if out["success"] and befriend:
                    world.befriend(requester, worker)
            prof = world.agents[worker].profile if worker else "none"
            unreliable = bool(worker) and world.unreliable_now(worker)   # metric only, after the decision
            call = out.get("call")
            if call is not None:
                stats["grade_statuses"][call["grade_status"]] += 1
                stats["grader_errors"] += call["grade_status"] == "grader_error"
                b = world.agents[worker].base
                stats["by_base"][b]["calls"] += 1; stats["by_base"][b]["success"] += call["success"]
            stats["episodes"] += 1; stats["success"] += out["success"]; stats["cost"] += out["cost"]; stats["messages"] += messages
            stats["calls"] += call is not None
            stats["by_profile"][prof]["selected"] += 1; stats["by_profile"][prof]["success"] += out["success"]
            window["n"] += 1; window["success"] += out["success"]; window["unreliable"] += unreliable; window["calls"] += call is not None
            record = {"policy": policy, "seed": seed, "e": e, "requester": requester, "worker": worker, "profile": prof, "domain": d,
                      "task": out["task"], "effect": out["effect"], "success": bool(out["success"]), "cost": out["cost"], "messages": messages,
                      "direct": len(direct), "refusals": refusals_here, "unreliable": unreliable}
            if call:
                record.update({k: call.get(k) for k in ("call", "model", "upper_cost_usd", "input_tokens", "output_tokens", "response_status",
                                                        "latency_seconds", "grade_status", "grade_seconds", "fenced")})
            stats["records"].append(record)
            if on_episode:
                on_episode(record, stats)
            if window["n"] == 100:
                stats["by_window"].append(window); window = {"n": 0, "success": 0, "unreliable": 0, "calls": 0}
            if call is not None and call["grade_status"] == "grader_error":
                raise LiveStop("grader error: the paid call is recorded, the run stops")
        stats["status"] = "completed"
    except CapStop as stop:
        stats["status"] = "cap_stop"; stats["message"] = str(stop)
    except LiveStop as stop:
        stats["status"] = "live_stop"; stats["message"] = str(stop)
    if window["n"]:
        stats["by_window"].append(window)
    stats["by_profile"] = dict(stats["by_profile"]); stats["grade_statuses"] = dict(stats["grade_statuses"]); stats["by_base"] = dict(stats["by_base"])
    stats["final_degree_mean"] = round(sum(len(v) for v in world.friends.values()) / len(world.ids), 3)
    stats["success_rate"] = stats["success"] / stats["episodes"] if stats["episodes"] else None
    return stats


def run_live(cfg, cmap, live_manifest, executor, episodes, seeds, policies, on_episode=None):
    """Seeds outer, policies inner (complete pairs first if the cap stops the run). Returns the results dict."""
    results = {"prompt_version": PROMPT_VERSION, "episodes_per_run": episodes, "seeds": list(seeds), "policies": list(policies),
               "population": cfg.get("name") or cfg.get("preset"), "runs": [], "status": "running"}
    for seed in seeds:
        for policy in policies:
            stats = run_live_policy(policy, cfg, cmap, seed, live_manifest, executor, episodes, on_episode)
            results["runs"].append(stats)
            if stats["status"] != "completed":
                results["status"] = stats["status"]; results["message"] = stats.get("message", "")
                results["ledger"] = executor.ledger.summary()
                return results
    results["status"] = "completed"; results["ledger"] = executor.ledger.summary()
    return results


def pooled(results):
    """Per policy over all seeds: episodes, success rate, calls, unreliable share by window; per base model live rates."""
    out = {"policies": {}, "by_base": defaultdict(lambda: {"calls": 0, "success": 0})}
    for r in results["runs"]:
        p = out["policies"].setdefault(r["policy"], {"episodes": 0, "success": 0, "calls": 0, "cost_usd": 0.0, "windows": []})
        p["episodes"] += r["episodes"]; p["success"] += r["success"]; p["calls"] += r["calls"]; p["cost_usd"] += r["cost"]
        for i, w in enumerate(r["by_window"]):
            while len(p["windows"]) <= i:
                p["windows"].append({"n": 0, "success": 0, "unreliable": 0})
            for k in ("n", "success", "unreliable"):
                p["windows"][i][k] += w[k]
        for b, v in r["by_base"].items():
            out["by_base"][b]["calls"] += v["calls"]; out["by_base"][b]["success"] += v["success"]
    for p in out["policies"].values():
        p["success_rate"] = p["success"] / p["episodes"] if p["episodes"] else None
        p["success_by_window"] = [w["success"] / w["n"] for w in p["windows"] if w["n"]]
        p["unreliable_share_by_window"] = [w["unreliable"] / w["n"] for w in p["windows"] if w["n"]]
    out["by_base"] = {b: {**v, "live_rate": v["success"] / v["calls"] if v["calls"] else None} for b, v in out["by_base"].items()}
    return out
