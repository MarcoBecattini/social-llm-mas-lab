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

Hosted: **https://social-llm-mas-lab.onrender.com** (Render free instance, Frankfurt; after a period without visitors the first request takes about a minute while the service wakes up). Locally:

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
| `render.yaml`, `Dockerfile` | deployment as a Render Web Service |

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

## Data, provenance and licence

- Code under the Apache License 2.0 (`LICENSE`).
- The bundled data hold task identifiers, the domain each task was drawn for, library names and per-model outcomes
  (pass/fail, upper cost, tokens). No prompts, tests or solutions of BigCodeBench are redistributed; the dataset itself
  is Apache-2.0. Raw traces stay in the research repository, excluded from distribution.
- Reference results are the paper's provenance files, unchanged, with the SHA-256 of the competence map they were
  produced from; `run_experiment` records the same hash.

## Roadmap

Live mode: the user enters an OpenAI key and a spending cap in the browser session, the app quotes the cost, reserves
before every call and stops at the cap; generated code is graded by a slim grader running as a Render Private Service
with no secrets. The pool of 121 unseen tasks used by the paper's live validation is already bundled.

## Citation

Becattini, M., Iera, A. Follow-up paper on social LLM multi-agent systems (in preparation). This repository:
https://github.com/MarcoBecattini/social-llm-mas-lab
