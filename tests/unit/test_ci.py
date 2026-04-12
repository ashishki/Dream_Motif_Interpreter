from pathlib import Path
import subprocess

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
CI_WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def test_ci_workflow_has_required_jobs() -> None:
    workflow = yaml.safe_load(CI_WORKFLOW_PATH.read_text(encoding="utf-8"))
    jobs = workflow["jobs"]

    assert any("install" in job_name for job_name in jobs), jobs.keys()
    assert "ruff-check" in jobs
    assert "ruff-format" in jobs
    assert "pytest" in jobs


def test_ruff_check_passes() -> None:
    result = subprocess.run(
        ["ruff", "check", "app/", "tests/"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
