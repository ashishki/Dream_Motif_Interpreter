from copy import deepcopy
from pathlib import Path
import subprocess
import sys

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
CI_WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"
WORKFLOW_PATHS = tuple(sorted((REPO_ROOT / ".github" / "workflows").glob("*.y*ml")))
PINNED_OFFICIAL_ACTIONS = {
    "actions/checkout": "9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0",
    "actions/setup-python": "ece7cb06caefa5fff74198d8649806c4678c61a1",
}


def iter_uses_nodes(value: object):
    if isinstance(value, dict):
        if isinstance(value.get("uses"), str):
            yield value
        for child in value.values():
            yield from iter_uses_nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_uses_nodes(child)


def assert_workflow_security(workflow: dict) -> int:
    assert workflow["permissions"] == {"contents": "read"}
    assert all("permissions" not in job for job in workflow["jobs"].values())

    action_nodes = list(iter_uses_nodes(workflow))
    assert action_nodes
    for node in action_nodes:
        action, separator, revision = node["uses"].partition("@")
        assert separator == "@"
        assert action in PINNED_OFFICIAL_ACTIONS
        assert revision == PINNED_OFFICIAL_ACTIONS[action]
        if action == "actions/checkout":
            assert node.get("with", {}).get("persist-credentials") is False
    return len(action_nodes)


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
    action_count = 0

    assert WORKFLOW_PATHS
    for workflow_path in WORKFLOW_PATHS:
        workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
        action_count += assert_workflow_security(workflow)

    assert action_count == 8
    assert "scripts/eval_public_fixture.py" in workflow_text
    assert "dream_motif_public_retrieval_v1.json" in workflow_text


@pytest.mark.parametrize(
    "mutation",
    (
        "mutable_pin",
        "broad_top_level",
        "job_override",
        "persist_missing",
        "persist_true",
        "unapproved_action",
    ),
)
def test_ci_security_guard_rejects_unsafe_mutations(mutation: str) -> None:
    workflow = yaml.safe_load(CI_WORKFLOW_PATH.read_text(encoding="utf-8"))
    mutated = deepcopy(workflow)
    action_nodes = list(iter_uses_nodes(mutated))
    checkout = next(node for node in action_nodes if node["uses"].startswith("actions/checkout@"))

    if mutation == "mutable_pin":
        checkout["uses"] = "actions/checkout@v7"
    elif mutation == "broad_top_level":
        mutated["permissions"] = {"contents": "write"}
    elif mutation == "job_override":
        next(iter(mutated["jobs"].values()))["permissions"] = {"contents": "write"}
    elif mutation == "persist_missing":
        checkout["with"].pop("persist-credentials")
    elif mutation == "persist_true":
        checkout["with"]["persist-credentials"] = True
    else:
        next(iter(mutated["jobs"].values()))["steps"].append(
            {"uses": "untrusted/example@0123456789abcdef"}
        )

    with pytest.raises(AssertionError):
        assert_workflow_security(mutated)
