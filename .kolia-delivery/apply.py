"""Temporary branch-only publication of an exact, hash-verified offline source tree."""
import base64
import ctypes
import ctypes.util
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

BRANCH = "codex/kolia-experience-v1"
BASE = "d9c271a541de1a75e98bd7178bef0d104fe053f7"
TARGET_TREE = "41577720ddd0c55f7d2e275cf11c98db9d579f4c"
DICT_SHA = "16a90f4f85f07ce1bb7b4f7745b173a997f810dbb21d8caae18250fee03f8af4"
PAYLOAD_SHA = "7ea13a929381cd81260c30eb72e633c862141d6a062b4dc1e47e1a95f103a8ed"
PATHS = '''.env.example
README.md
app/api/motifs.py
app/api/workspace.py
app/assistant/chat.py
app/assistant/prompts.py
app/assistant/selection.py
app/assistant/session.py
app/main.py
app/services/archive_research.py
app/static/dream_memory_map.html
app/telegram/handlers.py
app/workers/transcribe.py
docs/KOLIA_EXPERIENCE_ACCEPTANCE_RU.md
docs/KOLIA_EXPERIENCE_V1.md
docs/PRODUCT_OVERVIEW.md
docs/USER_GUIDE_RU.md
docs/adr/ADR-012-kolia-selection-and-workspace.md
docs/handoffs/END_TO_END_HARDENING_HANDOFF.md
docs/handoffs/KOLIA_EXPERIENCE_V1_HANDOFF.md
scripts/smoke_kolia_workspace.py
tests/unit/test_archive_research.py
tests/unit/test_assistant_chat.py
tests/unit/test_experience_selection.py
tests/unit/test_experience_workflows.py
tests/unit/test_motifs_api.py
tests/unit/test_telegram_bot.py
tests/unit/test_voice_selection_context.py
tests/unit/test_workspace_api.py
tests/unit/test_workspace_shell_syntax.py'''.splitlines()


def git(*args):
    return subprocess.check_output(["git", *args]).decode().strip()


def source(path):
    result = subprocess.run(["git", "show", f"{BASE}:{path}"], capture_output=True)
    if result.returncode != 0:
        assert not git("ls-tree", BASE, "--", path)
        return b""
    return result.stdout


def decode(directory):
    olds = [source(path) for path in PATHS]
    dictionary = json.dumps(
        [{"path": path, "text": old.decode()} for path, old in zip(PATHS, olds)],
        ensure_ascii=False, separators=(",", ":"),
    ).encode()
    assert hashlib.sha256(dictionary).hexdigest() == DICT_SHA, "baseline dictionary changed"
    chunks = [(directory / f"chunk-{i}.b64").read_text().strip() for i in range(4)]
    # Reconstruct one omitted transport span, then verify the complete immutable payload.
    assert len(chunks[1]) == 14813
    chunks[1] = chunks[1][:908] + (
        "GmqsDxhhYTlyJo/m56w6MjpDGmtQMamTHI1NCdu/5e40NLpwPvc+mhY8bXzwINIUbojWb/fYwTd5jGaZachhmHFSjEaj6Uw1x4Ou8cTxTnB7q3DJCgaByqNu3B62UFtSbfg/FrwjzyzhO5o54ugpUolBdzXANNmno2mnk8lMpLOjEUcCxGQNcNmP5w/"
    ) + chunks[1][908:]
    encoded = "".join(chunks)
    compressed = base64.b64decode(encoded, validate=True)
    assert len(compressed) == 37533
    library = ctypes.util.find_library("zstd")
    assert library, "libzstd is required only by this temporary offline transport"
    zstd = ctypes.CDLL(library)
    zstd.ZSTD_createDCtx.restype = ctypes.c_void_p
    zstd.ZSTD_freeDCtx.argtypes = [ctypes.c_void_p]
    zstd.ZSTD_freeDCtx.restype = ctypes.c_size_t
    zstd.ZSTD_decompress_usingDict.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p,
        ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t,
    ]
    zstd.ZSTD_decompress_usingDict.restype = ctypes.c_size_t
    context = zstd.ZSTD_createDCtx()
    assert context
    output = ctypes.create_string_buffer(691526)
    try:
        size = zstd.ZSTD_decompress_usingDict(
            context, output, len(output), compressed, len(compressed), dictionary, len(dictionary)
        )
    finally:
        zstd.ZSTD_freeDCtx(context)
    assert size == 691526, "decompression failed or payload size changed"
    raw = output.raw[:size]
    assert hashlib.sha256(raw).hexdigest() == PAYLOAD_SHA, "source payload changed"
    files = json.loads(raw)
    assert [item["path"] for item in files] == PATHS
    for item, old in zip(files, olds):
        assert hashlib.sha256(old).hexdigest() == item["base"]
        content = item["text"].encode() if item["text"] is not None else None
        assert (hashlib.sha256(content).hexdigest() if content is not None else None) == item["new"]
    return files


