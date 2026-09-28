"""Smoke tests of the Streamlit app with Streamlit's AppTest: it loads, validates, runs a small replay and compares."""
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / "app" / "streamlit_app.py")


def _app():
    at = AppTest.from_file(APP, default_timeout=120)
    at.run()
    return at


def test_app_loads_with_paper_preset_and_reference_tab():
    at = _app()
    assert not at.exception
    assert at.session_state["preset"] == "paper-v2" and len(at.session_state["cfg"]["agents"]) == 11
    texts = " ".join(x.value for x in at.success)
    assert "Configuration valid" in texts
    assert any("Pre-registered results" in x.value for x in at.subheader)


def test_app_runs_small_replay_and_reports():
    at = _app()
    at.sidebar.slider[0].set_value(1)                      # seeds
    at.sidebar.multiselect[0].set_value(["random", "social"])
    at.sidebar.select_slider[1].set_value(1000)            # bootstrap
    at.sidebar.button[1].click()                           # Run replay (button 0 is Load preset)
    at.run()
    assert not at.exception
    r = at.session_state["results"]
    assert set(r["policies"]) == {"random", "social"} and r["config"]["seeds"] == 1 and r["config"]["episodes"] == 3000
    assert "social - random" in r["paired_differences"]
    assert any("Same population and rules" in x.value for x in at.success)


def test_app_flags_invalid_population():
    at = _app()
    at.sidebar.multiselect[0].set_value([])
    at.run()
    assert any("select at least one policy" in x.value for x in at.error)
