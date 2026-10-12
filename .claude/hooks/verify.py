"""Claude Code Stop hook: refuse to finish while lint, format or tests fail.

Wired up in `.claude/settings.json`. Claude Code pipes the hook's JSON on
stdin when Claude is about to end its turn. This script:

1. Exits 0 straight away when `CLAUDE_SKIP_VERIFY=1` is set.
2. Works out which checkout to verify: the session's `cwd` from the hook
   input (which follows Claude into a git worktree), falling back to
   `CLAUDE_PROJECT_DIR` and then to this file's own checkout.
3. Fingerprints the working tree (tracked and untracked files, minus ignored
   ones) as a git tree id. If it matches the fingerprint cached at
   `git rev-parse --git-path claude-verified`, nothing changed since the last
   green run, so it exits 0 without running anything. On a clean checkout the
   fingerprint is simply HEAD's tree, so committing verified work does not
   trigger a re-run.
4. Otherwise runs `uv run ruff check`, `uv run ruff format --check` and
   `uv run pytest -q -x`, stopping at the first failure. On failure it prints
   the tail of that command's output to stderr and exits 2, which tells Claude
   Code to keep Claude working. On success it caches the fingerprint and
   exits 0.

Problems with the hook itself (no git, no uv) exit 1: Claude Code shows the
message to the user but does not block.

Standard library only, so it runs under `uv run --no-project python`, `py`
or `python3` on Windows (Git Bash or PowerShell) and Linux alike.

Try it by hand:

    echo '{"hook_event_name":"Stop","cwd":"."}' | python .claude/hooks/verify.py
"""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

CHECKS = [
    ["uv", "run", "ruff", "check"],
    ["uv", "run", "ruff", "format", "--check"],
    ["uv", "run", "pytest", "-q", "-x"],
]
TAIL_LINES = 40
CHECK_TIMEOUT = 300


def read_input() -> dict:
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except (ValueError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def git(repo: pathlib.Path, *args: str, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    return result.stdout.strip()


def find_repo(hook_input: dict) -> pathlib.Path | None:
    candidates = [
        hook_input.get("cwd"),
        os.environ.get("CLAUDE_PROJECT_DIR"),
        str(pathlib.Path(__file__).resolve().parents[2]),
    ]
    for candidate in candidates:
        if not candidate or not pathlib.Path(candidate).is_dir():
            continue
        try:
            top = pathlib.Path(git(pathlib.Path(candidate), "rev-parse", "--show-toplevel"))
        except (subprocess.CalledProcessError, OSError):
            continue
        if (top / "pyproject.toml").is_file():
            return top
    return None


def git_path(repo: pathlib.Path, name: str) -> pathlib.Path:
    path = pathlib.Path(git(repo, "rev-parse", "--git-path", name))
    return path if path.is_absolute() else repo / path


def fingerprint(repo: pathlib.Path) -> str:
    """Tree id of the working tree as `git add -A` would stage it.

    Uses a throwaway copy of the index so the real one is never touched.
    """
    with tempfile.TemporaryDirectory() as scratch:
        index = pathlib.Path(scratch) / "index"
        real_index = git_path(repo, "index")
        if real_index.is_file():
            shutil.copyfile(real_index, index)
        env = {**os.environ, "GIT_INDEX_FILE": str(index)}
        git(repo, "add", "-A", env=env)
        return git(repo, "write-tree", env=env)


def tail(text: str) -> str:
    lines = text.rstrip().splitlines()
    return "\n".join(lines[-TAIL_LINES:])


def main() -> int:
    hook_input = read_input()

    if os.environ.get("CLAUDE_SKIP_VERIFY") == "1":
        return 0

    if shutil.which("git") is None:
        print("verify hook: git not found on PATH; skipping verification", file=sys.stderr)
        return 1
    repo = find_repo(hook_input)
    if repo is None:
        print("verify hook: no git checkout with a pyproject.toml found", file=sys.stderr)
        return 1
    if shutil.which("uv") is None:
        print("verify hook: uv not found on PATH; skipping verification", file=sys.stderr)
        return 1

    try:
        cache = git_path(repo, "claude-verified")
        current = fingerprint(repo)
    except (subprocess.CalledProcessError, OSError) as exc:
        print(f"verify hook: could not read git state: {exc}", file=sys.stderr)
        return 1

    try:
        if cache.read_text(encoding="utf-8").strip() == current:
            return 0
    except OSError:
        pass

    env = {**os.environ, "NO_COLOR": "1", "PYTHONIOENCODING": "utf-8"}
    for command in CHECKS:
        try:
            result = subprocess.run(
                command,
                cwd=repo,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=CHECK_TIMEOUT,
                check=False,
            )
        except subprocess.TimeoutExpired:
            print(f"`{' '.join(command)}` timed out after {CHECK_TIMEOUT}s.", file=sys.stderr)
            return 2
        if result.returncode != 0:
            print(
                f"Verification failed: `{' '.join(command)}` exited {result.returncode} "
                f"in {repo}. Fix this before finishing (or report it to the user "
                f"if it cannot be fixed). Output tail:\n{tail(result.stdout)}",
                file=sys.stderr,
            )
            return 2

    try:
        cache.write_text(current + "\n", encoding="utf-8")
    except OSError as exc:
        print(f"verify hook: checks passed but could not cache result: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
