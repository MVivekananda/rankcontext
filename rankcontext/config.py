"""
Central configuration: default exclusions, boost rules, and default weights.
Keeping these in one place makes the scoring behaviour easy to explain
and defend (see PRD section 16, Viva Defense Notes).
"""

from __future__ import annotations

# Directories that are always skipped, regardless of .gitignore content.
# These are near-universally noise for LLM context purposes.
DEFAULT_EXCLUDE_DIRS = {
    ".git", ".hg", ".svn",
    "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    "node_modules", "venv", ".venv", "env", ".env",
    "build", "dist", "site-packages", ".tox",
    ".idea", ".vscode", "target", "out",
}

# File extensions we treat as text/source and are willing to include.
# Anything not in this set is checked with a binary sniff instead of a
# hard reject, so uncommon-but-valid text files still get a chance.
LIKELY_TEXT_EXTENSIONS = {
    ".py", ".pyi", ".md", ".rst", ".txt", ".toml", ".cfg", ".ini",
    ".yaml", ".yml", ".json", ".js", ".jsx", ".ts", ".tsx", ".html",
    ".css", ".sh", ".bash", ".sql", ".proto", ".java", ".go", ".rs",
    ".c", ".h", ".cpp", ".hpp", ".rb", ".php",
}

# Filenames that get a documentation/manifest boost applied after the
# base composite score is computed (PRD section 7.4).
BOOST_RULES = [
    # (glob-style prefix match, boost factor)
    (("README", "ARCHITECTURE", "CONTRIBUTING"), 2.5),
    (("package.json", "pyproject.toml", "setup.py", "setup.cfg",
      "requirements.txt", "Cargo.toml", "go.mod"), 1.5),
]

DEFAULT_WEIGHTS = (0.5, 0.3, 0.2)  # centrality, recency, token_cost

# Hard cap referenced by NFR "Performance" - analyze up to ~2000 files
# within a few minutes on a standard laptop.
DEFAULT_MAX_FILES = 2000

# Files larger than this are still scored but flagged; guards against a
# single huge generated file dominating the walk.
MAX_FILE_BYTES_FOR_FULL_READ = 2_000_000  # 2 MB


def boost_factor(filename: str) -> float:
    """Return the multiplicative boost for a given (base) filename."""
    for prefixes, factor in BOOST_RULES:
        for p in prefixes:
            if filename == p or filename.startswith(p + "."):
                return factor
    return 1.0
