"""
Stage 5: Git History Mining (FR-7).

Parses `git log` to get, per file, a commit count and days-since-last-
modified. These feed the recency/frequency score in scoring.py. If the
source isn't a git repository at all, every file simply gets a neutral
(zero) recency score rather than the pipeline failing.
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

_COMMIT_MARKER = "\x01"


@dataclass
class FileGitStats:
    commits: int = 0
    days_since_last: float | None = None  # None => never seen in history


def is_git_repo(root: Path) -> bool:
    return (root / ".git").exists()


def get_commit_stats(root: Path) -> dict[str, FileGitStats]:
    """
    Returns relpath -> FileGitStats for every file that appears anywhere
    in the repo's commit history (files with no history simply won't be
    keys in the returned dict).

    OPTIMIZED: Single git invocation (not per-file), parse once in Python.
    Avoids subprocess overhead that was causing 15-40s on Windows for large repos.
    """
    if not is_git_repo(root):
        return {}

    try:
        # Single git log call for entire repo; includes all history (even shallow clones will show what they have)
        result = subprocess.run(
            [
                "git", "-C", str(root), "log",
                f"--pretty=format:{_COMMIT_MARKER}%at",
                "--name-only",
                "--since=2 years ago",  # Safety: avoid repos with extremely deep history
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,  # Prevent hang on pathological repos
        )
    except (subprocess.CalledProcessError, OSError, subprocess.TimeoutExpired):
        return {}

    stats: dict[str, FileGitStats] = {}
    current_ts: int | None = None
    now = time.time()

    for line in result.stdout.splitlines():
        if not line:
            continue
        if line.startswith(_COMMIT_MARKER):
            try:
                current_ts = int(line[len(_COMMIT_MARKER):])
            except ValueError:
                current_ts = None
            continue

        relpath = line.strip()
        if not relpath or current_ts is None:
            continue

        entry = stats.setdefault(relpath, FileGitStats())
        entry.commits += 1
        days_ago = (now - current_ts) / 86400.0
        if entry.days_since_last is None or days_ago < entry.days_since_last:
            entry.days_since_last = days_ago

    return stats
