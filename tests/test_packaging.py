"""Every data file the package reads must be tracked by git and declared as package data, so that the hosted image,
built from the repository, ships it. Guards against the ignore-rule accident of 28 September 2026."""
import subprocess
from pathlib import Path

import pytest

from socialmas import data as D

ROOT = Path(__file__).resolve().parents[1]


def _tracked():
    try:
        out = subprocess.check_output(["git", "-C", str(ROOT), "ls-files", "socialmas/data"], text=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        pytest.skip("not a git checkout")
    return set(out.split())


def test_all_data_files_are_tracked_by_git():
    tracked = _tracked()
    files = sorted(p.relative_to(ROOT).as_posix() for p in D.DATA_DIR.rglob("*.json"))
    missing = [f for f in files if f not in tracked]
    assert files and not missing, f"untracked package data (check .gitignore): {missing}"


def test_package_data_patterns_cover_every_data_file():
    import tomllib
    cfg = tomllib.loads((ROOT / "pyproject.toml").read_text())
    patterns = cfg["tool"]["setuptools"]["package-data"]["socialmas"]
    pkg = ROOT / "socialmas"
    for p in D.DATA_DIR.rglob("*.json"):
        rel = p.relative_to(pkg).as_posix()
        assert any(Path(rel).match(pat) for pat in patterns), f"{rel} matches no package-data pattern {patterns}"
