"""Engine tests transported from the research repository: mechanics, determinism, pairing, no ground-truth leakage.
They run against the bundled data, so the package must reproduce the pre-registered numbers exactly."""
import copy
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import socialmas.sim as S
from socialmas import data as D

CFG = D.load_preset("paper-v2")
CMAP = D.load_map_for(CFG)
CFG3 = D.load_preset("paper-v3-liars")
SIM_SRC = Path(S.__file__)


def small(episodes=600, seeds=2, pool=None):
    c = copy.deepcopy(CFG); c["episodes"] = episodes; c["seeds"] = seeds
    if pool: c["task_pool"]["rule"] = pool
    return c


def test_pool_rules_and_hard_stratum():
    w = S.World(CFG, CMAP, 0); assert len(w.pool) == 350 and len(w.hard) == 176
    w2 = S.World(small(pool="discriminating"), CMAP, 0); assert len(w2.pool) == 174
    for t in w2.hard:
        assert not w2.outcome["nano"][t] and not w2.outcome["mini"][t]
    assert w2.base_rate["mini"]["Time"] > w.base_rate["mini"]["Time"]


def test_declarations_follow_profiles_from_map_rates():
    w = S.World(CFG, CMAP, 0)
    assert w.agents["A05"].declared == set(S.DOMAINS) == w.agents["A11"].declared
    assert w.agents["A08"].declared == {"System", "Computation"}
    assert w.agents["A01"].declared == set(S.DOMAINS) - {"Time"}
    assert w.agents["A03"].declared == {"Cryptography", "System", "Visualization", "General", "Computation"}
    assert w.agents["A06"].declared == w.agents["A01"].declared == w.agents["A10"].declared


def _connected(w):
    seen, stack = set(), [w.ids[0]]
    while stack:
        a = stack.pop()
        if a in seen: continue
        seen.add(a); stack.extend(w.friends[a])
    return seen == set(w.ids)


def test_graph_connected_symmetric_and_capped():
    for seed in range(20):
        w = S.World(CFG, CMAP, seed)
        assert _connected(w)
        for a in w.ids:
            assert a not in w.friends[a] and all(a in w.friends[b] for b in w.friends[a])
            assert len(w.friends[a]) <= CFG["graph"]["degree"] + 1


def test_execute_semantics_and_rates():
    w = S.World(CFG, CMAP, 1)
    out = w.execute("A08", "Network"); assert out["refused"] and out["cost"] == 0.0 and out["task"] is None
    out = w.execute("A08", "System"); assert not out["refused"] and out["success"] == w.outcome["mini"][out["task"]]
    outs = [w.execute("A11", "General") for _ in range(50)]
    assert not any(o["success"] for o in outs) and all(o["cost"] > 0 for o in outs)
    w2 = S.World(CFG, CMAP, 1)
    rate = sum(w2.execute("A01", "System")["success"] for _ in range(3000)) / 3000
    assert abs(rate - w2.base_rate["mini"]["System"]) < 0.04
    outs = [w2.execute("A07", "System") for _ in range(3000)]
    assert abs(sum(o["success"] for o in outs) / 3000 - 0.5 * w2.base_rate["mini"]["System"]) < 0.04
    w3 = S.World(CFG, CMAP, 1); w3.episode = 0
    r0 = sum(w3.execute("A10", "System")["success"] for _ in range(800)) / 800
    w3.episode = CFG["agents"][9]["phase_length"]
    r1 = sum(w3.execute("A10", "System")["success"] for _ in range(800)) / 800
    assert r0 > r1 + 0.2


def test_true_rates_and_unstable_share():
    w = S.World(CFG, CMAP, 0)
    assert w.true_rate("A11", "System") == 0.0 and w.true_rate("A08", "Network") == 0.0
    assert abs(w.true_rate("A06", "System") - 0.7 * w.base_rate["mini"]["System"]) < 1e-9
    assert abs(w.lazy_share(w.agents["A10"]) - 0.5) < 1e-9
    c = small(episodes=1000); c["agents"][9]["phase_length"] = 150
    w2 = S.World(c, CMAP, 0); assert abs(w2.lazy_share(w2.agents["A10"]) - 0.45) < 1e-9


