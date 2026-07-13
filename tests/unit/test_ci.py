from pathlib import Path
import subprocess
import sys

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
CI_WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"
PINNED_OFFICIAL_ACTIONS = {
    "actions/checkout": "9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0",
    "actions/setup-python": "ece7cb06caefa5fff74198d8649806c4678c61a1",
}


def test_ci_workflow_has_required_jobs() -> None:
    workflow = yaml.safe_load(CI_WORKFLOW_PATH.read_text(encoding="utf-8"))
    jobs = workflow["jobs"]

    assert any("install" in job_name for job_name in jobs), jobs.keys()
    assert "ruff-check" in jobs
    assert "ruff-format" in jobs
    assert "pytest" in jobs


def test_ruff_check_passes() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "app/", "scripts/", "tests/"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_ci_uses_read_only_defaults_and_checks_public_evidence() -> None:
    workflow_text = CI_WORKFLOW_PATH.read_text(encoding="utf-8")
    workflow = yaml.safe_load(workflow_text)
    action_steps = [
        step for job in workflow["jobs"].values() for step in job["steps"] if "uses" in step
    ]

    assert workflow["permissions"] == {"contents": "read"}
    assert all("permissions" not in job for job in workflow["jobs"].values())
    assert len(action_steps) == 8
    for step in action_steps:
        action, separator, revision = step["uses"].partition("@")
        assert separator == "@"
        assert action in PINNED_OFFICIAL_ACTIONS
        assert revision == PINNED_OFFICIAL_ACTIONS[action]
        if action == "actions/checkout":
            assert step.get("with", {}).get("persist-credentials") is False
    assert "scripts/eval_public_fixture.py" in workflow_text
    assert "dream_motif_public_retrieval_v1.json" in workflow_text
