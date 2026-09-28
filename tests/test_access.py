"""Accounts, roles, bootstrap, password policy, last-admin guard, sessions and audit."""
import time

import pytest

from socialmas import access as A


def make(tmp_path, **env):
    return A.Access(data_dir=tmp_path / "data", env={"SOCIALMAS_ADMIN_USER": "boot", "SOCIALMAS_ADMIN_PASSWORD": "bootstrap-secret-1", **env})


def test_roles_and_capabilities_are_consistent():
    for role, spec in A.ROLES.items():
        assert spec["capabilities"] <= set(A.CAPABILITIES), role
    assert A.Principal("x", "X", "sysadmin").can("users.manage")
    assert not A.Principal("x", "X", "reviewer").can("users.manage") and A.Principal("x", "X", "reviewer").can("replay.run")
    assert A.Principal("x", "X", "researcher").can("live.run") and not A.Principal("x", "X", "reviewer").can("live.run")
    with pytest.raises(KeyError):
        A.Principal("x", "X", "reviewer").can("fly")


def test_password_hashing_format_and_policy():
    h = A.hash_password("correct horse battery")
    assert h.startswith("pbkdf2_sha256$600000$") and A.verify_password("correct horse battery", h)
    assert not A.verify_password("wrong", h) and not A.verify_password("x", "garbage")
    with pytest.raises(A.AccessError):
        A.check_password_policy("short")


def test_bootstrap_then_first_account_disables_shared_credential(tmp_path):
    acc = make(tmp_path)
    assert acc.bootstrap_active() and not acc.has_users()
    assert acc.authenticate("nobody", "whatever") is None
    boot = acc.authenticate("Boot", "bootstrap-secret-1")
    assert boot and boot.legacy and boot.role == "sysadmin"
    with pytest.raises(A.AccessError):
        acc.issue_token(boot)
    with pytest.raises(A.AccessError):
        acc.upsert_user(boot, "marco", "Marco", "reviewer", password="temporary-pass-1")   # first account must be sysadmin
    u = acc.upsert_user(boot, "Marco", "Marco Becattini", "sysadmin", password="temporary-pass-1")
    assert u["id"] == "marco" and u["must_change_password"] and u["active"]
    assert acc.authenticate("boot", "bootstrap-secret-1") is None            # shared credential is dead now
    p = acc.authenticate("MARCO ", "temporary-pass-1")
    assert p and p.must_change_password and not p.legacy
    actions = [e["action"] for e in acc.events()]
    assert "user.created" in actions and "session.login" in actions and "session.login_failed" in actions


def test_first_login_change_clears_flag_and_wrong_current_is_refused(tmp_path):
    acc = make(tmp_path)
    boot = acc.authenticate("boot", "bootstrap-secret-1")
    acc.upsert_user(boot, "marco", "Marco", "sysadmin", password="temporary-pass-1")
    p = acc.authenticate("marco", "temporary-pass-1")
    with pytest.raises(A.AccessError):
        acc.change_password(p, "wrong-current-1", "my-own-password-1")
    with pytest.raises(A.AccessError):
        acc.change_password(p, "temporary-pass-1", "short")
    acc.change_password(p, "temporary-pass-1", "my-own-password-1")
    assert not acc.principal_for("marco").must_change_password
    assert acc.authenticate("marco", "temporary-pass-1") is None and acc.authenticate("marco", "my-own-password-1")


