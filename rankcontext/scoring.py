"""
Stage 7: Composite Scoring (FR-9), including the documentation/config
boost (FR-15).

CORRECTED FORMULA (v2.0):
  raw_score(file) = w1*centrality + w2*recency   (all normalized, NO token cost)
  boosted_score(file) = raw_score(file) * boost_factor(file)

REASONING:
  Token cost is a cost-efficiency factor, not an intrinsic quality signal.
  Including it here (Stage 7) + dividing by tokens in Stage 8 (selection.py)
  caused a double-penalty that systematically starved large, important files.

  Stage 7 should measure pure structural importance (centrality + recency only).
  Stage 8 (greedy_select) handles cost-efficiency via smoothed ratio:
    score_per_token = boosted_score / (tokens + k), where k ~ 500

See REVIEW.md Issue #3 for detailed explanation of the fix.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import PurePosixPath

from .config import boost_factor
from .git_history import FileGitStats

RECENCY_HALF_LIFE_DAYS = 30.0


@dataclass
class FileScore:
    relpath: str
    centrality: float
    recency: float
    tokens: int
    token_norm: float
    raw_score: float
    boosted_score: float
    boost: float


def _min_max_normalize(values: dict[str, float]) -> dict[str, float]:
    if not values:
        return {}
    lo, hi = min(values.values()), max(values.values())
    if math.isclose(hi, lo):
        return {k: 0.0 for k in values}
    span = hi - lo
    return {k: (v - lo) / span for k, v in values.items()}


def compute_recency_scores(
    git_stats: dict[str, FileGitStats], all_files: list[str]
) -> dict[str, float]:
    """
    Combine commit frequency and last-touched recency into one 0..1
    score per file. Files with no git history at all score 0 - they
    are neither penalized nor favored beyond that.
    """
    commit_counts = {f: git_stats[f].commits for f in all_files if f in git_stats}
    commit_norm = _min_max_normalize(commit_counts)

    recency_decay: dict[str, float] = {}
    for f in all_files:
        stats = git_stats.get(f)
        if stats is None or stats.days_since_last is None:
            continue
        # Exponential decay: recently touched -> close to 1, old -> close to 0.
        recency_decay[f] = math.exp(-stats.days_since_last / RECENCY_HALF_LIFE_DAYS)

    combined: dict[str, float] = {}
    for f in all_files:
        c = commit_norm.get(f, 0.0)
        r = recency_decay.get(f, 0.0)
        combined[f] = 0.5 * c + 0.5 * r
    return combined


def compute_scores(
    all_files: list[str],
    centrality: dict[str, float],
    recency: dict[str, float],
    token_counts: dict[str, int],
    weights: tuple[float, float, float],
) -> dict[str, FileScore]:
    w1, w2, w3 = weights

    centrality_norm = _min_max_normalize({f: centrality.get(f, 0.0) for f in all_files})
    recency_norm = _min_max_normalize({f: recency.get(f, 0.0) for f in all_files})
    token_norm = _min_max_normalize({f: float(token_counts.get(f, 0)) for f in all_files})

    # FIXED: Remove token cost from raw score (Stage 7).
    # Token cost is a cost-efficiency factor, not an intrinsic quality signal.
    # Including it here causes double-penalty when combined with Stage 8's per-token division.
    # Stage 7 should measure pure structural importance: centrality + recency.
    raw_scores = {
        f: (w1 * centrality_norm.get(f, 0.0)
            + w2 * recency_norm.get(f, 0.0))
        for f in all_files
    }

    # IMPORTANT: do NOT min-max normalize raw_scores to 0..1 before
    # applying the boost. That would floor the lowest-scoring file to
    # exactly 0, and 0 * any boost is still 0 - silently defeating the
    # documentation/config boost for exactly the files (thin READMEs,
    # rarely-imported manifests) it exists to rescue. Instead, shift
    # raw scores to a small positive floor first, boost that, and only
    # normalize to 0..1 for display AFTER boosting.
    min_raw = min(raw_scores.values()) if raw_scores else 0.0
    epsilon = 0.01
    shifted = {f: v - min_raw + epsilon for f, v in raw_scores.items()}

    boosted_raw = {
        f: shifted[f] * boost_factor(PurePosixPath(f).name)
        for f in all_files
    }
    boosted_norm = _min_max_normalize(boosted_raw)
    raw_norm = _min_max_normalize(raw_scores)  # kept for display/debugging only

    results: dict[str, FileScore] = {}
    for f in all_files:
        filename = PurePosixPath(f).name
        boost = boost_factor(filename)
        base = raw_norm.get(f, 0.0)
        results[f] = FileScore(
            relpath=f,
            centrality=centrality_norm.get(f, 0.0),
            recency=recency_norm.get(f, 0.0),
            tokens=token_counts.get(f, 0),
            token_norm=token_norm.get(f, 0.0),
            raw_score=base,
            boosted_score=boosted_norm.get(f, 0.0),
            boost=boost,
        )
    return results
