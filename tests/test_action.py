import os
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def run_action(tmp_path: Path, **env: str) -> subprocess.CompletedProcess[str]:
    """Run action.yml's run step with a merge-flow stub that records its argv."""
    script = yaml.safe_load((ROOT / "action.yml").read_text())["runs"]["steps"][2]["run"]
    stub = tmp_path / "bin" / "merge-flow"
    stub.parent.mkdir()
    stub.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$ARGV_OUT"\n')
    stub.chmod(0o755)
    output = tmp_path / "github_output"
    output.touch()
    full = {
        **os.environ,
        "PATH": f"{stub.parent}{os.pathsep}{os.environ['PATH']}",
        "RUNNER_TEMP": str(tmp_path),
        "GITHUB_OUTPUT": str(output),
        "ARGV_OUT": str(tmp_path / "argv"),
        "MF_MODE": "plan",
        "MF_WINDOW": "",
        "MF_BASE": "main",
        "MF_PRS": "",
        "MF_CHECKS": "",
        **env,
    }
    return subprocess.run(["bash", "-c", script], env=full, capture_output=True, text=True, check=False)


def test_plan_passes_prs_and_checks(tmp_path):
    result = run_action(tmp_path, MF_PRS="12,15", MF_CHECKS="tests")
    assert result.returncode == 0, result.stderr
    plan = str(tmp_path / "merge-flow-plan.json")
    argv = (tmp_path / "argv").read_text().splitlines()
    assert argv == ["--base", "main", "--json", plan, "--prs", "12,15", "--checks", "tests"]


def test_land_refuses_prs(tmp_path):
    # land merges every PR its window holds; a prs list there would look like a filter and do nothing.
    result = run_action(tmp_path, MF_MODE="land", MF_WINDOW="42", MF_PRS="12")
    assert result.returncode == 2
    assert "::error::" in result.stdout
    assert not (tmp_path / "argv").exists()