def main():
    directory = Path(os.getenv("DELIVERY_DIR", ".kolia-delivery"))
    files = decode(directory)
    if "--verify-only" in sys.argv:
        for item in files:
            expected = item["text"].encode() if item["text"] is not None else None
            actual = Path(item["path"]).read_bytes() if Path(item["path"]).exists() else None
            assert expected == actual, item["path"]
        print("PASS: all 30 source files match the locally tested tree")
        return
    assert os.getenv("GITHUB_REF") == f"refs/heads/{BRANCH}", "wrong branch"
    assert git("status", "--porcelain") == "", "dirty checkout"
    initial_head = git("rev-parse", "HEAD")
    assert initial_head == os.getenv("GITHUB_SHA"), "unexpected runner head"
    subprocess.run(["git", "merge-base", "--is-ancestor", BASE, "HEAD"], check=True)
    changed = git("diff", "--name-only", BASE, "HEAD").splitlines()
    assert all(p.startswith(".kolia-delivery/") or p == ".github/workflows/kolia-deliver.yml" for p in changed), changed
    git("config", "user.name", "Artem Shishkin")
    git("config", "user.email", "33684107+ashishki@users.noreply.github.com")
    workspace = {
        "app/api/motifs.py", "app/api/workspace.py", "app/main.py",
        "app/static/dream_memory_map.html", "tests/unit/test_motifs_api.py",
        "tests/unit/test_workspace_api.py", "tests/unit/test_workspace_shell_syntax.py",
        "scripts/smoke_kolia_workspace.py",
    }
    groups = [
        ("feat: preserve conversational selections and ground bounded archive research", lambda p: p not in workspace and p.startswith(("app/", "tests/"))),
        ("feat: add task-first archive workspace and complete human review queue", lambda p: p in workspace),
        ("docs: publish Kolia user journeys and release acceptance gates", lambda p: p.startswith("docs/") or p in {"README.md", ".env.example"}),
    ]
    applied = set()
    for message, accepts in groups:
        paths = []
        for item in files:
            path = item["path"]
            if not accepts(path):
                continue
            assert path not in applied
            current = Path(path).read_bytes() if Path(path).exists() else b""
            assert hashlib.sha256(current).hexdigest() == item["base"], path
            if item["text"] is None:
                Path(path).unlink()
            else:
                Path(path).parent.mkdir(parents=True, exist_ok=True)
                Path(path).write_bytes(item["text"].encode())
            paths.append(path)
            applied.add(path)
        git("add", "--", *paths)
        git("commit", "-m", message)
    assert applied == set(PATHS)
    git("rm", "-r", "--", ".kolia-delivery")
    git("commit", "-m", "chore: remove temporary offline source transport")
    # Native connector removes workflows separately; GITHUB_TOKEN does not edit them.
    saved_head = git("rev-parse", "HEAD")
    git("rm", "--cached", "--", ".github/workflows/kolia-source-snapshot.yml", ".github/workflows/kolia-deliver.yml")
    assert git("write-tree") == TARGET_TREE, "candidate source tree differs from tested tree"
    git("read-tree", saved_head)
    assert git("status", "--porcelain") == ""
    remote = git("ls-remote", "origin", f"refs/heads/{BRANCH}").split()[0]
    assert remote == initial_head, "remote changed; refusing to overwrite"
    git("push", "origin", f"HEAD:refs/heads/{BRANCH}")
    print("Published branch-only source commits:", saved_head)
    print("Verified reviewed tree after native workflow cleanup:", TARGET_TREE)


if __name__ == "__main__":
    main()
