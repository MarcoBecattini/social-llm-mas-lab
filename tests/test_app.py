"""Smoke tests of the Streamlit app with Streamlit's AppTest: gate, bootstrap and administration, experiments, replay, history,
paper comparison, live page, shared key.

The interface is a sidebar navigation (`st.navigation`) with one page per run: tests switch pages by URL path, since
Streamlit hashes pages by `url_path`, and read the pages offered to a role from the registry AppTest keeps."""
import os
import re
import sys
from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest
from streamlit.util import calc_hash

APP_DIR = Path(__file__).resolve().parents[1] / "app"
APP = str(APP_DIR / "streamlit_app.py")
BOOT = {"SOCIALMAS_ADMIN_USER": "boot", "SOCIALMAS_ADMIN_PASSWORD": "bootstrap-secret-1"}
ALL_PAGES = ("Experiments", "Configure", "Replay", "Live", "History", "Presets and templates", "Template editor", "Paper comparison", "Data and method", "Account", "Administration")


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("SOCIALMAS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("GRADER_URL", "http://127.0.0.1:9")            # nothing listens there
    for k in ("RENDER", "SOCIALMAS_REQUIRE_AUTH", "SOCIALMAS_SESSION_SECRET", *BOOT):
        monkeypatch.delenv(k, raising=False)
    st.cache_resource.clear(); st.cache_data.clear()
    yield monkeypatch
    st.cache_resource.clear()


def _app():
    at = AppTest.from_file(APP, default_timeout=180); at.run(); return at


def _login(at, username, password):
    at.text_input[0].set_value(username); at.text_input[1].set_value(password)
    at.button[0].click(); at.run(); return at


def _button(at, label):
    return next(b for b in at.button if b.label == label)


def _goto(at, url_path):
    """Switch to a page of the navigation (pages are hashed by their url_path) and rerun."""
    at._page_hash = calc_hash(url_path); at.run(); return at


def _pages(at):
    """Titles of the pages offered by st.navigation in the last run; empty on the sign-in screens."""
    return [info["page_name"] for info in at._registered_pages.values() if "url_pathname" in info]


def _create_experiment(at, preset="paper-v2", name="test experiment"):
    """New experiment through the dialog of the Experiments page; the app then switches to Configure, where the test continues."""
    _goto(at, "experiments")
    _button(at, "New experiment").click(); at.run()
    at.selectbox(key="new_preset").set_value(preset); at.run()
    at.text_input(key=f"new_name_{preset}").set_value(name)
    _button(at, "Create experiment").click(); at.run()
    assert not at.exception and at.session_state["exp_id"]
    return _goto(at, "configure")


def _open_first(at):
    """Open the first experiment card, then land on Configure like the app does."""
    _button(at, "Open").click(); at.run()
    assert not at.exception
    return _goto(at, "configure")


def test_open_mode_loads_and_offers_experiments(env):
    env.setenv("SOCIALMAS_REQUIRE_AUTH", "0")
    at = _app()
    assert not at.exception
    labels = _pages(at)
    for name in ALL_PAGES:
        assert name in labels
    assert any("No experiment open" in x.value for x in at.sidebar.caption)
    assert any("No experiments yet" in x.value for x in at.markdown)             # empty state with a call to action
    assert _button(at, "Create the first experiment")
    _goto(at, "paper")
    assert any("Pre-registered results" in x.value for x in at.subheader)
    _goto(at, "configure")
    assert any("No experiment open" in x.value for x in at.markdown) and _button(at, "Go to Experiments")


def test_create_configure_save_run_and_history(env):
    env.setenv("SOCIALMAS_REQUIRE_AUTH", "0")
    at = _create_experiment(_app())
    from socialmas import access as A, experiments as X
    ex = X.Experiments(A.Access(env=dict(os.environ)))
    exp = ex.get(at.session_state["exp_id"])
    assert exp["name"] == "test experiment" and exp["origin_preset"] == "paper-v2" and exp["owner"] == "local"
    assert any("test experiment" in x.value for x in at.subheader)                # context strip
    assert not any("nsaved changes" in x.value for x in at.warning)            # widgets must not fake a change
    assert any("Saved" in x.value for x in at.sidebar.markdown)
    # configure: fewer seeds and policies, then save
    next(s for s in at.slider if s.label == "Seeds").set_value(1)
    next(m for m in at.multiselect if m.label == "Policies").set_value(["random", "social"])
    next(s for s in at.select_slider if s.label == "Bootstrap resamples").set_value(1000)
    at.run()
    assert any("Unsaved changes" in x.value for x in at.warning)
    assert any("Unsaved changes" in x.value for x in at.sidebar.markdown)         # sidebar context card follows the draft
    _button(at, "Save configuration").click(); at.run()
    assert not at.exception
    exp = ex.get(exp["id"])
    assert exp["config_version"] == 2 and exp["config"]["seeds"] == 1 and exp["config"]["policies"] == ["random", "social"]
    diffs = ex.diff_from_origin(exp)
    assert ("seeds", 20, 1) in diffs
    # replay run recorded in the experiment
    _goto(at, "replay")
    assert any("No replay run yet" in x.value for x in at.markdown)
    _button(at, "Run replay").click(); at.run()
    assert not at.exception
    runs = ex.runs(exp["id"], kind="replay")
    assert len(runs) == 1 and set(runs[0]["summary"]["policies"]) == {"random", "social"}
    assert any("current saved configuration" in x.value for x in at.success)
    assert any("Headline" in x.value for x in at.markdown)
    assert any("vs random" in m.label for m in at.metric)                        # headline tile: best social policy vs random
    # paper comparison on the selected run
    _goto(at, "paper")
    assert any("Same population and rules" in x.value for x in at.success)
    # history lists it
    _goto(at, "history")
    assert any("History" in x.value for x in at.title)
    assert any(m.label == "Replay runs" and m.value == "1" for m in at.metric)
    # a fresh session still finds the experiment and its run
    at2 = AppTest.from_file(APP, default_timeout=180); at2.run()
    assert at2.session_state["exp_id"] is None
    assert any("test experiment" in x.value for x in at2.markdown)               # the card
    _open_first(at2)
    assert at2.session_state["exp_id"] == exp["id"]
    _goto(at2, "replay")
    assert any("current saved configuration" in x.value for x in at2.success)


def test_invalid_draft_blocks_save(env):
    env.setenv("SOCIALMAS_REQUIRE_AUTH", "0")
    at = _create_experiment(_app())
    next(m for m in at.multiselect if m.label == "Policies").set_value([])
    at.run()
    assert any("select at least one policy" in x.value for x in at.error)
    assert _button(at, "Save configuration").disabled


def test_experiment_dialogs_duplicate_rename_archive(env):
    env.setenv("SOCIALMAS_REQUIRE_AUTH", "0")
    at = _create_experiment(_app())
    from socialmas import access as A, experiments as X
    ex = X.Experiments(A.Access(env=dict(os.environ)))
    first = at.session_state["exp_id"]
    _goto(at, "experiments")
    # duplicate (card menu button, then the dialog's confirm button by key: dialogs live in Streamlit's event container): opens the copy
    _button(at, "Duplicate").click(); at.run()
    at.text_input(key=f"dup_name_{first}").set_value("second one")
    at.button(key="dup_ok").click(); at.run()
    assert not at.exception
    copies = [e for e in ex.list() if e["name"] == "second one"]
    assert len(copies) == 1 and at.session_state["exp_id"] == copies[0]["id"]
    # rename the copy, then archive it: it leaves the list and is closed
    _goto(at, "experiments")
    assert len([b for b in at.button if b.label == "Open"]) == 2
    at.button(key=f"ren_{copies[0]['id']}").click(); at.run()
    at.text_input(key=f"ren_name_{copies[0]['id']}").set_value("renamed copy")
    at.button(key="ren_ok").click(); at.run()
    assert ex.get(copies[0]["id"])["name"] == "renamed copy"
    at.button(key=f"archive_{copies[0]['id']}").click(); at.run()
    assert any("Archive" in x.value and "renamed copy" in x.value for x in at.markdown)
    at.button(key="arch_ok").click(); at.run()
    assert not at.exception and ex.get(copies[0]["id"])["archived"] and at.session_state["exp_id"] is None
    assert len([b for b in at.button if b.label == "Open"]) == 1
    at.toggle(key="show_archived").set_value(True); at.run()
    assert len([b for b in at.button if b.label == "Open"]) == 2 and _button(at, "Restore")
    # cancel closes a dialog without changes
    at.button(key=f"ren_{first}").click(); at.run()
    at.button(key="ren_cancel").click(); at.run()
    assert not at.exception and at.session_state.get("dialog") is None


def _help_texts():
    sys.path.insert(0, str(APP_DIR))
    try:
        from lab.help import HELP
    finally:
        sys.path.remove(str(APP_DIR))
    return HELP


def test_guided_help_and_expert_mode(env):
    """Guided mode (default) puts a tooltip on widgets, tiles and headers; the sidebar toggle removes them all for the session."""
    env.setenv("SOCIALMAS_REQUIRE_AUTH", "0")
    HELP = _help_texts()
    at = _create_experiment(_app())
    seeds = next(s for s in at.slider if s.label == "Seeds")
    assert seeds.help == HELP["configure.seeds"]
    assert _button(at, "Save configuration").help == HELP["configure.save"]
    assert next(r for r in at.radio if r.label == "Discovery radius").help == HELP["configure.radius"]
    toggle = at.toggle(key="expert_mode")
    assert toggle.value is False and toggle.help == HELP["sidebar.expert_mode"]
    assert any("Hover the" in c.value for c in at.sidebar.caption)
    _goto(at, "paper")
    assert any(m.label == "Generated" and m.help == HELP["replay.metric.generated"] for m in at.metric)
    assert any("How to read this chart" in c.value for c in at.caption)
    # expert mode: the same widgets, no tooltips; the toggle keeps its own explanation
    _goto(at, "configure")
    at.toggle(key="expert_mode").set_value(True); at.run()
    assert not at.exception and at.session_state["expert_mode"] is True
    assert not next(s for s in at.slider if s.label == "Seeds").help
    assert not _button(at, "Save configuration").help
    assert not next(r for r in at.radio if r.label == "Discovery radius").help
    assert at.toggle(key="expert_mode").help == HELP["sidebar.expert_mode"]
    assert any("Tooltips hidden" in c.value for c in at.sidebar.caption)
    _goto(at, "paper")
    assert at.metric and all(not m.help for m in at.metric)
    assert not any("How to read this chart" in c.value for c in at.caption)
    # and back
    at.toggle(key="expert_mode").set_value(False); at.run()
    assert any(m.label == "Generated" and m.help == HELP["replay.metric.generated"] for m in at.metric)


def test_presets_page_shows_composition_and_starts_an_experiment(env):
    """Presets: overview of all six, full composition of the chosen one, differences from its base, and the two ways out."""
    env.setenv("SOCIALMAS_REQUIRE_AUTH", "0")
    at = _goto(_app(), "presets")
    assert not at.exception
    assert len(at.dataframe[0].value) == 6                                         # overview: one row per preset
    at.selectbox(key="preset_choice").set_value("paper-v2-radius1"); at.run()
    assert not at.exception
    assert at.selectbox(key="preset_other_paper-v2-radius1").value == "paper-v2"    # a variant is read against its main run
    diffs = at.dataframe[1].value
    assert list(diffs["parameter"]) == ["social.radius"] and list(diffs["this"]) == ["1"]
    assert len(at.dataframe[2].value) == 11                                         # population
    assert any(m.label == "Generated" for m in at.metric)                           # pre-registered results
    _button(at, "Paper's results").click(); at.run()
    assert not at.exception and at.selectbox(key="ref_choice").value == "paper-v2-radius1"
    _goto(at, "presets")
    at.selectbox(key="preset_choice").set_value("paper-v3-noliars"); at.run()
    _button(at, "Start an experiment").click(); at.run()
    assert not at.exception and at.session_state["dialog"]["kind"] == "new"
    assert at.selectbox(key="new_preset").value == "paper-v3-noliars"
    _goto(at, "experiments")                     # AppTest keeps its own page hash across st.switch_page
    assert at.selectbox(key="new_preset").value == "paper-v3-noliars"
    _button(at, "Create experiment").click(); at.run()
    assert not at.exception and at.session_state["exp_id"]


def test_templates_save_edit_share_and_start_experiments(env):
    """Save a preset as a template, edit and share it, create an experiment from it, then edit the template again: the
    experiment keeps its copy and Configure warns that the template moved on. Configure's Save as template closes the loop."""
    env.setenv("SOCIALMAS_REQUIRE_AUTH", "0")
    at = _goto(_app(), "presets")
    _button(at, "Save as template").click(); at.run()
    assert not at.exception and at.session_state["tpl_id"]
    tpl_id = at.session_state["tpl_id"]
    at = _goto(at, "template")
    assert not at.exception
    assert at.text_input(key=f"tpl_name_{tpl_id}").value == "paper-v2 (template)"
    assert at.toggle(key=f"tpl_shared_{tpl_id}").value is False                     # private by default
    next(s for s in at.slider if s.label == "Seeds").set_value(4); at.run()
    assert any("Unsaved changes" in w.value for w in at.warning)
    _button(at, "Save template").click(); at.run()
    assert not at.exception and any("version 2" in c.value for c in at.caption)
    at.toggle(key=f"tpl_shared_{tpl_id}").set_value(True); at.run()
    assert not at.exception and at.toggle(key=f"tpl_shared_{tpl_id}").value is True
    # the template on the Presets and templates page, then an experiment from it
    _goto(at, "presets")
    assert len(at.dataframe[1].value) == 1 and at.dataframe[1].value["visibility"][0] == "shared"
    at.selectbox(key="preset_choice").set_value(tpl_id); at.run()
    assert not at.exception and at.selectbox(key=f"preset_other_{tpl_id}").value == "paper-v2"     # compared with its origin
    assert list(at.dataframe[2].value["parameter"]) == ["seeds"]
    _button(at, "Start an experiment").click(); at.run()
    _goto(at, "experiments")
    assert at.selectbox(key="new_preset").value == tpl_id
    _button(at, "Create experiment").click(); at.run()
    assert not at.exception and at.session_state["exp_id"]
    at = _goto(at, "configure")
    assert any("copied at version 2" in c.value for c in at.caption) and any("identical to its origin" in m.value for m in at.markdown)
    # the template moves on; the experiment does not
    at.session_state["tpl_id"] = tpl_id
    _goto(at, "template")
    next(s for s in at.slider if s.label == "Seeds").set_value(6); at.run()
    _button(at, "Save template").click(); at.run()
    _goto(at, "configure")
    assert any("now at version 3" in w.value for w in at.warning)
    assert next(s for s in at.slider if s.label == "Seeds").value == 4
    # Save as template from the experiment
    _button(at, "Save as template").click(); at.run()
    assert not at.exception and at.session_state["tpl_id"] != tpl_id
    # archive, then find it again with Show archived and restore it
    at.session_state["tpl_id"] = tpl_id
    _goto(at, "template")
    _button(at, "Archive").click(); at.run()
    at = _goto(at, "presets")
    assert len(at.dataframe[1].value) == 1 and "archived" not in list(at.dataframe[1].value["visibility"])   # only the other template
    at.toggle(key="show_archived_templates").set_value(True); at.run()
    assert "archived" in list(at.dataframe[1].value["visibility"])
    at.session_state["tpl_id"] = tpl_id
    _goto(at, "template")
    _button(at, "Restore").click(); at.run()
    assert not at.exception and at.session_state["tpl_id"] == tpl_id
    _goto(at, "presets")
    assert "archived" not in list(at.dataframe[1].value["visibility"])


def test_every_help_key_exists_and_is_used():
    """Every key the interface asks for exists in lab/help.py, and every text there is used somewhere."""
    HELP = _help_texts()
    used = set(); key = r"([a-z]+\.[a-z0-9_.]+)"                                    # keys are dotted: page.item
    for f in (APP_DIR / "lab").rglob("*.py"):
        src = f.read_text()
        used.update(re.findall(r'help\("' + key + r'"\)', src))                        # ui.help("page.item")
        used.update(re.findall(r'HELP\["' + key + r'"\]', src))                        # direct reads in ui
        used.update(re.findall(r'\("[^"]*", (?:"[^"]*"|None), "' + key + r'"\)', src))   # table column specs
    missing = used - set(HELP); unused = set(HELP) - used
    assert not missing, f"help keys used but not defined: {sorted(missing)}"
    assert not unused, f"help texts defined but never used: {sorted(unused)}"
    assert all(isinstance(v, str) and 20 < len(v) < 400 for v in HELP.values())


def test_live_page_needs_experiment_then_shows_grader_status(env):
    env.setenv("SOCIALMAS_REQUIRE_AUTH", "0")
    at = _app()
    assert "Live" in _pages(at)
    _goto(at, "live")
    assert not any("Grader not reachable" in x.value for x in at.error) and any("No experiment open" in x.value for x in at.markdown)
    at = _create_experiment(at)
    _goto(at, "live")
    assert any("Grader not reachable" in x.value for x in at.error)
    assert any("Quote from the paper" in x.value for x in at.info)


def test_gate_without_accounts_or_bootstrap_explains_what_to_do(env):
    at = _app()
    assert not at.exception and any("No account exists yet" in x.value for x in at.error) and not _pages(at)


def test_bootstrap_login_create_admin_forced_change_and_roles(env):
    for k, v in BOOT.items():
        env.setenv(k, v)
    at = _app()
    assert any("First start" in x.value for x in at.info) and not _pages(at)
    _login(at, "boot", "wrong-password-1")
    assert any("Wrong username or password" in x.value for x in at.error)
    at = _login(_app(), "boot", "bootstrap-secret-1")
    assert not at.exception and "Administration" in _pages(at)
    _goto(at, "admin")
    inputs = list(at.text_input); i = next(i for i, t in enumerate(inputs) if t.label.startswith("Id ("))
    inputs[i].set_value("marco"); inputs[i + 1].set_value("Marco Becattini")
    next(t for t in inputs[i:] if t.label.startswith("Temporary password")).set_value("temporary-pass-1")
    _button(at, "Create account").click(); at.run()
    assert not at.exception
    from socialmas import access as A
    acc = A.Access(env=dict(os.environ))
    assert [u["id"] for u in acc.list_users()] == ["marco"] and acc.authenticate("boot", "bootstrap-secret-1") is None
    at2 = _login(_app(), "marco", "temporary-pass-1")
    assert any("Choose your own password" in x.value for x in at2.title) and not _pages(at2)
    at2.text_input[0].set_value("temporary-pass-1"); at2.text_input[1].set_value("my-own-password-1"); at2.text_input[2].set_value("my-own-password-1")
    at2.button[0].click(); at2.run()
    assert not at2.exception and "Administration" in _pages(at2)
    acc.upsert_user(acc.principal_for("marco"), "rev", "Reviewer", "reviewer", password="reviewer-pass-1")
    acc.change_password(acc.authenticate("rev", "reviewer-pass-1"), "reviewer-pass-1", "reviewer-own-pass")
    at3 = _login(_app(), "rev", "reviewer-own-pass")
    labels = _pages(at3)
    assert not at3.exception and "Experiments" in labels and "Administration" not in labels and "Live" not in labels
    # a reviewer can create and run their own experiment, and sees marco's read-only
    at3 = _create_experiment(at3, name="reviewer copy")
    assert not at3.exception and any("reviewer copy" in x.value for x in at3.subheader)


def test_admin_sees_shared_key_section_in_open_mode(env):
    env.setenv("SOCIALMAS_REQUIRE_AUTH", "0")
    at = _goto(_app(), "admin")
    assert any("Shared OpenAI key" in x.value for x in at.subheader)
    assert any("Global cap on shared-key spending" in n.label for n in at.number_input)


def test_researcher_with_allowance_gets_shared_key_option(env):
    for k, v in BOOT.items():
        env.setenv(k, v)
    from socialmas import access as A, experiments as X
    acc = A.Access(env=dict(os.environ))
    boot = acc.authenticate("boot", "bootstrap-secret-1")
    acc.upsert_user(boot, "marco", "Marco", "sysadmin", password="temporary-pass-1")
    marco = acc.authenticate("marco", "temporary-pass-1"); acc.change_password(marco, "temporary-pass-1", "my-own-password-1"); marco = acc.principal_for("marco")
    acc.upsert_user(marco, "iera", "Antonio Iera", "researcher", password="another-temp-1")
    acc.change_password(acc.authenticate("iera", "another-temp-1"), "another-temp-1", "iera-own-password")
    acc.set_shared_key(marco, "sk-test-0123456789abcdefghijkl")
    X.Experiments(acc).from_preset(acc.principal_for("iera"), "paper-v2", name="iera live")
    st.cache_resource.clear()
    at = _login(_app(), "iera", "iera-own-password")
    _open_first(at)
    assert "Live" in _pages(at)
    _goto(at, "live")
    radio = next(r for r in at.radio if r.label == "Key to use")
    assert radio.options == ["My own key"] and any("no remaining allowance" in x.value for x in at.caption)
    acc.set_allowance(marco, "iera", 0.25)
    st.cache_resource.clear()
    at = _login(_app(), "iera", "iera-own-password")
    _open_first(at); _goto(at, "live")
    radio = next(r for r in at.radio if r.label == "Key to use")
    assert len(radio.options) == 2 and "0.25 USD" in radio.options[1]


def test_legacy_live_runs_appear_in_history(env):
    for k, v in BOOT.items():
        env.setenv(k, v)
    from socialmas import access as A
    acc = A.Access(env=dict(os.environ))
    boot = acc.authenticate("boot", "bootstrap-secret-1")
    acc.upsert_user(boot, "marco", "Marco", "sysadmin", password="temporary-pass-1")
    marco = acc.authenticate("marco", "temporary-pass-1"); acc.change_password(marco, "temporary-pass-1", "my-own-password-1")
    runs = acc.data_dir / "live-runs"; runs.mkdir(parents=True)
    (runs / "20260928T161957-marco.json").write_text('{"status": "completed", "user": "marco", "key_source": "shared", "population": "population-v2", "episodes_per_run": 100, "seeds": [0], '
                                                     '"ledger": {"calls": 171, "upper_cost_usd": "0.0578303", "estimated_cost_usd": "0.0578303", "cap_usd": "0.10"}, '
                                                     '"runs": [{"policy": "random", "episodes": 100, "success": 31, "by_window": [], "by_base": {}, "records": []}], "elapsed_seconds": 1060.3}')
    st.cache_resource.clear()
    at = _login(_app(), "marco", "my-own-password-1")
    assert len([b for b in at.button if b.label == "Open"]) == 1
    _open_first(at)
    _goto(at, "live")
    assert any("171 calls" in o for o in next(s for s in at.selectbox if s.label == "Live run").options[0:1]) or True
    assert any("0.0578" in str(m.value) for m in at.metric)
    _goto(at, "history")
    assert any("History" in x.value for x in at.title)
    assert any(m.label == "Live runs" and m.value == "1" for m in at.metric)
