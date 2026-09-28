"""Data and method: what the replay uses, where it comes from, and under which licence."""
import pandas as pd
import streamlit as st

from socialmas import data as D

from .. import charts, ui

TITLE = "Data and method"


def render():
    cmap = D.load_competence_map()
    ui.page_header(TITLE, ["Reference", TITLE], "The measured outcome table behind every replay, and the provenance of the bundled data.", help=ui.help("method.page"))
    with ui.card("What the replay uses"):
        st.markdown(
            "Every worker in the simulation is backed by a **measured** outcome table: three OpenAI models answered the same 350 "
            "BigCodeBench-Instruct tasks (50 drawn per domain, seven domains), graded by the official evaluator in an isolated container, "
            "at temperature 0. An agent's answer in a domain is replayed with replacement from its base model's row for that domain. "
            "Policies never read this table: they see declarations, their own trust records, referral opinions and episode outcomes. "
            "Only the two reference lines (`best_fixed`, `oracle`) assume ground truth.")
    ui.chart(charts.map_chart(cmap), help=ui.help("method.map"))
    ui.table(pd.DataFrame([{"model": m, "tasks": v["tasks"], "passed": v["passed"], "pass_rate": v["pass_rate"], "cost": float(v["upper_cost_usd"])}
                           for m, v in cmap["models"].items()]),
             {"model": "Model", "tasks": ("Tasks", "%d"), "passed": ("Passed", "%d"), "pass_rate": ("Pass rate", "%.3f", "method.models.pass_rate"),
              "cost": ("Upper cost USD (350 tasks)", "%.4f", "method.models.cost")}, help=ui.help("method.models"))
    comp = cmap["complementarity"]
    st.caption(f"Tasks solved by k of the three models: {comp['solved_by_k_models']}. Map generated {cmap['generated_utc'][:10]}; "
               f"manifest sha256 {cmap['manifest_sha256'][:12]}.")
    with ui.card("Provenance and licence", help=ui.help("method.provenance")):
        st.markdown(
            "- Code: Apache-2.0. Data files: task identifiers, domains, library names and per-model outcomes only; no prompts, tests or "
            "solutions of BigCodeBench are redistributed (the dataset itself is Apache-2.0).\n"
            "- Reference results are the pre-registered runs of the paper, byte for byte; every preset reproduces them from the bundled map "
            "because the simulator is deterministic given the seed.\n"
            "- The live pool of 121 unseen tasks used for the paper's live validation is bundled for the live mode.\n"
            "- Source and issues: https://github.com/MarcoBecattini/social-llm-mas-lab")
