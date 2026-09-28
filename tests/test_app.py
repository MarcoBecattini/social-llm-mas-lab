"""Smoke tests of the Streamlit app with Streamlit's AppTest: gate, bootstrap and administration, replay run, comparison."""
import os
from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / "app" / "streamlit_app.py")
BOOT = {"SOCIALMAS_ADMIN_USER": "boot", "SOCIALMAS_ADMIN_PASSWORD": "bootstrap-secret-1"}


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Fresh data directory and caches for every test; authentication on unless a test turns it off."""
    monkeypatch.setenv("SOCIALMAS_DATA_DIR", str(tmp_path / "data"))
    for k in ("RENDER", "SOCIALMAS_REQUIRE_AUTH", "SOCIALMAS_SESSION_SECRET", *BOOT):
        monkeypatch.delenv(k, raising=False)
    st.cache_resource.clear(); st.cache_data.clear()
    yield monkeypatch
    st.cache_resource.clear()


def _app():
    at = AppTest.from_file(APP, default_timeout=120)
    at.run()
    return at


def _login(at, username, password):
    at.text_input[0].set_value(username)
    at.text_input[1].set_value(password)
    at.button[0].click()      # form submit "Sign in"
    at.run()
    return at


def test_open_mode_loads_paper_preset_and_reference_tab(env):
    env.setenv("SOCIALMAS_REQUIRE_AUTH", "0")
    at = _app()
    assert not at.exception
    assert at.session_state["preset"] == "paper-v2" and len(at.session_state["cfg"]["agents"]) == 11
    assert "Configuration valid" in " ".join(x.value for x in at.success)
    assert any("Pre-registered results" in x.value for x in at.subheader)
    assert any("Administration" in t.label for t in at.tabs)                  # local user is a sysadmin


def test_open_mode_runs_small_replay_and_matches_paper(env):
    env.setenv("SOCIALMAS_REQUIRE_AUTH", "0")
    at = _app()
    at.sidebar.slider[0].set_value(1)                      # seeds
    at.sidebar.multiselect[0].set_value(["random", "social"])
    at.sidebar.select_slider[1].set_value(1000)            # bootstrap resamples
    at.sidebar.button[1].click()                           # Run replay (button 0 is Load preset)
    at.run()
    assert not at.exception
    r = at.session_state["results"]
    assert set(r["policies"]) == {"random", "social"} and r["config"]["seeds"] == 1 and r["config"]["episodes"] == 3000
    assert "social - random" in r["paired_differences"]
    assert any("Same population and rules" in x.value for x in at.success)


def test_open_mode_flags_invalid_population(env):
    env.setenv("SOCIALMAS_REQUIRE_AUTH", "0")
    at = _app()
    at.sidebar.multiselect[0].set_value([])
    at.run()
    assert any("select at least one policy" in x.value for x in at.error)


def test_gate_without_accounts_or_bootstrap_explains_what_to_do(env):
    at = _app()
    assert not at.exception
    assert any("No account exists yet" in x.value for x in at.error)
    assert not at.tabs


def test_bootstrap_login_create_admin_forced_change_and_sign_out(env):
    for k, v in BOOT.items():
        env.setenv(k, v)
    at = _app()
    assert any("First start" in x.value for x in at.info) and not at.tabs
    _login(at, "boot", "wrong-password-1")
    assert any("Wrong username or password" in x.value for x in at.error)
    at = _login(_app(), "boot", "bootstrap-secret-1")
    assert not at.exception and any("Administration" in t.label for t in at.tabs)
    # create the first (SysAdmin) account through the admin form
    form_inputs = [t for t in at.text_input if t.label.startswith(("id", "Name", "Temporary password"))]
    form_inputs[0].set_value("marco"); form_inputs[1].set_value("Marco Becattini"); form_inputs[2].set_value("temporary-pass-1")
    add_btn = next(b for b in at.button if b.label == "Create account")
    add_btn.click(); at.run()
    assert not at.exception
    from socialmas import access as A
    acc = A.Access(env=dict(os.environ))
    assert [u["id"] for u in acc.list_users()] == ["marco"] and acc.list_users()[0]["role"] == "sysadmin"
    assert acc.authenticate("boot", "bootstrap-secret-1") is None          # bootstrap credential is dead
    # sign out, sign in as marco: forced password change
    at2 = _app()                                                             # a new browser session: gate again
    assert not at2.tabs
    at2 = _login(at2, "marco", "temporary-pass-1")
    assert any("Choose your own password" in x.value for x in at2.title) and not at2.tabs
    at2.text_input[0].set_value("temporary-pass-1"); at2.text_input[1].set_value("my-own-password-1"); at2.text_input[2].set_value("my-own-password-1")
    at2.button[0].click(); at2.run()
    assert not at2.exception and any("Administration" in t.label for t in at2.tabs)
    assert not acc.principal_for("marco").must_change_password
    # a reviewer sees no Administration tab
    acc.upsert_user(acc.principal_for("marco"), "rev", "Reviewer", "reviewer", password="reviewer-pass-1")
    acc.change_password(acc.authenticate("rev", "reviewer-pass-1"), "reviewer-pass-1", "reviewer-own-pass")
    at3 = _login(_app(), "rev", "reviewer-own-pass")
    assert not at3.exception and at3.tabs and not any("Administration" in t.label for t in at3.tabs)
    assert any("Account" in t.label for t in at3.tabs)


def test_live_tab_shows_grader_status_and_reference(env):
    env.setenv("SOCIALMAS_REQUIRE_AUTH", "0"); env.setenv("GRADER_URL", "http://127.0.0.1:9")   # nothing listens there
    at = _app()
    assert not at.exception and any(t.label == "Live" for t in at.tabs)
    assert any("Grader not reachable" in x.value for x in at.error)
    assert any("Reference: the paper" in x.value for x in at.markdown)
    assert any("Quote from the paper" in x.value for x in at.info)


def test_admin_sees_shared_key_section_in_open_mode(env):
    env.setenv("SOCIALMAS_REQUIRE_AUTH", "0"); env.setenv("GRADER_URL", "http://127.0.0.1:9")
    at = _app()
    assert not at.exception
    assert any("Shared OpenAI key" in x.value for x in at.subheader)
    assert any("Global cap on shared-key spending" in n.label for n in at.number_input)


def test_researcher_with_allowance_gets_shared_key_option(env):
    for k, v in BOOT.items():
        env.setenv(k, v)
    env.setenv("GRADER_URL", "http://127.0.0.1:9")
    from socialmas import access as A
    acc = A.Access(env=dict(os.environ))
    boot = acc.authenticate("boot", "bootstrap-secret-1")
    acc.upsert_user(boot, "marco", "Marco", "sysadmin", password="temporary-pass-1")
    marco = acc.authenticate("marco", "temporary-pass-1"); acc.change_password(marco, "temporary-pass-1", "my-own-password-1"); marco = acc.principal_for("marco")
    acc.upsert_user(marco, "iera", "Antonio Iera", "researcher", password="another-temp-1")
    acc.change_password(acc.authenticate("iera", "another-temp-1"), "another-temp-1", "iera-own-password")
    acc.set_shared_key(marco, "sk-test-0123456789abcdefghijkl")
    st.cache_resource.clear()
    at = _login(_app(), "iera", "iera-own-password")                    # no allowance yet
    assert not at.exception and any(t.label == "Live" for t in at.tabs)
    radio = next(r for r in at.radio if r.label == "Key to use")
    assert radio.options == ["My own key"]
    assert any("no remaining allowance" in x.value for x in at.caption)
    acc.set_allowance(marco, "iera", 0.25)
    st.cache_resource.clear()
    at = _login(_app(), "iera", "iera-own-password")
    radio = next(r for r in at.radio if r.label == "Key to use")
    assert len(radio.options) == 2 and "0.25 USD" in radio.options[1]
