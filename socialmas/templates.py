"""Personal templates: named configurations from which experiments are created, like the paper's presets, but owned by a
user and editable. A template has no runs: it is a starting point, not a measurement. Private by default (visible to
its owner and to administrators); the owner can share it with the whole laboratory. Only the owner and administrators
change it; every save bumps its version, so experiments created from it know which version they copied."""
import json

from . import data as D
from .experiments import ExperimentError, _new_id, _now, normalized_json

DESCRIPTION_MAX = 2000
ORIGIN_KINDS = ("preset", "template", "experiment")


class Templates:
    def __init__(self, experiments):
        self.ex = experiments; self.acc = experiments.acc; self.db = experiments.db; self.lock = experiments.lock
        self._schema()

    def _schema(self):
        with self.lock:
            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS templates(
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, owner TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
                    config TEXT NOT NULL, config_version INTEGER NOT NULL DEFAULT 1, shared INTEGER NOT NULL DEFAULT 0,
                    archived INTEGER NOT NULL DEFAULT 0, origin_kind TEXT, origin_ref TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            """)

    # ---- permissions ----
    @staticmethod
    def can_see(principal, tpl):
        return bool(tpl["shared"]) or tpl["owner"] == principal.id or principal.can("users.manage")

    @staticmethod
    def can_edit(principal, tpl):
        return tpl["owner"] == principal.id or principal.can("users.manage")

    @staticmethod
    def can_create(principal):
        return principal.can("replay.run") and not principal.legacy

    # ---- helpers ----
    @staticmethod
    def _to_dict(r):
        d = dict(r); d["config"] = json.loads(d["config"]); d["shared"] = bool(d["shared"]); d["archived"] = bool(d["archived"]); return d

    def _raw(self, tpl_id):
        r = self.db.execute("SELECT * FROM templates WHERE id=?", (tpl_id,)).fetchone()
        return None if r is None else self._to_dict(r)

    def _require_edit(self, principal, tpl_id):
        tpl = self._raw(tpl_id)
        if tpl is None or not self.can_see(principal, tpl):
            raise ExperimentError("no such template")
        if not self.can_edit(principal, tpl):
            raise ExperimentError("only the owner or an administrator can change this template")
        return tpl

    @staticmethod
    def _clean_description(text):
        return (text or "").strip()[:DESCRIPTION_MAX]

    # ---- creation ----
    def create(self, principal, name, config, description="", origin_kind=None, origin_ref=None):
        if not self.can_create(principal):
            raise ExperimentError("your role cannot create templates")
        if origin_kind is not None and origin_kind not in ORIGIN_KINDS:
            raise ExperimentError(f"origin must be one of {', '.join(ORIGIN_KINDS)}")
        name = self.ex._clean_name(name); cfg = self.ex._clean_config(config); now = _now(); tpl_id = _new_id("tpl")
        with self.lock:
            self.db.execute("INSERT INTO templates(id, name, owner, description, config, config_version, shared, archived, origin_kind, origin_ref, "
                            "created_at, updated_at) VALUES(?, ?, ?, ?, ?, 1, 0, 0, ?, ?, ?, ?)",
                            (tpl_id, name, principal.id, self._clean_description(description), json.dumps(cfg), origin_kind, origin_ref, now, now))
            self.acc.audit(principal, "template.created", template=tpl_id, name=name, origin=f"{origin_kind}:{origin_ref}" if origin_kind else None)
        return self._raw(tpl_id)

    def from_preset(self, principal, preset, name=None, description=""):
        if preset not in D.PRESETS:
            raise ExperimentError(f"unknown preset {preset}")
        return self.create(principal, name or f"{preset} (template)", D.load_preset(preset), description, "preset", preset)

    def from_experiment(self, principal, exp_id, name=None, description=""):
        exp = self.ex.get(exp_id)
        if exp is None:
            raise ExperimentError("no such experiment")
        return self.create(principal, name or f"{exp['name']} (template)", exp["config"], description or exp["notes"], "experiment", exp_id)

    def duplicate(self, principal, tpl_id, name=None):
        src = self.get(principal, tpl_id)
        if src is None:
            raise ExperimentError("no such template")
        return self.create(principal, name or f"{src['name']} (copy)", src["config"], src["description"], "template", tpl_id)

    # ---- reading ----
    def get(self, principal, tpl_id):
        """The template, or None when it does not exist or this principal may not see it."""
        tpl = self._raw(tpl_id)
        return tpl if tpl is not None and self.can_see(principal, tpl) else None

    def get_any(self, tpl_id):
        """The template regardless of visibility: for the origin of an experiment, whose configuration is already public in the lab."""
        return self._raw(tpl_id)

    def list(self, principal, include_archived=False):
        q = "SELECT * FROM templates" + ("" if include_archived else " WHERE archived=0") + " ORDER BY updated_at DESC"
        return [t for t in (self._to_dict(r) for r in self.db.execute(q).fetchall()) if self.can_see(principal, t)]

    # ---- changes ----
    def update_config(self, principal, tpl_id, config):
        tpl = self._require_edit(principal, tpl_id); cfg = self.ex._clean_config(config)
        if normalized_json(cfg) == normalized_json(tpl["config"]):
            return tpl
        with self.lock:
            self.db.execute("UPDATE templates SET config=?, config_version=config_version+1, updated_at=? WHERE id=?", (json.dumps(cfg), _now(), tpl_id))
            self.acc.audit(principal, "template.updated", template=tpl_id, version=tpl["config_version"] + 1)
        return self._raw(tpl_id)

    def rename(self, principal, tpl_id, name):
        self._require_edit(principal, tpl_id); name = self.ex._clean_name(name)
        with self.lock:
            self.db.execute("UPDATE templates SET name=?, updated_at=? WHERE id=?", (name, _now(), tpl_id))
            self.acc.audit(principal, "template.renamed", template=tpl_id, name=name)
        return self._raw(tpl_id)

    def set_description(self, principal, tpl_id, text):
        self._require_edit(principal, tpl_id)
        with self.lock:
            self.db.execute("UPDATE templates SET description=?, updated_at=? WHERE id=?", (self._clean_description(text), _now(), tpl_id))
        return self._raw(tpl_id)

    def set_shared(self, principal, tpl_id, shared):
        self._require_edit(principal, tpl_id)
        with self.lock:
            self.db.execute("UPDATE templates SET shared=?, updated_at=? WHERE id=?", (int(bool(shared)), _now(), tpl_id))
            self.acc.audit(principal, "template.shared" if shared else "template.unshared", template=tpl_id)
        return self._raw(tpl_id)

    def archive(self, principal, tpl_id, archived=True):
        self._require_edit(principal, tpl_id)
        with self.lock:
            self.db.execute("UPDATE templates SET archived=?, updated_at=? WHERE id=?", (int(bool(archived)), _now(), tpl_id))
            self.acc.audit(principal, "template.archived" if archived else "template.restored", template=tpl_id)
        return self._raw(tpl_id)

    # ---- experiments from templates ----
    def new_experiment(self, principal, tpl_id, name=None, notes=""):
        tpl = self.get(principal, tpl_id)
        if tpl is None or tpl["archived"]:
            raise ExperimentError("no such template")
        return self.ex.create(principal, name or f"{tpl['name']} (experiment)", tpl["config"], notes=notes or tpl["description"],
                              origin_template=tpl_id, origin_template_version=tpl["config_version"])

