"""Experiments: creation from presets, permissions, versions, duplication, archiving, runs, diffs and legacy import."""
import copy
import json

import pytest

from socialmas import access as A
from socialmas import data as D
from socialmas.experiment import run_experiment
from socialmas.experiments import ExperimentError, Experiments

CMAP = D.load_competence_map()


def lab(tmp_path):
    acc = A.Access(data_dir=tmp_path / "data", env={"SOCIALMAS_ADMIN_USER": "boot", "SOCIALMAS_ADMIN_PASSWORD": "bootstrap-secret-1"})
    boot = acc.authenticate("boot", "bootstrap-secret-1")
    acc.upsert_user(boot, "marco", "Marco", "sysadmin", password="temporary-pass-1")
    marco = acc.authenticate("marco", "temporary-pass-1"); acc.change_password(marco, "temporary-pass-1", "my-own-password-1"); marco = acc.principal_for("marco")
    acc.upsert_user(marco, "iera", "Antonio Iera", "researcher", password="another-temp-1")
    acc.change_password(acc.authenticate("iera", "another-temp-1"), "another-temp-1", "iera-own-password")
    acc.upsert_user(marco, "rev", "Reviewer", "reviewer", password="reviewer-temp-1")
    acc.change_password(acc.authenticate("rev", "reviewer-temp-1"), "reviewer-temp-1", "reviewer-own-pass")
    return acc, Experiments(acc), marco, acc.principal_for("iera"), acc.principal_for("rev")


def test_create_from_preset_list_and_permissions(tmp_path):
    acc, ex, marco, iera, rev = lab(tmp_path)
    e = ex.from_preset(iera, "paper-v2", name="v2 with a twist")
    assert e["owner"] == "iera" and e["origin_preset"] == "paper-v2" and e["config_version"] == 1 and "preset" not in e["config"]
    assert [x["id"] for x in ex.list()] == [e["id"]]
    r = ex.from_preset(rev, "paper-v3-liars")                        # reviewers can create their own experiments
    assert r["owner"] == "rev" and len(ex.list()) == 2
    with pytest.raises(ExperimentError):
        ex.rename(rev, e["id"], "hijack")                            # not the owner
    ex.rename(iera, e["id"], "v2, radius 1")
    ex.rename(marco, e["id"], "v2, radius 1 (admin touch)")          # administrators may
    assert ex.get(e["id"])["name"].startswith("v2, radius 1")
    with pytest.raises(ExperimentError):
        ex.from_preset(iera, "nope")
    with pytest.raises(ExperimentError):
        ex.create(A.Principal("boot", "Boot", "sysadmin", legacy=True), "x", D.load_preset("paper-v2"))


def test_update_config_versions_validation_and_diff(tmp_path):
    acc, ex, marco, iera, rev = lab(tmp_path)
    e = ex.from_preset(iera, "paper-v2")
    assert ex.diff_from_origin(e) == []
    cfg = copy.deepcopy(e["config"]); cfg["social"]["radius"] = 1; cfg["seeds"] = 5
    e2 = ex.update_config(iera, e["id"], cfg)
    assert e2["config_version"] == 2 and e2["config"]["social"]["radius"] == 1
    assert ex.update_config(iera, e["id"], cfg)["config_version"] == 2          # no change, no new version
    diffs = ex.diff_from_origin(e2)
    assert ("seeds", 20, 5) in diffs and ("social.radius", 2, 1) in diffs and len(diffs) == 2
    cfg["agents"].append({"id": "A12", "base": "nano", "profile": "liar"})
    e3 = ex.update_config(iera, e["id"], cfg)
    assert any(d[0] == "agents" and "12 agents" in d[2] for d in ex.diff_from_origin(e3))
    bad = copy.deepcopy(cfg); bad["episodes"] = 250
    with pytest.raises(ExperimentError):
        ex.update_config(iera, e["id"], bad)
    with pytest.raises(ExperimentError):
        ex.update_config(rev, e["id"], cfg)


