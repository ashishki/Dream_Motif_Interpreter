from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_public_fixture_and_contribution_boundary_is_explicit() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    policy = (ROOT / "docs" / "PUBLIC_FIXTURE_PRIVACY.md").read_text(encoding="utf-8")
    form = (ROOT / ".github" / "ISSUE_TEMPLATE" / "bounded-adapter-test.yml").read_text(
        encoding="utf-8"
    )
    config = (ROOT / ".github" / "ISSUE_TEMPLATE" / "config.yml").read_text(encoding="utf-8")
    security = (ROOT / "SECURITY.md").read_text(encoding="utf-8")

    assert "template=bounded-adapter-test.yml" in readme
    assert "authored-synthetic fixtures" in readme
    policy_lower = " ".join(policy.casefold().split())
    for marker in (
        "do not start from private text and redact it",
        "generic feature requests",
        "failing-then-passing regression",
        "not a general anonymity guarantee",
    ):
        assert marker in policy_lower
    for field_id in (
        "revision",
        "contribution_type",
        "contract",
        "reproduction",
        "fixture_provenance",
        "execution_boundary",
        "verification",
        "confirmations",
    ):
        assert f"id: {field_id}" in form
    assert "not a redaction, paraphrase, or transformation" in form
    assert "Live provider/private archive" not in form
    assert "email-first private route" in policy
    assert "GitHub private vulnerability reporting is not assumed" in policy
    assert "blank_issues_enabled: false" in config
    assert "security/policy" in config
    assert "security/advisories/new" not in config
    assert "GitHub private vulnerability reporting is not assumed" in security
    assert "cannot promise a response or remediation deadline" in " ".join(security.split())
