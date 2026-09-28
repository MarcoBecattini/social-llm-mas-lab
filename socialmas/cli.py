"""Command line: run a preset or a configuration file, print a Markdown report, list presets.

    python -m socialmas.cli presets
    python -m socialmas.cli run --preset paper-v2 --seeds 2 --episodes 600 --output out.json
    python -m socialmas.cli run --config my-population.json --output out.json --log episodes.jsonl
    python -m socialmas.cli report out.json
"""
import argparse
import json
import sys
import time
from pathlib import Path

from . import data as D
from .experiment import run_experiment, validate_config
from .report import markdown_report


def main(argv=None):
    parser = argparse.ArgumentParser(prog="socialmas")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("presets", help="list the paper presets")
    r = sub.add_parser("run", help="run a preset or a configuration file")
    g = r.add_mutually_exclusive_group(required=True)
    g.add_argument("--preset", choices=D.preset_names())
    g.add_argument("--config", help="path to a population configuration (same schema as the presets)")
    r.add_argument("--seeds", type=int); r.add_argument("--episodes", type=int)
    r.add_argument("--pool", choices=["all", "discriminating"]); r.add_argument("--radius", type=int, choices=[1, 2])
    r.add_argument("--degree", type=int); r.add_argument("--label", default="")
    r.add_argument("--output", required=True); r.add_argument("--log", help="write one JSON line per episode here")
    p = sub.add_parser("report", help="print Markdown tables for a results file")
    p.add_argument("results")
    args = parser.parse_args(argv)
    if args.cmd == "presets":
        for name, spec in D.PRESETS.items():
            print(f"{name:26} {spec['label']}")
        return 0
    if args.cmd == "report":
        print(markdown_report(json.loads(Path(args.results).read_text())))
        return 0
    cfg = D.load_preset(args.preset) if args.preset else json.loads(Path(args.config).read_text())
    if args.seeds: cfg["seeds"] = args.seeds
    if args.episodes: cfg["episodes"] = args.episodes
    if args.pool: cfg["task_pool"]["rule"] = args.pool
    if args.radius: cfg["social"]["radius"] = args.radius
    if args.degree: cfg["graph"]["degree"] = args.degree
    cfg["run_label"] = args.label
    cmap = D.load_map_for(cfg)
    problems = validate_config(cfg, cmap)
    if problems:
        print("configuration problems:\n- " + "\n- ".join(problems), file=sys.stderr)
        return 2
    t0 = time.perf_counter()
    def progress(done, total, policy, seed):
        print(f"\r{done}/{total} {policy} seed {seed}   ", end="", file=sys.stderr, flush=True)
    log = open(args.log, "w") if args.log else None
    try:
        results = run_experiment(cfg, cmap, progress=progress, log=log)
    finally:
        if log: log.close()
    print(file=sys.stderr)
    for pol, v in results["policies"].items():
        print(pol, json.dumps({k: v[k] for k in ("success_rate", "cost_per_success_usd", "messages_per_episode")}))
    out = Path(args.output); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2) + "\n")
    print(f"written {out} in {time.perf_counter() - t0:.1f}s", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
