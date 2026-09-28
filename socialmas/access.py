"""Accounts, roles, sessions and audit for the hosted laboratory.

The model is borrowed from Scala Radar (Becattini, 2026): capabilities are a fixed list in code, roles are named
bundles of capabilities, every user holds exactly one role; users are created by an administrator only (no sign-up,
no email); passwords are PBKDF2-SHA256; while no account exists, an environment credential acts as an implicit
SysAdmin and stops working as soon as the first account is created; a password set by someone else must be changed
at the next login; the last active administrator cannot be removed, demoted or deactivated; every governance act is
appended to an audit log. Storage is a single SQLite file (one web instance), on the persistent disk when hosted."""
import base64
import datetime as dt
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
from pathlib import Path

CAPABILITIES = {
    "replay.run": "run replay experiments and edit populations",
    "replay.export": "download results, reports and configurations",
    "paper.view": "see the pre-registered results of the paper",
    "data.view": "see the competence map and the method",
    "live.run": "run live episodes with real LLM calls under a spending cap (coming release)",
    "users.manage": "create users, assign roles, reset passwords, deactivate accounts",
    "audit.view": "read the access log",
    "settings.manage": "change application settings",
}
_BASE = {"replay.run", "replay.export", "paper.view", "data.view"}
ROLES = {
    "sysadmin": {"label": "SysAdmin", "capabilities": set(CAPABILITIES)},
    "researcher": {"label": "Researcher", "capabilities": _BASE | {"live.run"}},
    "reviewer": {"label": "Reviewer", "capabilities": set(_BASE)},
}
ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
ID_MAX, NAME_MAX, PASSWORD_MIN, PASSWORD_MAX = 64, 120, 10, 200
PBKDF2_ITERATIONS = 600_000
SESSION_TTL_SECONDS = 12 * 3600
COOKIE_NAME = "socialmas_session"


class AccessError(ValueError):
    """A refused operation, with a message meant for the person."""


# ---- passwords ----
def hash_password(password, iterations=PBKDF2_ITERATIONS):
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), iterations).hex()
    return f"pbkdf2_sha256${iterations}${salt}${digest}"


def verify_password(password, stored):
    try:
        algo, iterations, salt, digest = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(iterations)).hex()
        return hmac.compare_digest(candidate, digest)
    except (ValueError, AttributeError):
        return False


DUMMY_HASH = hash_password("dummy-password-for-timing", iterations=PBKDF2_ITERATIONS)


def check_password_policy(password):
    if not isinstance(password, str) or len(password) < PASSWORD_MIN:
        raise AccessError(f"the password must have at least {PASSWORD_MIN} characters")
    if len(password) > PASSWORD_MAX:
        raise AccessError(f"the password must have at most {PASSWORD_MAX} characters")


def _now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


class Principal:
    def __init__(self, id, name, role, legacy=False, must_change_password=False, active=True):
        self.id = id; self.name = name; self.role = role; self.legacy = legacy
        self.must_change_password = must_change_password; self.active = active
        self.capabilities = set(ROLES.get(role, {"capabilities": set()})["capabilities"])

    def can(self, capability):
        if capability not in CAPABILITIES:
            raise KeyError(f"unknown capability {capability}")
        return capability in self.capabilities

    @property
    def role_label(self):
        return ROLES.get(self.role, {}).get("label", self.role)


def default_data_dir(env=None):
    env = os.environ if env is None else env
    explicit = env.get("SOCIALMAS_DATA_DIR")
    if explicit:
        return Path(explicit)
    hosted = Path("/var/data")
    if hosted.is_dir() and os.access(hosted, os.W_OK):
        return hosted
    return Path.cwd() / "data"


