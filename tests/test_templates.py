"""Personal templates: creation from presets, experiments and templates; private by default, shared on request;
owner-only edits with versions; experiments created from a template and their diff and staleness against it."""
import copy

import pytest

from socialmas import data as D
from socialmas.experiments import ExperimentError
from socialmas.templates import Templates

from test_experiments import lab


def setup(tmp_path):
    acc, ex, marco, iera, rev = lab(tmp_path)
    return ex, Templates(ex), marco, iera, rev


def test_private_by_default_then_shared(tmp_path):
    ex, tp, marco, iera, rev = setup(tmp_path)
    t = tp.from_preset(iera, "paper-v2", name="iera's base")
    assert t["owner"] == "iera" and t["shared"] is False and t["config_version"] == 1 and t["origin_kind"] == "preset"
    assert [x["id"] for x in tp.list(iera)] == [t["id"]]
    assert tp.list(rev) == [] and tp.get(rev, t["id"]) is None                  # private: invisible to others
    assert [x["id"] for x in tp.list(marco)] == [t["id"]]                         # administrators see everything
    with pytest.raises(ExperimentError):
        tp.set_shared(rev, t["id"], True)
    tp.set_shared(iera, t["id"], True)
    assert [x["id"] for x in tp.list(rev)] == [t["id"]]
    with pytest.raises(ExperimentError):
        tp.rename(rev, t["id"], "mine now")                                      # shared means usable, not editable
    own = tp.from_preset(rev, "paper-v2")                                         # like experiments, reviewers create their own
    assert own["owner"] == "rev" and own["id"] not in [x["id"] for x in tp.list(iera)]


def test_versions_duplicate_and_archive(tmp_path):
    ex, tp, marco, iera, rev = setup(tmp_path)
    t = tp.from_preset(iera, "paper-v2")
    cfg = copy.deepcopy(t["config"]); cfg["social"]["radius"] = 1
    t2 = tp.update_config(iera, t["id"], cfg)
    assert t2["config_version"] == 2 and t2["config"]["social"]["radius"] == 1
    cfg["social"]["radius"] = 1.0
    assert tp.update_config(iera, t["id"], cfg)["config_version"] == 2          # 1 and 1.0 are the same value
    bad = copy.deepcopy(cfg); bad["episodes"] = 0
    with pytest.raises(ExperimentError):
        tp.update_config(iera, t["id"], bad)
    with pytest.raises(ExperimentError):
        tp.update_config(rev, t["id"], cfg)
    d = tp.duplicate(marco, t["id"], "marco's copy")
    assert d["owner"] == "marco" and d["origin_kind"] == "template" and d["origin_ref"] == t["id"] and d["shared"] is False
    tp.archive(iera, t["id"])
    assert t["id"] not in [x["id"] for x in tp.list(iera)] and t["id"] in [x["id"] for x in tp.list(iera, include_archived=True)]
    with pytest.raises(ExperimentError):
        tp.new_experiment(iera, t["id"])


def test_experiment_from_template_diff_and_staleness(tmp_path):
    ex, tp, marco, iera, rev = setup(tmp_path)
    e0 = ex.from_preset(iera, "paper-v2")
    cfg = copy.deepcopy(e0["config"]); cfg["seeds"] = 5
    e0 = ex.update_config(iera, e0["id"], cfg)
    t = tp.from_experiment(iera, e0["id"], name="five seeds")
    assert t["origin_kind"] == "experiment" and t["config"]["seeds"] == 5
    e = tp.new_experiment(iera, t["id"], name="from template")
    assert e["origin_template"] == t["id"] and e["origin_template_version"] == 1 and e["origin_preset"] is None
    o = ex.origin(e)
    assert o["kind"] == "template" and o["copied_version"] == o["current_version"] == 1 and ex.diff_from_origin(e) == []
    cfg = copy.deepcopy(t["config"]); cfg["episodes"] = 1000
    tp.update_config(iera, t["id"], cfg)
    o = ex.origin(ex.get(e["id"]))
    assert o["current_version"] == 2 and o["copied_version"] == 1                  # the template moved on; the experiment did not
    assert ex.diff_from_origin(ex.get(e["id"])) == [("episodes", 1000, 3000)]
    dup = ex.duplicate(marco, e["id"])
    assert dup["origin_template"] == t["id"] and dup["origin_template_version"] == 1
    with pytest.raises(ExperimentError):
        tp.new_experiment(rev, t["id"])                                          # private template: reviewers cannot even see it


def test_old_database_gains_the_origin_columns(tmp_path):
    acc, ex, marco, iera, rev = lab(tmp_path)
    e = ex.from_preset(iera, "paper-v2")
    from socialmas.experiments import Experiments
    ex2 = Experiments(acc)                                                        # schema migration is idempotent
    assert ex2.get(e["id"])["origin_template"] is None and ex2.origin(e)["kind"] == "preset"


def test_private_origin_is_not_revealed_and_archived_templates_can_be_restored(tmp_path):
    ex, tp, marco, iera, rev = setup(tmp_path)
    t = tp.from_preset(iera, "paper-v2")
    e = tp.new_experiment(iera, t["id"], name="from a private template")
    cfg = t["config"]; cfg["seeds"] = 3
    tp.update_config(iera, t["id"], cfg)                                         # private edits after the copy
    hidden = ex.origin(ex.get(e["id"]), viewer=rev)
    assert hidden["private"] and hidden["name"] is None and hidden["config"] is None and hidden["current_version"] is None
    assert hidden["copied_version"] == 1 and ex.diff_from_origin(ex.get(e["id"]), viewer=rev) is None
    assert ex.origin(ex.get(e["id"]), viewer=iera)["current_version"] == 2       # the owner and administrators see it all
    assert ex.origin(ex.get(e["id"]), viewer=marco)["name"] == t["name"]
    tp.set_shared(iera, t["id"], True)
    assert not ex.origin(ex.get(e["id"]), viewer=rev)["private"]
    tp.archive(iera, t["id"])
    assert tp.list(rev, include_archived=True) == []                             # archived: only who can restore sees it
    assert [x["id"] for x in tp.list(iera, include_archived=True)] == [t["id"]]
    assert tp.archive(iera, t["id"], archived=False)["archived"] is False
    assert tp.new_experiment(rev, t["id"])["origin_template"] == t["id"]