def test_duplicate_archive_and_notes(tmp_path):
    acc, ex, marco, iera, rev = lab(tmp_path)
    e = ex.from_preset(iera, "paper-v3-noliars", notes="twin")
    d = ex.duplicate(rev, e["id"])
    assert d["owner"] == "rev" and d["origin_preset"] == "paper-v3-noliars" and d["config"] == e["config"] and d["notes"] == "twin"
    ex.set_notes(rev, d["id"], "my copy")
    assert ex.get(d["id"])["notes"] == "my copy"
    ex.archive(iera, e["id"])
    assert [x["id"] for x in ex.list()] == [d["id"]] and len(ex.list(include_archived=True)) == 2
    ex.archive(iera, e["id"], archived=False)
    assert len(ex.list()) == 2


def test_runs_are_recorded_loaded_and_matched_to_config(tmp_path):
    acc, ex, marco, iera, rev = lab(tmp_path)
    e = ex.from_preset(iera, "paper-v2")
    cfg = copy.deepcopy(e["config"]); cfg["seeds"] = 1; cfg["episodes"] = 300; cfg["policies"] = ["random", "social"]; cfg["analysis"]["bootstrap_resamples"] = 200
    e = ex.update_config(iera, e["id"], cfg)
    res = run_experiment(e["config"], CMAP); res["elapsed_seconds"] = 0.4
    rid = ex.record_run(iera, e["id"], "replay", res)
    runs = ex.runs(e["id"])
    assert len(runs) == 1 and runs[0]["kind"] == "replay" and runs[0]["user"] == "iera" and set(runs[0]["summary"]["policies"]) == {"random", "social"}
    assert ex.current_run_matches(ex.get(e["id"]), runs[0])
    loaded = ex.load_run(rid)
    assert loaded["policies"]["social"]["success_rate"] == res["policies"]["social"]["success_rate"]
    cfg["social"]["epsilon"] = 0.2; e = ex.update_config(iera, e["id"], cfg)
    assert not ex.current_run_matches(e, ex.runs(e["id"])[0])
    live = {"status": "completed", "key_source": "shared", "episodes_per_run": 100, "seeds": [0], "config": e["config"],
            "ledger": {"calls": 171, "upper_cost_usd": "0.0578"}, "runs": [{"policy": "random", "episodes": 100, "success": 31}, {"policy": "social", "episodes": 100, "success": 42}]}
    ex.record_run(marco, e["id"], "live", live)
    lr = ex.runs(e["id"], kind="live")
    assert len(lr) == 1 and lr[0]["summary"]["calls"] == 171 and lr[0]["summary"]["policies"]["social"] == 0.42
    assert len(ex.runs(e["id"])) == 2
    with pytest.raises(ExperimentError):
        ex.record_run(marco, "nope", "replay", res)
    actions = [x["action"] for x in acc.events()]
    assert "run.recorded" in actions and "experiment.created" in actions and "experiment.updated" in actions


def test_legacy_live_runs_are_imported_once(tmp_path):
    acc, ex, marco, iera, rev = lab(tmp_path)
    legacy = acc.data_dir / "live-runs"; legacy.mkdir()
    (legacy / "20260928T161957-marco.json").write_text(json.dumps({"status": "completed", "user": "marco", "key_source": "shared", "population": "population-v2",
                                                                    "episodes_per_run": 100, "seeds": [0], "ledger": {"calls": 171, "upper_cost_usd": "0.0578303"},
                                                                    "runs": [{"policy": "random", "episodes": 100, "success": 31}, {"policy": "social", "episodes": 100, "success": 42}]}))
    (legacy / "20260928T170000-ghost.json").write_text(json.dumps({"status": "completed", "user": "ghost", "population": "population-v2", "runs": [], "ledger": {}}))
    assert ex.import_legacy_live_runs() == 1
    exps = ex.list()
    assert len(exps) == 1 and exps[0]["id"] == "legacy-paper-v2-marco" and exps[0]["owner"] == "marco" and exps[0]["origin_preset"] == "paper-v2"
    runs = ex.runs(exps[0]["id"])
    assert len(runs) == 1 and runs[0]["kind"] == "live" and runs[0]["summary"]["calls"] == 171
    assert ex.import_legacy_live_runs() == 0 and len(ex.runs(exps[0]["id"])) == 1
    assert ex.load_run(runs[0]["id"])["ledger"]["calls"] == 171
