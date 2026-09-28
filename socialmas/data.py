"""Bundled data: competence map, pool manifests, paper presets and pre-registered reference results.

Nothing here contains benchmark content: the competence map holds task identifiers, the domain each task was drawn
for, and per-model outcomes (pass/fail, cost, tokens); the pool manifests hold identifiers, domains and library
names. Prompts, tests and canonical solutions of BigCodeBench are never redistributed."""
import copy
import json
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"
PRESET_DIR = DATA_DIR / "presets"
REFERENCE_DIR = DATA_DIR / "reference"

# Paper presets: base configuration, overrides applied on top of it, and the pre-registered results they reproduce.
PRESETS = {
    "paper-v2": {
        "label": "Paper v2: 11 agents, 350 tasks, radius 2 (main run)",
        "config": "population-v2.json", "overrides": {}, "reference": "social-v2-results.json",
        "description": "Main pre-registered run: eleven agents (honest, lazy, boaster, impostor, specialists, unstable), "
                       "random connected graph of degree 3, discovery radius 2, all 350 tasks, seven policies, 20 seeds, "
                       "3,000 episodes per seed and policy."},
    "paper-v2-radius1": {
        "label": "Paper v2, radius 1 (direct contacts only)",
        "config": "population-v2.json", "overrides": {"social": {"radius": 1}}, "reference": "social-v2-radius1-results.json",
        "description": "Pre-registered variant: candidates are the requester's direct contacts only."},
    "paper-v2-pool174": {
        "label": "Paper v2, 174 solvable tasks (secondary run)",
        "config": "population-v2.json", "overrides": {"task_pool": {"rule": "discriminating"}},
        "reference": "social-v2-pool174-results.json",
        "description": "Pre-registered secondary run on the 174 tasks passed by at least one base model."},
    "paper-v2-degree2-posthoc": {
        "label": "Paper v2, initial degree 2 (post-hoc variant)",
        "config": "population-v2.json", "overrides": {"graph": {"degree": 2}}, "reference": "social-v2-degree2-posthoc-results.json",
        "description": "Declared post-hoc: two initial contacts per agent instead of three, radius 2."},
    "paper-v3-liars": {
        "label": "Paper v3: 30 agents, sparse graph, 4 lying referrers",
        "config": "population-v3-liars.json", "overrides": {}, "reference": "social-v3-liars-results.json",
        "description": "Pre-registered v3 run: thirty agents, degree 2, radius 2, four honest workers that lie when asked "
                       "for opinions, eight policies including the referral-accuracy defence `social_refcheck`."},
    "paper-v3-noliars": {
        "label": "Paper v3 twin without liars",
        "config": "population-v3-noliars.json", "overrides": {}, "reference": "social-v3-noliars-results.json",
        "description": "Twin of the v3 run with the four liars replaced by honest agents; same seeds, same schedule."},
}


def _read(path):
    return json.loads(Path(path).read_text())


@lru_cache(maxsize=None)
def load_competence_map(name="bcb-competence-map.json"):
    return _read(DATA_DIR / name)


def competence_map_path(cfg):
    """Path of the competence map a configuration points to: bundled name, or an explicit path."""
    ref = cfg.get("competence_map", "bcb-competence-map.json")
    p = Path(ref)
    if p.is_absolute() and p.exists():
        return p
    if (DATA_DIR / p.name).exists():
        return DATA_DIR / p.name
    if p.exists():
        return p.resolve()
    raise FileNotFoundError(f"competence map not found: {ref}")


def load_map_for(cfg):
    return _read(competence_map_path(cfg))


def load_pool(name="bcb-pool.json"):
    return _read(DATA_DIR / name)


def preset_names():
    return list(PRESETS)


def deep_update(base, overrides):
    for k, v in overrides.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            deep_update(base[k], v)
        else:
            base[k] = copy.deepcopy(v)
    return base


def load_preset(name):
    """A fresh configuration dict for a preset (base file plus overrides)."""
    spec = PRESETS[name]
    cfg = _read(PRESET_DIR / spec["config"])
    deep_update(cfg, spec["overrides"])
    cfg["preset"] = name
    return cfg


def load_reference(name):
    """Pre-registered results for a preset, or None if the preset has none."""
    ref = PRESETS[name].get("reference")
    return _read(REFERENCE_DIR / ref) if ref else None


def load_reference_file(filename):
    return _read(REFERENCE_DIR / filename)