def test_trust_mechanics():
    t = S.Trust(CFG["social"])
    assert t.overall_estimate("w") is None and t.evidence("w", "System") == (0, 0)
    for ok in (True, True, False):
        t.update("w", "System", ok)
    assert abs(t.overall_estimate("w") - 3 / 5) < 1e-9
    assert t.evidence("w", "Network") == (2, 1)
    assert t.evidence("w", "System") == (2, 1)
    t.note_refusal("w", "Time"); assert t.n("w") == 3
    t2 = S.Trust(CFG["social"]); t2.update("v", "Time", False); t2.update("v", "Time", False)
    assert t2.overall_estimate("v") < 0.5 < t.overall_estimate("w")


def test_social_score_uses_declarations_then_evidence_and_referrals():
    w = S.World(CFG, CMAP, 0); soc = CFG["social"]
    trust = {a: S.Trust(soc) for a in w.ids}
    r = "A01"; direct = w.friends[r]
    fr, target = next((f, x) for f in sorted(direct) for x in sorted(w.friends[f])
                      if x != r and "System" in w.agents[x].declared)
    base = S.social_score(r, target, "System", w, trust, direct, soc, True)
    assert base in (soc["declared_prior"], soc["undeclared_prior"])
    for _ in range(4):
        trust[fr].update(target, "System", False)
    with_ref = S.social_score(r, target, "System", w, trust, direct, soc, True)
    no_ref = S.social_score(r, target, "System", w, trust, direct, soc, False)
    assert with_ref < base and no_ref == base
    trust[r].update(target, "System", True); trust[r].update(target, "System", True)
    assert S.social_score(r, target, "System", w, trust, direct, soc, False) > 0.5


def test_schedule_identical_across_policies_and_deterministic():
    c = small()
    with tempfile.TemporaryDirectory() as tmp:
        logs = {}
        for pol in ("random", "social", "oracle"):
            path = Path(tmp) / f"{pol}.jsonl"
            with open(path, "w") as f:
                S.run_policy(pol, c, CMAP, 0, f)
            logs[pol] = [(json.loads(l)["requester"], json.loads(l)["domain"]) for l in open(path)]
        assert logs["random"] == logs["social"] == logs["oracle"]
    a, _ = S.run_policy("social", c, CMAP, 0); b, _ = S.run_policy("social", c, CMAP, 0)
    assert (a["success"], a["cost"], a["messages"]) == (b["success"], b["cost"], b["messages"])
    d, _ = S.run_policy("social", c, CMAP, 1); assert (d["success"], d["cost"]) != (a["success"], a["cost"])


def test_reproducible_across_hash_seeds():
    code = ("import socialmas.sim as S; from socialmas import data as D; c=D.load_preset('paper-v2'); c['episodes']=600; "
            "m=D.load_map_for(c); s,_=S.run_policy('social',c,m,3); print(s['success'], round(s['cost'],8))")
    outs = set()
    for hs in ("0", "1", "12345"):
        env = {**os.environ, "PYTHONHASHSEED": hs}
        outs.add(subprocess.check_output([sys.executable, "-c", code], env=env, text=True).strip())
    assert len(outs) == 1, outs


def test_refusal_memory_and_like_window():
    w = S.World(CFG, CMAP, 0); soc = CFG["social"]; trust = {a: S.Trust(soc) for a in w.ids}
    r = "A02"; direct = w.friends[r]
    for _ in range(5):
        trust[r].update("A08", "System", True)
    assert S.social_score(r, "A08", "System", w, trust, direct, soc, False) > 0.8
    trust[r].note_refusal("A08", "Network")
    assert S.social_score(r, "A08", "Network", w, trust, direct, soc, False) == soc["undeclared_prior"]
    assert S.last_like_window(CFG) == 26


def test_refusal_reselects_with_extra_message():
    c = small(episodes=300, seeds=1)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "log.jsonl"
        with open(path, "w") as f:
            s, _ = S.run_policy("random", c, CMAP, 0, f)
        rows = [json.loads(l) for l in open(path)]
    assert s["refusals"] > 0 and s["reselect_failures"] == 0
    assert any(r["refusals"] > 0 for r in rows)
    assert all(r["messages"] == 2 * r["direct"] + r["refusals"] for r in rows)


def test_best_fixed_uses_clone_when_fixed_agent_requests():
    c = small(episodes=300, seeds=1)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "log.jsonl"
        with open(path, "w") as f:
            S.run_policy("best_fixed", c, CMAP, 0, f)
        rows = [json.loads(l) for l in open(path)]
    assert all(r["worker"] == ("A02" if r["requester"] == "A01" else "A01") for r in rows)


