# Social LLM-MAS Lab

Replay laboratory for **outcome-based trust and social discovery in a society of LLM agents**: the companion
application of the follow-up paper by Marco Becattini and Antonio Iera. Anyone, reviewers included, can change the
population of agents, the social graph, the trust rules and the selection policies, rerun the experiment, see curves,
tables and paired bootstrap comparisons, and check the numbers against the pre-registered runs of the paper.

Replay mode needs no API key: every worker is backed by an outcome table **measured once** with real models
(three OpenAI models on 350 BigCodeBench-Instruct tasks, graded by the official evaluator in an isolated container).
An agent's answer in a domain is replayed with replacement from its base model's row for that domain. Policies never
read that table: they see declarations, their own trust records, referral opinions and episode outcomes.

## Run it

Hosted: **https://social-llm-mas-lab.onrender.com** (Render, Starter instance, Frankfurt, always on). Locally:

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt && pip install -e .
streamlit run app/streamlit_app.py
```

With Docker:

```bash
docker build -t social-llm-mas-lab . && docker run --rm -p 8501:8501 social-llm-mas-lab
```

Command line, without the interface:

```bash
socialmas presets
socialmas run --preset paper-v2 --seeds 20 --output runs/v2.json
socialmas run --config my-population.json --seeds 5 --output runs/mine.json --log runs/mine-episodes.jsonl
socialmas report runs/v2.json
```

Tests: `pytest -q` (engine mechanics, determinism, no ground-truth leakage, exact reproduction of the paper's
per-seed numbers from the bundled data, runner, CLI and an `AppTest` smoke test of the interface).

## What is in the box

| Path | Content |
|---|---|
| `socialmas/sim.py` | the validated simulator of the paper, verbatim: `World`, `Trust`, policies, `run_policy`, `summarize`, `paired_bootstrap` |
| `socialmas/experiment.py` | `run_experiment(cfg)` with validation and progress; same results structure as the paper's provenance files |
| `socialmas/data/` | competence map (350 tasks × 3 models), pool manifests (350 + 121 unseen tasks), paper presets, reference results |
| `socialmas/report.py`, `socialmas/cli.py` | tables, Markdown report, command line |
| `app/streamlit_app.py` | the interface: population editor, rules, run with progress, results, paper comparison, data and method |
| `socialmas/live.py`, `socialmas/bcb_data.py` | live mode: session ledger with cap, HTTP executor, live world; dataset fetch and verification |
| `grader/` | grader service: vendored BigCodeBench evaluation, HTTP server, Dockerfile, feasibility gate |
| `render.yaml`, `Dockerfile` | deployment: web service plus grader Private Service on Render |

### Presets

| Preset | What it reproduces |
|---|---|
| `paper-v2` | main run: 11 agents, degree 3, radius 2, all 350 tasks, 7 policies, 20 seeds × 3,000 episodes |
| `paper-v2-radius1` | direct contacts only |
| `paper-v2-pool174` | the 174 tasks passed by at least one base model |
| `paper-v2-degree2-posthoc` | two initial contacts per agent (declared post-hoc) |
| `paper-v3-liars` | 30 agents, degree 2, four lying referrers, 8 policies including `social_refcheck` |
| `paper-v3-noliars` | the twin without liars |

The simulator is deterministic given the seed, and seed *i* of your run is seed *i* of the paper: with the same
population and rules, shared seeds reproduce the pre-registered per-seed numbers bit for bit (the test suite checks
it), so any difference you see after an edit is the effect of the edit, not noise.

### Profiles and policies

Profiles: `honest`, `boaster` (declares everything), `impostor` (declares everything, always fails, still bills),
`lazy` (empty answer with probability `lazy_p`), `specialist` (refuses outside its domains), `unstable` (alternating
honest and lazy phases), `liar` (honest worker, inverted and amplified referral reports).

Policies: `random`, `declared`, `social_noref` (own trust, no referrals), `social_nobefriend` (referrals, fixed graph),
`social` (trust, referrals weighted by trust in the referrer as a worker, new relationships after success),
`social_refcheck` (referrals weighted by the referrer's past referral accuracy). `best_fixed` and `oracle` are
reference lines that assume ground truth; they are not social policies.

## Accounts and roles

Everyone signs in (no public pages). The model is borrowed from Scala Radar:

- **Roles** are fixed bundles of capabilities: `sysadmin` (everything: accounts, access log, settings), `researcher`
  (replay, exports, and the coming live mode with a spending cap), `reviewer` (replay and exports). Every account has
  one role. Capabilities are checked in the app, not only hidden.
- **Accounts are created by a SysAdmin** in the Administration tab: id (lowercase slug, immutable), name, role and a
  temporary password. No self sign-up, no email. The person must choose their own password at the first login;
  until then everything else is blocked. Passwords are PBKDF2-SHA256 (600,000 iterations), at least 10 characters.
- **First start**: set `SOCIALMAS_ADMIN_USER` and `SOCIALMAS_ADMIN_PASSWORD` in the environment, sign in with them and
  create your own SysAdmin account. That bootstrap credential stops working as soon as the first account exists. The
  last active administrator cannot be deactivated, demoted or removed; prefer deactivation to removal.
- **Sessions** are a signed cookie (`{sub, iat, exp}`, 12 hours) verified on every page load; sign-out, an admin
  password reset, a self-service password change and deactivation invalidate older sessions immediately.
- **Audit**: account changes, password changes, sign-ins and failed sign-ins are appended to an access log visible
  to SysAdmins.
- **Storage**: one SQLite file in `SOCIALMAS_DATA_DIR` (on Render the 1 GB disk mounted at `/var/data`; locally
  `./data`). Without a persistent disk the app runs but warns that accounts will not survive a redeploy. The session
  secret comes from `SOCIALMAS_SESSION_SECRET` or is generated once and kept in the database.
- Local development without accounts: `SOCIALMAS_REQUIRE_AUTH=0` (ignored on Render).

## Data, provenance and licence

- Code under the Apache License 2.0 (`LICENSE`).
- The bundled data hold task identifiers, the domain each task was drawn for, library names and per-model outcomes
  (pass/fail, upper cost, tokens). No prompts, tests or solutions of BigCodeBench are redistributed; the dataset itself
  is Apache-2.0. Raw traces stay in the research repository, excluded from distribution.
- Reference results are the paper's provenance files, unchanged, with the SHA-256 of the competence map they were
  produced from; `run_experiment` records the same hash.

## Live mode

Accounts with the `live.run` capability (researchers and administrators) get a **Live** tab: the same population, graph,
trust rules and policies as the replay, but every honest-type execution is a real call to the user's **own OpenAI
key** on one of the 121 out-of-sample tasks of the paper's live validation, graded by the grader service before the
trust update. The app quotes the expected cost from the paper's live run, and a **session ledger** refuses any call
whose realistic worst cost would cross the user's cap, so the cap is never exceeded. Lazy shirking, impostor and
refused episodes make no call. The key lives in the server-side session memory for the run only; requests carry
`store: false`; nothing about the key is logged. Results, the calls ledger and the episode log can be downloaded; a
sanitized copy of each run is kept under `live-runs/` on the data disk for administrators.

The tasks themselves are not in this repository: on first use the app downloads the BigCodeBench v0.1.4 parquet
(2.3 MB, Apache-2.0) from Hugging Face into the data directory and verifies it against the SHA-256 frozen by the
paper (`socialmas/bcb_data.py`).

### Grader service

`grader/` is a slim image with the official BigCodeBench evaluation code vendored unchanged (`untrusted_check`, same
commit as the paper) and the upstream pinned libraries minus the heavy runtimes the pools exclude. It exposes
`POST /grade` and `GET /healthz`, runs as an unprivileged user, holds no secrets, and is deployed as a Render Private
Service reachable only from the workspace's other services (`GRADER_URL`, optional shared `GRADER_TOKEN`). The
feasibility gate of the paper (canonical solution passes, empty body fails) is reproduced on it for the live pool
with `grader/gate.py`.

## Citation

Becattini, M., Iera, A. Follow-up paper on social LLM multi-agent systems (in preparation). This repository:
https://github.com/MarcoBecattini/social-llm-mas-lab
