import json
import subprocess
import sys


def test_cli_run_and_report(tmp_path):
    out = tmp_path / "r.json"
    cmd = [sys.executable, "-m", "socialmas.cli", "run", "--preset", "paper-v2", "--seeds", "1", "--episodes", "300",
           "--output", str(out), "--log", str(tmp_path / "ep.jsonl")]
    subprocess.check_call(cmd)
    r = json.loads(out.read_text())
    assert r["config"]["seeds"] == 1 and len(r["policies"]) == 7
    assert sum(1 for _ in open(tmp_path / "ep.jsonl")) == 7 * 300
    md = subprocess.check_output([sys.executable, "-m", "socialmas.cli", "report", str(out)], text=True)
    assert "| `social` |" in md
    listing = subprocess.check_output([sys.executable, "-m", "socialmas.cli", "presets"], text=True)
    assert "paper-v3-liars" in listing
    assert subprocess.run([sys.executable, "-m", "socialmas.cli", "run", "--preset", "paper-v2", "--episodes", "250",
                           "--output", str(out)], capture_output=True).returncode == 2
