"""Cheap repeatable checks, separate from the optional browser smoke."""

from pathlib import Path
import re
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_workspace_inline_javascript_parses(tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node unavailable; run scripts/smoke_kolia_workspace.py with Chromium")
    shell = (ROOT / "app/static/dream_memory_map.html").read_text()
    script = tmp_path / "workspace.js"
    script.write_text("\n".join(re.findall(r"<script>([\s\S]*?)</script>", shell)))
    subprocess.run([node, "--check", str(script)], check=True, capture_output=True, timeout=10)


def test_shell_does_not_persist_private_archive_in_browser_storage():
    shell = (ROOT / "app/static/dream_memory_map.html").read_text()
    assert "localStorage" not in shell and "sessionStorage" not in shell
    assert 'id="archive-tab"' in shell and 'id="research-form"' in shell
    assert 'type="password"' not in shell
    assert 'id="reader-note-form"' in shell
    assert "new AbortController()" in shell
    assert "state.reviewEpoch" in shell