def test_admin_flows_roles_deactivation_and_last_admin_guard(tmp_path):
    acc = make(tmp_path)
    boot = acc.authenticate("boot", "bootstrap-secret-1")
    acc.upsert_user(boot, "marco", "Marco", "sysadmin", password="temporary-pass-1")
    marco = acc.authenticate("marco", "temporary-pass-1")
    acc.upsert_user(marco, "iera", "Antonio Iera", "researcher", password="another-temp-1")
    acc.upsert_user(marco, "rev1", "Reviewer One", "reviewer", password="reviewer-temp-1")
    ids = [u["id"] for u in acc.list_users()]
    assert ids == ["iera", "marco", "rev1"] and all("password" not in u for u in acc.list_users())
    rev = acc.authenticate("rev1", "reviewer-temp-1")
    with pytest.raises(A.AccessError):
        acc.upsert_user(rev, "x", "X", "reviewer", password="reviewer-temp-1")          # reviewers cannot manage users
    acc.upsert_user(marco, "iera", "Antonio Iera", "sysadmin")                          # promote, no password change
    assert acc.get_user("iera")["role"] == "sysadmin" and acc.authenticate("iera", "another-temp-1")
    acc.upsert_user(marco, "rev1", "Reviewer One", "reviewer", active=False)            # deactivate
    assert acc.authenticate("rev1", "reviewer-temp-1") is None and acc.principal_for("rev1") is None
    acc.upsert_user(marco, "marco", "Marco", "reviewer")                                # demote self while iera is admin: allowed
    assert acc.get_user("marco")["role"] == "reviewer" and not acc.principal_for("marco").can("users.manage")
    iera_p = acc.principal_for("iera")
    acc.upsert_user(iera_p, "marco", "Marco", "sysadmin")                               # iera promotes marco back
    marco = acc.principal_for("marco")
    acc.upsert_user(marco, "iera", "Antonio Iera", "researcher")                        # demote iera back
    with pytest.raises(A.AccessError):
        acc.upsert_user(marco, "marco", "Marco", "sysadmin", active=False)              # last admin cannot be deactivated
    with pytest.raises(A.AccessError):
        acc.remove_user(marco, "marco")
    acc.remove_user(marco, "rev1")
    assert acc.get_user("rev1") is None
    with pytest.raises(A.AccessError):
        acc.upsert_user(marco, "Bad Id", "Bad", "reviewer", password="reviewer-temp-1")
    with pytest.raises(A.AccessError):
        acc.upsert_user(marco, "ok", "Ok", "wizard", password="reviewer-temp-1")


def test_admin_password_reset_flags_account_and_invalidates_sessions(tmp_path):
    acc = make(tmp_path)
    boot = acc.authenticate("boot", "bootstrap-secret-1")
    acc.upsert_user(boot, "marco", "Marco", "sysadmin", password="temporary-pass-1")
    marco = acc.authenticate("marco", "temporary-pass-1"); acc.change_password(marco, "temporary-pass-1", "my-own-password-1")
    acc.upsert_user(marco, "iera", "Antonio Iera", "researcher", password="another-temp-1")
    iera = acc.authenticate("iera", "another-temp-1"); acc.change_password(iera, "another-temp-1", "iera-own-password")
    iera = acc.authenticate("iera", "iera-own-password"); tok = acc.issue_token(iera)
    assert acc.verify_token(tok).id == "iera"
    time.sleep(1.1)
    acc.upsert_user(marco, "iera", "Antonio Iera", "researcher", password="reset-by-admin-1")
    assert acc.verify_token(tok) is None                                                # older sessions are dead
    assert acc.principal_for("iera").must_change_password


def test_session_tokens_sign_expire_and_logout(tmp_path):
    acc = make(tmp_path)
    boot = acc.authenticate("boot", "bootstrap-secret-1")
    acc.upsert_user(boot, "marco", "Marco", "sysadmin", password="temporary-pass-1")
    marco = acc.authenticate("marco", "temporary-pass-1")
    tok = acc.issue_token(marco)
    assert acc.verify_token(tok).id == "marco"
    body, sig = tok.split(".")
    assert acc.verify_token(body + ".AAAA") is None and acc.verify_token("nonsense") is None
    assert acc.verify_token(acc.issue_token(marco, ttl=-1)) is None
    other = A.Access(data_dir=tmp_path / "other", env={"SOCIALMAS_SESSION_SECRET": "different-secret"})
    assert other.verify_token(tok) is None
    time.sleep(1.1)
    acc.logout(marco)
    assert acc.verify_token(tok) is None
    assert acc.verify_token(acc.issue_token(acc.authenticate("marco", "temporary-pass-1"))).id == "marco"


def test_secret_persists_and_env_secret_wins(tmp_path):
    a = make(tmp_path); b = A.Access(data_dir=tmp_path / "data", env={})
    assert a.secret == b.secret
    c = A.Access(data_dir=tmp_path / "data", env={"SOCIALMAS_SESSION_SECRET": "from-env"})
    assert c.secret == b"from-env"


def test_no_bootstrap_without_env_and_hosted_warning(tmp_path):
    acc = A.Access(data_dir=tmp_path / "d", env={})
    assert not acc.bootstrap_active() and acc.authenticate("boot", "x") is None
    hosted = A.Access(data_dir=tmp_path / "d2", env={"RENDER": "true"})
    assert hosted.persistent_warning and "persistent disk" in hosted.persistent_warning
