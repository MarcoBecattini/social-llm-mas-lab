"""Live mode without network: session ledger and cap, quote, executor against fake API and grader, run loop, pooled summary,
dataset module against the locally frozen parquet when available."""
import json
import os
from pathlib import Path

import pytest

from socialmas import bcb_data as B
from socialmas import data as D
from socialmas import live as L

PRICING = json.loads((D.DATA_DIR / "pricing.json").read_text())
LIVE_POOL = D.load_pool("bcb-live-pool.json")
CMAP = D.load_competence_map()
LOCAL_PARQUET = Path("/Users/marco/Evoluzione Paper Iera/followup/runtime/bcb/data/v0.1.4-00000-of-00001.parquet")


def fake_tasks():
    """Synthetic task records for the live pool ids: enough for prompts and grading calls, no benchmark content."""
    return {tid: {"task_id": tid, "instruct_prompt": f"Write task_func for {tid}. " * 10, "code_prompt": "import os\ndef task_func():\n",
                  "canonical_solution": "    return 1\n", "test": "import unittest\n", "entry_point": "task_func"} for tid in LIVE_POOL["task_order"]}


def api_response(model, inp=300, out=120, status="completed", cached=0, text="```python\nimport os\ndef task_func():\n    return 1\n```"):
    return {"id": "resp_1", "model": model, "status": status, "store": False,
            "usage": {"input_tokens": inp, "output_tokens": out, "total_tokens": inp + out, "input_tokens_details": {"cached_tokens": cached}},
            "output": [{"type": "message", "content": [{"type": "output_text", "text": text}]}]}


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code; self._payload = payload

    def json(self):
        return self._payload


class FakeSession:
    """Answers the OpenAI endpoint with a canned response and the grader with pass/fail from a rule."""

    def __init__(self, grade_rule=lambda body: "pass", api_status=200, api_payload=None):
        self.grade_rule = grade_rule; self.api_status = api_status; self.api_payload = api_payload; self.posts = []

    def post(self, url, json=None, headers=None, timeout=None, allow_redirects=True):
        self.posts.append((url, json, headers))
        if url.endswith("/grade"):
            return FakeResponse(200, {"status": self.grade_rule(json), "details": {}, "seconds": 0.01})
        assert headers["Authorization"].startswith("Bearer ") and json["store"] is False
        payload = self.api_payload or api_response(json["model"])
        return FakeResponse(self.api_status, payload)


def test_ledger_bound_admit_settle_and_cap():
    led = L.SessionLedger(PRICING, "0.01")
    b = led.bound("gpt-4.1-mini-2025-04-14", 900)
    assert 0.003 < float(b) < 0.004                                        # 2048 output tokens at 1.60 dominate
    led.admit("gpt-4.1-mini-2025-04-14", 900)
    e = led.settle("gpt-4.1-mini-2025-04-14", api_response("gpt-4.1-mini-2025-04-14", inp=1000, out=500))
    assert e["upper_cost_usd"] == "0.0012" and led.upper == L.Decimal("0.0012")
    for _ in range(2):
        led.admit("gpt-4.1-mini-2025-04-14", 900); led.settle("gpt-4.1-mini-2025-04-14", api_response("gpt-4.1-mini-2025-04-14", inp=1000, out=500))
    with pytest.raises(L.CapStop):                                         # the 4th further call would cross 0.01
        for _ in range(6):
            led.admit("gpt-4.1-mini-2025-04-14", 900); led.settle("gpt-4.1-mini-2025-04-14", api_response("gpt-4.1-mini-2025-04-14", inp=1000, out=500))
    assert led.upper <= led.cap
    with pytest.raises(L.LiveStop):
        led.settle("gpt-4.1-mini-2025-04-14", {"usage": {"input_tokens": -1}})
    assert led.blocked
    with pytest.raises(L.LiveStop):
        led.admit("gpt-4.1-nano-2025-04-14", 100)


def test_settle_accepts_truncated_and_rejects_wrong_model():
    led = L.SessionLedger(PRICING, "1")
    r = api_response("gpt-4.1-nano-2025-04-14", status="incomplete"); r["incomplete_details"] = {"reason": "max_output_tokens"}
    assert led.settle("gpt-4.1-nano-2025-04-14", r)["response_status"] == "incomplete"
    with pytest.raises(L.LiveStop):
        led.settle("gpt-4.1-nano-2025-04-14", api_response("gpt-4.1-mini-2025-04-14"))


def test_quote_matches_paper_rates():
    q = L.quote(PRICING, 300, [0, 1], ["random", "social"])
    assert q["episodes"] == 1200 and 1000 < q["expected_calls"] < 1060 and 0.25 < q["expected_upper_usd"] < 0.32
    assert q["suggested_cap_usd"] == round(q["expected_upper_usd"] * 2, 3)


def make_executor(session, cap="0.10", cfg=None):
    cfg = cfg or D.load_preset("paper-v2")
    led = L.SessionLedger(PRICING, cap)
    return L.HttpLiveExecutor("sk-test-not-real", PRICING, led, fake_tasks(), cfg["base_models"], "http://grader:10000", session=session), cfg


