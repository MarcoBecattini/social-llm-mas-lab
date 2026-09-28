"""Feasibility gate for a running grader: for every task of a pool manifest, the canonical solution must pass and an empty
body must fail, exactly as the paper's gate on the official image. Reads the frozen dataset parquet (never redistributed)."""
import argparse
import hashlib
import json
import sys
import time

import pandas as pd
import requests

DATASET_SHA256 = "d9a4965821c9507ebdfb551c288656b2d5fe553234f5183044333ca8a4018267"


def grade(url, token, solution, test, entry_point):
    r = requests.post(url.rstrip("/") + "/grade", json={"solution": solution, "test": test, "entry_point": entry_point},
                      headers={"X-Grader-Token": token} if token else {}, timeout=180)
    r.raise_for_status()
    return r.json()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="http://localhost:10000"); p.add_argument("--token", default="")
    p.add_argument("--parquet", required=True); p.add_argument("--pool", required=True)
    p.add_argument("--limit", type=int, default=0); p.add_argument("--output", default="")
    a = p.parse_args()
    if hashlib.sha256(open(a.parquet, "rb").read()).hexdigest() != DATASET_SHA256:
        sys.exit("dataset hash mismatch")
    frame = pd.read_parquet(a.parquet).set_index("task_id")
    pool = json.load(open(a.pool)); order = pool["task_order"][: a.limit or None]
    rows = []; bad = 0; t0 = time.time()
    for i, tid in enumerate(order, 1):
        row = frame.loc[tid]
        canonical = row["code_prompt"] + row["canonical_solution"]
        empty = row["code_prompt"] + "\n    pass\n"
        c = grade(a.url, a.token, canonical, row["test"], row["entry_point"])
        e = grade(a.url, a.token, empty, row["test"], row["entry_point"])
        ok = c["status"] == "pass" and e["status"] != "pass"
        bad += not ok
        rows.append({"task_id": tid, "canonical": c["status"], "empty": e["status"], "ok": ok,
                     "seconds": round(c["seconds"] + e["seconds"], 3), "canonical_details": c["details"] if c["status"] != "pass" else {}})
        print(f"[{i}/{len(order)}] {tid} canonical={c['status']} empty={e['status']} {'OK' if ok else 'MISMATCH'}", flush=True)
    summary = {"tasks": len(rows), "ok": len(rows) - bad, "mismatches": bad, "elapsed_seconds": round(time.time() - t0, 1),
               "grader": requests.get(a.url.rstrip("/") + "/healthz", timeout=30).json(), "rows": rows}
    if a.output:
        json.dump(summary, open(a.output, "w"), indent=2)
    print(json.dumps({k: v for k, v in summary.items() if k != "rows"}, indent=2))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
