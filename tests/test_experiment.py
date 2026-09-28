"""Runner, validation, presets, reference comparison and report tables."""
import copy
import json

import pytest

from socialmas import data as D
from socialmas.experiment import compare_to_reference, config_hash, estimate_seconds, rules_signature, run_experiment, validate_config
from socialmas.report import decline_frame, differences_frame, headline_frame, markdown_report, selection_frame, windows_frame

CMAP = D.load_competence_map()


def small(name="paper-v2", episodes=600, seeds=2, policies=None):
    c = D.load_preset(name); c["episodes"] = episodes; c["seeds"] = seeds
    c["analysis"]["bootstrap_resamples"] = 500
    if policies: c["policies"] = policies
    return c


def test_presets_load_apply_overrides_and_have_references():
    names = D.preset_names()
    assert names[0] == "paper-v2" and len(names) == 6
    assert D.load_preset("paper-v2-radius1")["social"]["radius"] == 1
    assert D.load_preset("paper-v2-pool174")["task_pool"]["rule"] == "discriminating"
    assert D.load_preset("paper-v2-degree2-posthoc")["graph"]["degree"] == 2
    for n in names:
        ref = D.load_reference(n)
        assert ref and ref["policies"] and ref["config"]["seeds"] == 20
        assert not validate_config(D.load_preset(n), CMAP)


def test_bundled_data_holds_no_benchmark_content():
    for tid, row in CMAP["tasks"].items():
        assert set(row) == {"domains", "drawn_for_domain", "outcomes"}
    for name in ("bcb-pool.json", "bcb-live-pool.json"):
        pool = D.load_pool(name)
        for tid, row in pool["tasks"].items():
            assert set(row) <= {"task_id", "drawn_for_domain", "domains", "libs"}


def test_validate_config_reports_problems():
    c = small()
    c["episodes"] = 650; c["seeds"] = 0; c["agents"][0]["profile"] = "wizard"; c["agents"][1]["id"] = c["agents"][2]["id"]
    c["policies"].append("telepathy"); c["social"]["radius"] = 3; c["graph"]["degree"] = 40
    problems = validate_config(c, CMAP)
    joined = " ".join(problems)
    for word in ("episodes", "seeds", "profile", "unique", "telepathy", "radius", "degree"):
        assert word in joined
    with pytest.raises(ValueError):
        run_experiment(c, CMAP)


def test_run_experiment_structure_and_pairs():
    c = small(policies=["random", "declared", "social_noref", "social"])
    calls = []
    r = run_experiment(c, CMAP, progress=lambda d, t, p, s: calls.append((d, t, p, s)))
    assert calls[-1][0] == calls[-1][1] == 8
    assert set(r["policies"]) == {"random", "declared", "social_noref", "social"}
    assert "social - random" in r["paired_differences"] and "social - best_fixed" not in r["paired_differences"]
    assert len(r["policies"]["social"]["success_by_window"]) == 6
    assert r["ground_truth"]["pool_size"] == 350 and r["config_sha256"] == config_hash(c)
    assert r["competence_map_sha256"] == D.load_reference("paper-v2")["competence_map_sha256"]
    assert "_note" in r["unreliable_decline"] and r["unreliable_decline"]["social"]["n"] == 2


def test_run_reproduces_reference_per_seed_and_compare_flags_it():
    c = D.load_preset("paper-v2"); c["seeds"] = 1; c["policies"] = ["random", "social"]; c["analysis"]["bootstrap_resamples"] = 200
    r = run_experiment(c, CMAP)
    cmp = compare_to_reference(r, D.load_reference("paper-v2"))
    assert cmp["social"]["exact_on_shared_seeds"] and cmp["random"]["exact_on_shared_seeds"] and cmp["social"]["shared_seeds"] == 1
    c2 = copy.deepcopy(c); c2["social"]["epsilon"] = 0.3
    r2 = run_experiment(c2, CMAP)
    assert not compare_to_reference(r2, D.load_reference("paper-v2"))["social"]["exact_on_shared_seeds"]


def test_custom_population_runs():
    c = small(policies=["random", "social"])
    c["agents"] = [{"id": f"C{i:02d}", "base": "mini" if i % 2 else "nano", "profile": "honest"} for i in range(6)]
    c["agents"].append({"id": "C06", "base": "nano", "profile": "impostor"})
    c["agents"].append({"id": "C07", "base": "mini", "profile": "specialist", "domains": ["System"]})
    c["graph"]["degree"] = 2; c["best_fixed_agents"] = ["C01"]
    r = run_experiment(c, CMAP)
    assert r["policies"]["social"]["success_rate"]["mean"] > 0
    assert set(r["ground_truth"]["declarations"]) == {a["id"] for a in c["agents"]}


def test_report_frames_and_markdown_on_reference():
    ref = D.load_reference("paper-v3-liars")
    h = headline_frame(ref); assert len(h) == 8 and {"policy", "success", "messages_per_episode"} <= set(h.columns)
    d = differences_frame(ref); assert "social_refcheck - social" in set(d["comparison"])
    assert len(windows_frame(ref)) == 8 * 30 and set(selection_frame(ref)["profile"]) >= {"honest", "liar"}
    assert len(decline_frame(ref)) == 8
    md = markdown_report(ref)
    assert "| `social` |" in md and "Comparison" in md and "evaluation only" in md


def test_estimate_is_monotone():
    a = small(); b = small(name="paper-v3-liars")
    assert 0 < estimate_seconds(a) < estimate_seconds(b)


def test_rules_signature_matches_presets_to_their_references_and_ignores_run_settings():
    for n in D.preset_names():
        c = D.load_preset(n); ref = D.load_reference(n)
        assert rules_signature(c) == rules_signature(ref["config"]), n
        c["seeds"] = 1; c["episodes"] = 600; c["policies"] = ["random"]; c["social"]["prior_alpha"] = 1.0
        assert rules_signature(c) == rules_signature(ref["config"]), n
        c["social"]["epsilon"] = 0.2
        assert rules_signature(c) != rules_signature(ref["config"]), n
    assert rules_signature(D.load_preset("paper-v2")) != rules_signature(D.load_preset("paper-v2-radius1"))