def test_executor_calls_api_then_grader_and_records():
    sess = FakeSession(grade_rule=lambda body: "pass" if "return 1" in body["solution"] else "fail")
    ex, cfg = make_executor(sess)
    rec = ex("mini", LIVE_POOL["task_order"][0])
    assert rec["success"] and rec["grade_status"] == "pass" and rec["model"] == "gpt-4.1-mini-2025-04-14" and rec["fenced"]
    assert ex.ledger.entries and float(rec["upper_cost_usd"]) > 0 and ex.calls == 1
    urls = [u for u, _, _ in sess.posts]
    assert urls == [PRICING["api"], "http://grader:10000/grade"]
    assert sess.posts[1][1]["solution"].startswith("import os\ndef task_func():\n\n    pass\n")  # calibrated solution


def test_executor_api_error_blocks_ledger_and_grader_error_is_recorded():
    ex, _ = make_executor(FakeSession(api_status=429))
    with pytest.raises(L.LiveStop):
        ex("nano", LIVE_POOL["task_order"][0])
    assert ex.ledger.blocked

    class GraderDown(FakeSession):
        def post(self, url, json=None, headers=None, timeout=None, allow_redirects=True):
            if url.endswith("/grade"):
                raise ConnectionError("down")
            return super().post(url, json, headers, timeout, allow_redirects)
    ex, _ = make_executor(GraderDown())
    rec = ex("nano", LIVE_POOL["task_order"][1])
    assert rec["grade_status"] == "grader_error" and not rec["success"] and rec["grader_error"] == "ConnectionError"


def test_run_live_completes_costs_zero_for_lazy_and_impostor_and_pools():
    sess = FakeSession(grade_rule=lambda body: "pass")
    ex, cfg = make_executor(sess, cap="5")
    seen = []
    res = L.run_live(cfg, CMAP, LIVE_POOL, ex, 100, [0], ["random", "social"], on_episode=lambda r, s: seen.append(r))
    assert res["status"] == "completed" and len(res["runs"]) == 2 and len(seen) == 200
    for r in res["runs"]:
        assert r["episodes"] == 100 and r["status"] == "completed" and r["by_window"][0]["n"] == 100
        for rec in r["records"]:
            if rec["effect"] in ("lazy", "impostor", "refused", "unfilled"):
                assert rec["cost"] == 0.0 and not rec["success"]
            if rec["effect"] == "call":
                assert rec["success"] and rec["grade_status"] == "pass" and float(rec["upper_cost_usd"]) > 0
    effects = {rec["effect"] for r in res["runs"] for rec in r["records"]}
    assert "call" in effects and ("lazy" in effects or "impostor" in effects)
    sched_random = [(r["requester"], r["domain"]) for r in res["runs"][0]["records"]]
    sched_social = [(r["requester"], r["domain"]) for r in res["runs"][1]["records"]]
    assert sched_random == sched_social                                       # same schedule per seed across policies
    p = L.pooled(res)
    assert set(p["policies"]) == {"random", "social"} and p["policies"]["social"]["episodes"] == 100
    assert all(v["live_rate"] == 1.0 for v in p["by_base"].values())
    assert res["ledger"]["calls"] == ex.calls == sum(r["calls"] for r in res["runs"])


def test_run_live_stops_at_cap_and_reports_partial():
    ex, cfg = make_executor(FakeSession(), cap="0.005")
    res = L.run_live(cfg, CMAP, LIVE_POOL, ex, 100, [0, 1], ["random", "social"])
    assert res["status"] == "cap_stop" and len(res["runs"]) == 1 and res["runs"][0]["status"] == "cap_stop"
    assert L.Decimal(res["ledger"]["upper_cost_usd"]) <= L.Decimal("0.005") and res["runs"][0]["episodes"] < 100


def test_dataset_module_verifies_hash_and_loads_only_pool_tasks(tmp_path):
    with pytest.raises(B.DatasetError):
        B.ensure_dataset(tmp_path, download=False)
    bad = tmp_path / "bad.parquet"; bad.write_bytes(b"not a parquet")
    with pytest.raises(B.DatasetError):
        B.ensure_dataset(tmp_path, download=False, source=bad)
    if not LOCAL_PARQUET.exists():
        pytest.skip("frozen parquet not available on this machine")
    path = B.ensure_dataset(tmp_path, download=False, source=LOCAL_PARQUET)
    assert path.exists() and B.sha256_file(path) == B.DATASET_SHA256
    tasks = B.load_tasks(path, LIVE_POOL["task_order"])
    assert len(tasks) == 121 and all(t["entry_point"] == "task_func" for t in tasks.values())
    msgs = B.build_messages(next(iter(tasks.values())))
    assert msgs[0]["role"] == "system" and msgs[1]["content"]
    assert B.extract_code("hello ```python\nx = 1\n``` bye") == "x = 1\n"
