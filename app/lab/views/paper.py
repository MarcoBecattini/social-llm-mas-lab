"""Paper comparison: the pre-registered results of the paper, and the open experiment's selected replay run against them."""
import pandas as pd
import streamlit as st

from socialmas import data as D
from socialmas.experiment import compare_to_reference, rules_signature
from socialmas.report import differences_frame, headline_frame, windows_frame

from .. import charts, results, state, ui
from ..state import policy_label

TITLE = "Paper comparison"


def _default_index():
    exp = state.current_experiment(); names = D.preset_names()
    return names.index(exp["origin_preset"]) if exp and exp.get("origin_preset") in names else 0


def render():
    ui.page_header(TITLE, ["Reference", TITLE], "The pre-registered runs of the paper, byte for byte, and how the open experiment's selected replay run compares.")
    st.subheader("Pre-registered results of the paper", anchor=False)
    c1, c2 = st.columns([2, 3], vertical_alignment="center")
    ref_name = c1.selectbox("Reference run", D.preset_names(), index=_default_index(), format_func=lambda n: D.PRESETS[n]["label"], key="ref_choice")
    ref = D.load_reference(ref_name)
    c2.caption(D.PRESETS[ref_name]["description"] + f" Generated {ref['generated_utc'][:10]}; competence map sha256 {ref['competence_map_sha256'][:12]}.")
    ui.tiles(results.replay_tiles(ref, reference=True))
    hf = headline_frame(ref)
    ui.table(hf.assign(policy=hf["policy"].map(policy_label)), results.HEADLINE_COLUMNS)
    st.plotly_chart(charts.forest_chart(differences_frame(ref), "Paired differences, paper run"), width="stretch")
    c1, c2 = st.columns(2)
    with c1:
        st.plotly_chart(charts.line_chart(windows_frame(ref, "success_by_window"), "Success over time, paper run", "success rate"), width="stretch")
    with c2:
        st.plotly_chart(charts.line_chart(windows_frame(ref, "unreliable_share_by_window"), "Unreliable selections, paper run", "share of selections", yrange=[0, None]), width="stretch")
    if ref_name.startswith("paper-v3"):
        cmpv3 = D.load_reference_file("social-v3-compare.json")
        with ui.card("Liars against the twin without liars", "Paired by seed."):
            rows = [("damage to social: no liars − liars", cmpv3["damage_social_noliars_minus_liars"]),
                    ("damage to social_refcheck: no liars − liars", cmpv3["refcheck_noliars_minus_liars"]),
                    ("defence with liars: refcheck − social", cmpv3["defence_refcheck_minus_social_with_liars"]),
                    ("defence cost without liars: refcheck − social", cmpv3["defence_cost_refcheck_minus_social_without_liars"])]
            ui.table(pd.DataFrame([{"comparison": n, "points": v["mean_points"], "ci_low": v["ci95"][0], "ci_high": v["ci95"][1],
                                    "seeds_positive": f"{v['seeds_positive']}/{v['n']}"} for n, v in rows]),
                     {"comparison": "Comparison", "points": ("Points", "%+.2f"), "ci_low": ("CI 95% low", "%+.2f"), "ci_high": ("CI 95% high", "%+.2f"), "seeds_positive": "Seeds positive"})
            rw = cmpv3["referral_weight_by_referrer"]
            st.caption(f"Referral weight learned by `social_refcheck`: honest referrers {rw['honest_referrer']}, liars {rw['liar']}.")
    res = state.selected_replay_results()
    if not res:
        return
    exp = state.current_experiment()
    st.subheader(f"{exp['name']}: selected replay run against this reference", anchor=False)
    cmp = compare_to_reference(res, ref)
    same_cfg = rules_signature(res["config"]) == rules_signature(ref["config"])
    ui.table(pd.DataFrame([{"policy": policy_label(p), "run": v["run_mean"], "paper": v["reference_mean"], "delta": v["delta_points"],
                            "shared": v["shared_seeds"], "exact": v["exact_on_shared_seeds"]} for p, v in cmp.items()]),
             {"policy": "Policy", "run": ("Your run", "%.3f"), "paper": ("Paper", "%.3f"), "delta": ("Delta, points", "%+.2f"),
              "shared": ("Shared seeds", "%d"), "exact": ("Identical on shared seeds", "bool")})
    if same_cfg and res["config"]["episodes"] == ref["config"]["episodes"]:
        st.success("Same population and rules as the paper: shared seeds are identical, as the simulator is deterministic." if all(v["exact_on_shared_seeds"] for v in cmp.values())
                   else "Same configuration but different per-seed numbers: please report this as a bug.", icon=":material/check:")
    else:
        st.info("Your configuration differs from the paper's (population, rules or episodes), so the deltas measure your change, not noise.", icon=":material/difference:")