class Access:
    """All account operations. One instance per process; SQLite connection shared under a lock."""

    def __init__(self, data_dir=None, env=None):
        self.env = os.environ if env is None else env
        wanted = Path(data_dir) if data_dir else default_data_dir(self.env)
        self.persistent_warning = None
        try:
            wanted.mkdir(parents=True, exist_ok=True)
            self.data_dir = wanted
        except OSError as e:
            fallback = Path.cwd() / "data"; fallback.mkdir(parents=True, exist_ok=True)
            self.data_dir = fallback
            self.persistent_warning = f"could not use {wanted} ({e}); accounts are stored in {fallback}, which may not survive a redeploy"
        if self.env.get("RENDER") and self.data_dir != Path("/var/data") and not self.env.get("SOCIALMAS_DATA_DIR"):
            self.persistent_warning = "no persistent disk mounted at /var/data: accounts will be lost at the next deploy"
        self.path = self.data_dir / "access.sqlite3"
        self.lock = threading.RLock()
        self.db = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self._schema()
        self.secret = (self.env.get("SOCIALMAS_SESSION_SECRET") or self._setting("session_secret") or self._new_secret()).encode()

    # ---- storage ----
    def _schema(self):
        with self.lock:
            self.db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS users(
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, role TEXT NOT NULL, password TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1, must_change_password INTEGER NOT NULL DEFAULT 0,
                    sessions_valid_from TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS access_events(
                    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL, details TEXT NOT NULL);
            """)

    def _setting(self, key):
        row = self.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None

    def _set_setting(self, key, value):
        with self.lock:
            self.db.execute("INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))

    def _new_secret(self):
        s = secrets.token_urlsafe(48); self._set_setting("session_secret", s); return s

    # ---- audit ----
    def audit(self, actor, action, **details):
        with self.lock:
            self.db.execute("INSERT INTO access_events(ts, actor, action, details) VALUES(?, ?, ?, ?)",
                            (_now(), actor.id if isinstance(actor, Principal) else str(actor), action, json.dumps(details, sort_keys=True)))

    def events(self, limit=200):
        rows = self.db.execute("SELECT ts, actor, action, details FROM access_events ORDER BY id DESC LIMIT ?", (int(limit),)).fetchall()
        return [{"ts": r["ts"], "actor": r["actor"], "action": r["action"], **json.loads(r["details"])} for r in rows]

    # ---- users ----
    def _row(self, user_id):
        return self.db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()

    def has_users(self):
        return self.db.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"] > 0

    def list_users(self):
        rows = self.db.execute("SELECT id, name, role, active, must_change_password, created_at, updated_at FROM users ORDER BY id").fetchall()
        return [dict(r) | {"active": bool(r["active"]), "must_change_password": bool(r["must_change_password"]),
                           "role_label": ROLES.get(r["role"], {}).get("label", r["role"])} for r in rows]

    def get_user(self, user_id):
        r = self._row(user_id)
        return None if r is None else {k: r[k] for k in r.keys() if k != "password"} | {"active": bool(r["active"]), "must_change_password": bool(r["must_change_password"])}

    def _admins_after(self, changed_id, role, active):
        """Active users holding users.manage once `changed_id` has the given role and status."""
        n = 0
        for r in self.db.execute("SELECT id, role, active FROM users").fetchall():
            rid, rrole, ractive = (changed_id, role, active) if r["id"] == changed_id else (r["id"], r["role"], bool(r["active"]))
            if ractive and "users.manage" in ROLES.get(rrole, {"capabilities": set()})["capabilities"]:
                n += 1
        return n

    def upsert_user(self, actor, user_id, name, role, password=None, active=True):
        """Create or update an account. The actor needs users.manage. A password set here flags the account to change it."""
        if not actor.can("users.manage"):
            raise AccessError("your role cannot manage users")
        user_id = (user_id or "").strip().lower(); name = (name or "").strip()
        if not ID_RE.match(user_id) or len(user_id) > ID_MAX:
            raise AccessError("the id must be lowercase letters, digits, dots, dashes or underscores, at most 64 characters")
        if not 1 <= len(name) <= NAME_MAX:
            raise AccessError("the name must have between 1 and 120 characters")
        if role not in ROLES:
            raise AccessError(f"unknown role {role!r}; roles are {', '.join(ROLES)}")
        with self.lock:
            existing = self._row(user_id)
            if existing is None:
                if password is None:
                    raise AccessError("a new account needs a temporary password")
                if actor.legacy and role != "sysadmin":
                    raise AccessError("the first account must be a SysAdmin")
                if not self.has_users() and role != "sysadmin":
                    raise AccessError("the first account must be a SysAdmin")
            if password is not None:
                check_password_policy(password)
            if existing is not None and self._admins_after(user_id, role, bool(active)) == 0:
                raise AccessError("this change would leave no active administrator")
            now = _now()
            if existing is None:
                self.db.execute("INSERT INTO users(id, name, role, password, active, must_change_password, sessions_valid_from, created_at, updated_at) "
                                "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                (user_id, name, role, hash_password(password), int(bool(active)), int(actor.id != user_id), now, now, now))
                self.audit(actor, "user.created", user=user_id, role=role, active=bool(active))
            else:
                fields = {"name": name, "role": role, "active": int(bool(active)), "updated_at": now}
                if password is not None:
                    fields["password"] = hash_password(password); fields["must_change_password"] = int(actor.id != user_id)
                    fields["sessions_valid_from"] = now
                if not active:
                    fields["sessions_valid_from"] = now
                sets = ", ".join(f"{k}=?" for k in fields)
                self.db.execute(f"UPDATE users SET {sets} WHERE id=?", (*fields.values(), user_id))
                self.audit(actor, "user.updated", user=user_id, role=role, active=bool(active), password_changed=password is not None)
        return self.get_user(user_id)

    def remove_user(self, actor, user_id):
        if not actor.can("users.manage"):
            raise AccessError("your role cannot manage users")
        with self.lock:
            r = self._row(user_id)
            if r is None:
                raise AccessError("no such user")
            if self._admins_after(user_id, r["role"], False) == 0:
                raise AccessError("this would remove the last active administrator")
            self.db.execute("DELETE FROM users WHERE id=?", (user_id,))
            self.audit(actor, "user.removed", user=user_id)

    def change_password(self, principal, current_password, new_password):
        """Self-service change: verifies the current password, clears the first-login flag, invalidates older sessions."""
        if principal.legacy:
            raise AccessError("the bootstrap credential has no password to change: create your account first")
        r = self._row(principal.id)
        if r is None or not verify_password(current_password, r["password"]):
            raise AccessError("the current password is wrong")
        check_password_policy(new_password)
        if new_password == current_password:
            raise AccessError("choose a different password")
        now = _now()
        with self.lock:
            self.db.execute("UPDATE users SET password=?, must_change_password=0, sessions_valid_from=?, updated_at=? WHERE id=?",
                            (hash_password(new_password), now, now, principal.id))
            self.audit(principal, "password.changed", user=principal.id)

    # ---- authentication ----
    def bootstrap_credentials(self):
        u = (self.env.get("SOCIALMAS_ADMIN_USER") or "").strip(); p = (self.env.get("SOCIALMAS_ADMIN_PASSWORD") or "").strip()
        return (u, p) if u and p else None

    def bootstrap_active(self):
        return not self.has_users() and self.bootstrap_credentials() is not None

    def authenticate(self, username, password):
        """Principal for a correct username and password, else None. Same answer and similar timing for unknown users."""
        username = (username or "").strip().lower(); password = password or ""
        if not self.has_users():
            creds = self.bootstrap_credentials()
            if creds and hmac.compare_digest(username, creds[0].lower()) and hmac.compare_digest(password, creds[1]):
                self.audit(username, "session.login", legacy=True)
                return Principal(creds[0], "Bootstrap administrator", "sysadmin", legacy=True)
            verify_password(password, DUMMY_HASH)
            self.audit(username or "-", "session.login_failed")
            return None
        r = self._row(username)
        if r is None or not r["active"]:
            verify_password(password, DUMMY_HASH)
            self.audit(username or "-", "session.login_failed")
            return None
        if not verify_password(password, r["password"]):
            self.audit(username, "session.login_failed")
            return None
        self.audit(username, "session.login")
        return self.principal_for(username)

    def principal_for(self, user_id):
        r = self._row(user_id)
        if r is None or not r["active"]:
            return None
        return Principal(r["id"], r["name"], r["role"], must_change_password=bool(r["must_change_password"]))

    # ---- sessions: HMAC-signed tokens, no server state beyond sessions_valid_from ----
    def issue_token(self, principal, ttl=SESSION_TTL_SECONDS):
        if principal.legacy:
            raise AccessError("the bootstrap credential cannot open a persistent session")
        now = int(dt.datetime.now(dt.timezone.utc).timestamp())
        body = _b64(json.dumps({"sub": principal.id, "iat": now, "exp": now + int(ttl)}, separators=(",", ":")).encode())
        sig = _b64(hmac.new(self.secret, body.encode(), hashlib.sha256).digest())
        return f"{body}.{sig}"

    def verify_token(self, token):
        try:
            body, sig = token.split(".")
            expected = _b64(hmac.new(self.secret, body.encode(), hashlib.sha256).digest())
            if not hmac.compare_digest(sig, expected):
                return None
            claims = json.loads(_unb64(body))
        except (ValueError, AttributeError, json.JSONDecodeError):
            return None
        now = int(dt.datetime.now(dt.timezone.utc).timestamp())
        if claims.get("exp", 0) <= now:
            return None
        r = self._row(claims.get("sub", ""))
        if r is None or not r["active"]:
            return None
        valid_from = dt.datetime.fromisoformat(r["sessions_valid_from"]).timestamp()
        if claims.get("iat", 0) < int(valid_from):
            return None
        return self.principal_for(r["id"])

    def logout(self, principal):
        """Invalidate every token issued to this user before now."""
        if principal.legacy:
            return
        with self.lock:
            self.db.execute("UPDATE users SET sessions_valid_from=? WHERE id=?", (_now(), principal.id))
            self.audit(principal, "session.logout")
