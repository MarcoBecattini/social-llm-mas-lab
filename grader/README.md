# Grader service

`POST /grade` with `{"solution": ..., "test": ..., "entry_point": ..., "min_time_limit": 1, "gt_time_limit": 20}` returns
`{"status": "pass|fail|timeout", "details": {...}, "seconds": ...}`; `GET /healthz` returns version and load.
The evaluation code is vendored from BigCodeBench (see `bigcodebench_eval/VENDORED.md`), the libraries are the
upstream pins for everything the paper's pools import. Deployed on Render as a Private Service: reachable only from
the workspace's other services; no secrets, unprivileged user, per-check process with resource limits.

Local run: `docker build --platform linux/amd64 -t socialmas-grader grader && docker run --rm -p 10000:10000 socialmas-grader`.
Feasibility gate against a running grader: `python grader/gate.py --url http://localhost:10000 --parquet <v0.1.4 parquet> --pool socialmas/data/bcb-live-pool.json`.
