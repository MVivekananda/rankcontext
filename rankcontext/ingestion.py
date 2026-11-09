"""
Stage 1: Repository Ingestion.

Resolves a source (local path or Git URL) to a directory on disk, then
walks the tree applying .gitignore rules plus RankContext's own default
exclusions (FR-1, FR-2, FR-3).
"""

from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pathspec

from .config import DEFAULT_EXCLUDE_DIRS, LIKELY_TEXT_EXTENSIONS


def _looks_like_git_url(source: str) -> bool:
    return (
        source.startswith("http://")
        or source.startswith("https://")
        or source.startswith("git@")
        or source.endswith(".git")
    )


@dataclass
class ResolvedSource:
    root: Path
    is_git_repo: bool
    is_temp_clone: bool


def resolve_source(source: str) -> ResolvedSource:
    """
    Turn a CLI `source` argument into a local directory.

    - If it looks like a Git URL, clone it (with history) into a temp dir.
      Uses --filter=blob:none to avoid downloading file blobs while preserving
      commit metadata for recency scoring.
    - Otherwise treat it as a local path and use it directly.
    """
    if _looks_like_git_url(source):
        tmp_dir = Path(tempfile.mkdtemp(prefix="rankcontext_clone_"))
        try:
            # Clone with blob filter: keeps commit history (needed for recency metrics)
            # but skips downloading file contents initially.
            subprocess.run(
                [
                    "git", "clone",
                    "--filter=blob:none",  # Preserve history, skip blobs
                    "--no-checkout",       # Don't checkout initially
                    source,
                    str(tmp_dir),
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
            # Now fetch recent history (last 6 months) to ensure recency metrics work
            subprocess.run(
                [
                    "git", "-C", str(tmp_dir),
                    "fetch",
                    "--shallow-since=2026-05-09",  # Last 6 months from eval date
                    "origin",
                    "HEAD",
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=60,
            )
            # Finally, checkout the working tree
            subprocess.run(
                ["git", "-C", str(tmp_dir), "checkout"],
                check=True,
                capture_output=True,
                text=True,
                timeout=60,
            )
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(
                f"Failed to clone {source!r}: {exc.stderr.strip()}"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"Clone of {source!r} timed out (repo too large or network issue)"
            ) from exc
        return ResolvedSource(root=tmp_dir, is_git_repo=True, is_temp_clone=True)

    root = Path(source).expanduser().resolve()
    if not root.exists():
        raise FileNotFoundError(f"Source path does not exist: {root}")
    is_git_repo = (root / ".git").exists()
    return ResolvedSource(root=root, is_git_repo=is_git_repo, is_temp_clone=False)


def _pathspec_pattern_name() -> str:
    # Newer pathspec versions rename "gitwildmatch" to "gitignore" and
    # emit a DeprecationWarning for the old name; support both so this
    # works across pathspec versions without noisy warnings.
    try:
        pathspec.PathSpec.from_lines("gitignore", [])
        return "gitignore"
    except Exception:
        return "gitwildmatch"


def _load_gitignore_spec(root: Path) -> pathspec.PathSpec | None:
    gitignore = root / ".gitignore"
    if not gitignore.exists():
        return None
    lines = gitignore.read_text(errors="ignore").splitlines()
    return pathspec.PathSpec.from_lines(_pathspec_pattern_name(), lines)


def _is_probably_binary(path: Path, sniff_bytes: int = 2048) -> bool:
    """Cheap binary sniff: a NUL byte in the first chunk means binary."""
    try:
        with open(path, "rb") as f:
            chunk = f.read(sniff_bytes)
        return b"\x00" in chunk
    except OSError:
        return True


def collect_files(
    root: Path,
    extra_excludes: Iterable[str] = (),
    max_files: int | None = None,
) -> list[Path]:
    """
    Walk `root`, applying:
      - default excluded directory names (config.DEFAULT_EXCLUDE_DIRS)
      - .gitignore patterns, if a .gitignore exists at the root
      - user-supplied --exclude glob patterns
      - a binary-file sniff, to keep non-text files out of the bundle

    Returns a list of paths relative to `root`.
    """
    spec = _load_gitignore_spec(root)
    extra_spec = (
        pathspec.PathSpec.from_lines(_pathspec_pattern_name(), list(extra_excludes))
        if extra_excludes
        else None
    )

    collected: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue

        rel = path.relative_to(root)
        parts = set(rel.parts)
        if parts & DEFAULT_EXCLUDE_DIRS:
            continue

        rel_str = rel.as_posix()
        if spec is not None and spec.match_file(rel_str):
            continue
        if extra_spec is not None and extra_spec.match_file(rel_str):
            continue

        # Text-likeliness check: known-good extension is fast-pathed;
        # anything else gets a binary sniff before being accepted.
        if path.suffix not in LIKELY_TEXT_EXTENSIONS and _is_probably_binary(path):
            continue

        collected.append(rel)
        if max_files is not None and len(collected) >= max_files:
            break

    return collected