def test_policies_never_touch_ground_truth():
    src = SIM_SRC.read_text()
    body = src[src.index("def social_score"):src.index("# --- evaluation only")]
    forbidden = ("true_rate", "true_overall", "outcome[", "base_rate", "map_rate", "cost[", "unreliable_now", "lazy_phase")
    for line in body.splitlines():
        if "oracle_pick(" in line or line.rstrip().endswith("# metric only, after the decision"):
            continue
        for name in forbidden:
            assert name not in line, line


def test_paper_results_reproduce_from_bundled_data():
    """Seed 0 of the main v2 run and of the v3 runs must match the pre-registered provenance files exactly."""
    ref2 = D.load_reference("paper-v2")
    for policy in ("social", "random", "best_fixed"):
        stats, _ = S.run_policy(policy, CFG, CMAP, 0)
        assert abs(stats["success"] / stats["episodes"] - ref2["policies"][policy]["per_seed_success_rate"][0]) < 1e-9
    ref3 = D.load_reference("paper-v3-liars")
    for policy in ("social", "social_refcheck"):
        stats, _ = S.run_policy(policy, CFG3, CMAP, 0)
        assert abs(stats["success"] / stats["episodes"] - ref3["policies"][policy]["per_seed_success_rate"][0]) < 1e-9


def test_liar_reports_amplified_inversion_but_works_honestly():
    w = S.World(CFG3, CMAP, 0); soc = CFG3["social"]; trust = {a: S.Trust(soc) for a in w.ids}
    liar = next(a for a in w.ids if w.agents[a].profile == "liar"); honest = "B01"; bad = next(a for a in w.ids if w.agents[a].profile == "impostor")
    r = next(x for x in w.ids if x not in (liar, honest, bad))
    for a, b in ((r, liar), (liar, honest), (liar, bad)):
        w.friends[a].add(b); w.friends[b].add(a)
    for _ in range(4):
        trust[liar].update(honest, "System", True)
        trust[liar].update(bad, "System", False)
    assert S.referral_opinions(r, honest, "System", w, trust, w.friends[r]) == [(liar, 0, 6)]
    assert S.referral_opinions(r, bad, "System", w, trust, w.friends[r]) == [(liar, 6, 0)]
    assert w.report("B01", bad, "System", trust) == (0, 0)
    assert w.true_rate(liar, "System") == w.base_rate["nano"]["System"]
    ok = sum(w.execute(liar, "System")["success"] for _ in range(500)) / 500
    assert abs(ok - w.base_rate["nano"]["System"]) < 0.08


def test_refcheck_scores_reports_against_own_posterior_once_per_pair():
    t = S.Trust(CFG3["social"])
    assert t.referral_weight("x") == 0.5
    for _ in range(6):
        t.note_referral("liar", 0.05, 0.45)
        t.note_referral("good", 0.40, 0.45)
    assert t.referral_weight("liar") < 0.15 < 0.85 < t.referral_weight("good")
    c = copy.deepcopy(CFG3); c["episodes"] = 900; c["seeds"] = 1
    stats, world = S.run_policy("social_refcheck", c, CMAP, 0)
    rw = stats["calibration"]["referral_weight_by_referrer"]
    assert rw["liar"]["n"] > 0 and rw["honest_referrer"]["n"] > 0 and rw["liar"]["mean"] < rw["honest_referrer"]["mean"]


def test_v3_graphs_connected_and_capped():
    for seed in range(20):
        w = S.World(CFG3, CMAP, seed)
        assert _connected(w) and all(len(w.friends[a]) <= CFG3["graph"]["degree"] + 1 for a in w.ids)


def test_social_refcheck_runs_and_is_deterministic_without_profile_reads():
    c = copy.deepcopy(CFG3); c["episodes"] = 600; c["seeds"] = 1
    a, _ = S.run_policy("social_refcheck", c, CMAP, 0); b, _ = S.run_policy("social_refcheck", c, CMAP, 0)
    assert a["success"] == b["success"] and a["episodes"] == 600
    src = SIM_SRC.read_text()
    body = src[src.index("def referral_opinions"):src.index("# --- evaluation only")]
    for line in body.splitlines():
        if "oracle_pick(" in line or line.rstrip().endswith("# metric only, after the decision"):
            continue
        for name in ("true_rate", "true_overall", "outcome[", "base_rate", "map_rate", "cost[", "unreliable_now", "lazy_phase",
                     ".liar", ".profile"):
            assert name not in line, line
