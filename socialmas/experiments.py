"""Experiments as persistent objects: a named configuration (population, rules, run settings) owned by a user, with the
runs made on it (replay or live) and their results. Stored in the accounts database (same SQLite file) and in result
files under the data directory. Every signed-in person sees the laboratory's experiments; only the owner and
administrators change them. The paper's presets are read-only origins from which experiments are duplicated."""
import copy
import datetime as dt
import json
import re
import uuid

from . import data as D
from .experiment import config_hash, rules_signature, validate_config

NAME_MAX = 120
COMPARE_KEYS = ("base_models", "declaration_threshold", "task_pool", "graph", "social", "analysis", "seeds", "episodes", "policies", "best_fixed_agents")
PRESET_BY_POPULATION = {"population-v2": "paper-v2", "population-v3-liars": "paper-v3-liars", "population-v3-noliars": "paper-v3-noliars"}


class ExperimentError(ValueError):
    pass


def _now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _new_id(prefix="exp"):
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def _flatten(d, prefix=""):
    out = {}
    for k, v in (d or {}).items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(_flatten(v, key + "."))
        else:
            out[key] = v
    return out


class Experiments:
    def __init__(self, access):
        self.acc = access; self.db = access.db; self.lock = access.lock
        self.dir = access.data_dir / "experiments"
        self._schema()

    def _schema(self):
        with self.lock:
            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS experiments(
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, owner TEXT NOT NULL, origin_preset TEXT, config TEXT NOT NULL,
                    notes TEXT NOT NULL DEFAULT '', config_version INTEGER NOT NULL DEFAULT 1, archived INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS runs(
                    id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL, kind TEXT NOT NULL, user TEXT NOT NULL, ts TEXT NOT NULL,
                    status TEXT NOT NULL, config_sha256 TEXT, rules_signature TEXT, config_version INTEGER, summary TEXT NOT NULL, path TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS runs_by_experiment ON runs(experiment_id, ts);
            """)

    # ---- helpers ----
    def _row(self, exp_id):
        return self.db.execute("SELECT * FROM experiments WHERE id=?", (exp_id,)).fetchone()

    @staticmethod
    def _to_dict(r):
        d = dict(r); d["config"] = json.loads(d["config"]); d["archived"] = bool(d["archived"]); return d

    def can_edit(self, principal, exp):
        return principal.can("users.manage") or exp["owner"] == principal.id

    def _require_edit(self, principal, exp_id):
        r = self._row(exp_id)
        if r is None:
            raise ExperimentError("no such experiment")
        exp = self._to_dict(r)
        if not self.can_edit(principal, exp):
            raise ExperimentError("only the owner or an administrator can change this experiment")
        return exp

    @staticmethod
    def _clean_name(name):
        name = re.sub(r"\s+", " ", (name or "").strip())
        if not 1 <= len(name) <= NAME_MAX:
            raise ExperimentError("the name must have between 1 and 120 characters")
        return name

    @staticmethod
    def _clean_config(config):
        cfg = copy.deepcopy(config)
        for k in ("preset", "run_label"):
            cfg.pop(k, None)
        problems = validate_config(cfg, D.load_competence_map())
        if problems:
            raise ExperimentError("invalid configuration: " + "; ".join(problems))
        return cfg

    # ---- experiments ----
    def create(self, principal, name, config, origin_preset=None, notes=""):
        if principal.legacy or not principal.can("replay.run"):
            raise ExperimentError("your role cannot create experiments")
        name = self._clean_name(name); cfg = self._clean_config(config); now = _now(); exp_id = _new_id()
        with self.lock:
            self.db.execute("INSERT INTO experiments(id, name, owner, origin_preset, config, notes, config_version, archived, created_at, updated_at) "
                            "VALUES(?, ?, ?, ?, ?, ?, 1, 0, ?, ?)", (exp_id, name, principal.id, origin_preset, json.dumps(cfg), notes or "", now, now))
            self.acc.audit(principal, "experiment.created", experiment=exp_id, name=name, origin=origin_preset)
        return self.get(exp_id)

    def from_preset(self, principal, preset, name=None, notes=""):
        if preset not in D.PRESETS:
            raise ExperimentError(f"unknown preset {preset}")
        return self.create(principal, name or f"{preset} (copy)", D.load_preset(preset), origin_preset=preset, notes=notes)

    def get(self, exp_id):
        r = self._row(exp_id)
        return None if r is None else self._to_dict(r)

    def list(self, include_archived=False):
        q = "SELECT * FROM experiments" + ("" if include_archived else " WHERE archived=0") + " ORDER BY updated_at DESC"
        return [self._to_dict(r) for r in self.db.execute(q).fetchall()]

    def update_config(self, principal, exp_id, config):
        exp = self._require_edit(principal, exp_id); cfg = self._clean_config(config)
        if json.dumps(cfg, sort_keys=True) == json.dumps(exp["config"], sort_keys=True):
            return exp
        with self.lock:
            self.db.execute("UPDATE experiments SET config=?, config_version=config_version+1, updated_at=? WHERE id=?", (json.dumps(cfg), _now(), exp_id))
            self.acc.audit(principal, "experiment.updated", experiment=exp_id, version=exp["config_version"] + 1)
        return self.get(exp_id)

    def rename(self, principal, exp_id, name):
        self._require_edit(principal, exp_id); name = self._clean_name(name)
        with self.lock:
            self.db.execute("UPDATE experiments SET name=?, updated_at=? WHERE id=?", (name, _now(), exp_id))
            self.acc.audit(principal, "experiment.renamed", experiment=exp_id, name=name)
        return self.get(exp_id)

    def set_notes(self, principal, exp_id, notes):
        self._require_edit(principal, exp_id)
        with self.lock:
            self.db.execute("UPDATE experiments SET notes=?, updated_at=? WHERE id=?", ((notes or "")[:5000], _now(), exp_id))
        return self.get(exp_id)

    def archive(self, principal, exp_id, archived=True):
        self._require_edit(principal, exp_id)
        with self.lock:
            self.db.execute("UPDATE experiments SET archived=?, updated_at=? WHERE id=?", (int(bool(archived)), _now(), exp_id))
            self.acc.audit(principal, "experiment.archived" if archived else "experiment.restored", experiment=exp_id)
        return self.get(exp_id)

    def duplicate(self, principal, exp_id, name=None):
        src = self.get(exp_id)
        if src is None:
            raise ExperimentError("no such experiment")
        return self.create(principal, name or f"{src['name']} (copy)", src["config"], origin_preset=src["origin_preset"], notes=src["notes"])

    # ---- runs ----
    @staticmethod
    def summarize(kind, results):
        if kind == "replay":
            return {"policies": {p: v["success_rate"]["mean"] for p, v in results["policies"].items()},
                    "seeds": results["config"]["seeds"], "episodes": results["config"]["episodes"],
                    "elapsed_seconds": results.get("elapsed_seconds")}
        pooled = {}
        for r in results.get("runs", []):
            p = pooled.setdefault(r["policy"], {"episodes": 0, "success": 0})
            p["episodes"] += r["episodes"]; p["success"] += r["success"]
        led = results.get("ledger", {})
        return {"policies": {p: (v["success"] / v["episodes"] if v["episodes"] else None) for p, v in pooled.items()},
                "status": results.get("status"), "calls": led.get("calls"), "upper_cost_usd": led.get("upper_cost_usd"),
                "key_source": results.get("key_source"), "episodes": results.get("episodes_per_run"), "seeds": results.get("seeds"),
                "elapsed_seconds": results.get("elapsed_seconds")}

    def record_run(self, principal, exp_id, kind, results, status=None, path=None):
        exp = self.get(exp_id)
        if exp is None:
            raise ExperimentError("no such experiment")
        if kind not in ("replay", "live"):
            raise ExperimentError("kind must be replay or live")
        run_id = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]
        if path is None:
            run_dir = self.dir / exp_id / "runs"; run_dir.mkdir(parents=True, exist_ok=True)
            path = run_dir / f"{run_id}.json"
            path.write_text(json.dumps(results, indent=1))
        cfg = results.get("config") or exp["config"]
        summary = self.summarize(kind, results)
        with self.lock:
            self.db.execute("INSERT INTO runs(id, experiment_id, kind, user, ts, status, config_sha256, rules_signature, config_version, summary, path) "
                            "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (run_id, exp_id, kind, principal.id, _now(), status or results.get("status", "completed"),
                             results.get("config_sha256") or config_hash(cfg), rules_signature(cfg), exp["config_version"], json.dumps(summary), str(path)))
            self.db.execute("UPDATE experiments SET updated_at=? WHERE id=?", (_now(), exp_id))
            self.acc.audit(principal, "run.recorded", experiment=exp_id, run=run_id, kind=kind, status=status or results.get("status", "completed"))
        return run_id

    def runs(self, exp_id, kind=None):
        q = "SELECT * FROM runs WHERE experiment_id=?" + (" AND kind=?" if kind else "") + " ORDER BY ts DESC"
        rows = self.db.execute(q, (exp_id, kind) if kind else (exp_id,)).fetchall()
        return [dict(r) | {"summary": json.loads(r["summary"])} for r in rows]

    def run(self, run_id):
        r = self.db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        return None if r is None else dict(r) | {"summary": json.loads(r["summary"])}

    def load_run(self, run_id):
        r = self.run(run_id)
        if r is None:
            raise ExperimentError("no such run")
        from pathlib import Path
        return json.loads(Path(r["path"]).read_text())

    def current_run_matches(self, exp, run):
        """True when the experiment's configuration is still the one this run was made with."""
        return config_hash(exp["config"]) == run["config_sha256"]

    # ---- comparison with the origin preset ----
    def diff_from_origin(self, exp):
        if not exp.get("origin_preset") or exp["origin_preset"] not in D.PRESETS:
            return None
        origin = D.load_preset(exp["origin_preset"]); cur = exp["config"]
        diffs = []
        oa, ca = origin["agents"], cur["agents"]
        if json.dumps(oa, sort_keys=True) != json.dumps(ca, sort_keys=True):
            def prof(agents):
                c = {}
                for a in agents:
                    c[a["profile"]] = c.get(a["profile"], 0) + 1
                return ", ".join(f"{k} {v}" for k, v in sorted(c.items()))
            diffs.append(("agents", f"{len(oa)} agents: {prof(oa)}", f"{len(ca)} agents: {prof(ca)}"))
        fo = _flatten({k: origin.get(k) for k in COMPARE_KEYS}); fc = _flatten({k: cur.get(k) for k in COMPARE_KEYS})
        for k in sorted(set(fo) | set(fc)):
            if k.startswith("task_pool.description"):
                continue
            if json.dumps(fo.get(k), sort_keys=True) != json.dumps(fc.get(k), sort_keys=True):
                diffs.append((k, fo.get(k), fc.get(k)))
        return diffs

    # ---- migration of the runs saved before experiments existed ----
    def import_legacy_live_runs(self):
        """Files in <data_dir>/live-runs become live runs of a per-user experiment derived from their population preset."""
        legacy = self.acc.data_dir / "live-runs"
        if not legacy.exists():
            return 0
        known = {r["path"] for r in self.db.execute("SELECT path FROM runs").fetchall()}
        imported = 0
        for f in sorted(legacy.glob("*.json")):
            if str(f) in known:
                continue
            try:
                results = json.loads(f.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            user = results.get("user") or f.stem.split("-", 1)[-1]
            principal = self.acc.principal_for(user)
            if principal is None:
                continue
            preset = PRESET_BY_POPULATION.get(results.get("population"), "paper-v2")
            exp_id = f"legacy-{preset}-{user}"
            if self._row(exp_id) is None:
                now = _now()
                with self.lock:
                    self.db.execute("INSERT INTO experiments(id, name, owner, origin_preset, config, notes, config_version, archived, created_at, updated_at) "
                                    "VALUES(?, ?, ?, ?, ?, ?, 1, 0, ?, ?)",
                                    (exp_id, f"{preset} · live runs of {user}", user, preset, json.dumps(self._clean_config(D.load_preset(preset))),
                                     "Imported from the live runs made before experiments existed.", now, now))
            self.record_run(principal, exp_id, "live", results, status=results.get("status"), path=f)
            imported += 1
        return imported
