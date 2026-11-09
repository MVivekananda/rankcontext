"""
Stage 8: Budgeted Selection (FR-10, FR-11).

Greedy score-per-token fill: sort all candidate files by
boosted_score / tokens descending, then add them to the bundle one at a
time until the next file would exceed the token budget. This is the
standard greedy approximation to 0/1 knapsack - O(n log n), not
worst-case optimal, but the right trade-off here (see PRD section 7.5
and the viva notes on why greedy over exact knapsack).
"""

from __future__ import annotations

from dataclasses import dataclass

from .scoring import FileScore


@dataclass
class SelectionResult:
    included: list[FileScore]
    excluded: list[tuple[FileScore, str]]  # (file, reason)
    used_tokens: int


def greedy_select(scores: dict[str, FileScore], budget: int) -> SelectionResult:
    def score_per_token(fs: FileScore) -> float:
        # FIXED: Use smoothed ratio to avoid double-penalty and prevent
        # tiny files from dominating due to division by near-zero token counts.
        # The smoothing constant k (~500) is typical token count, chosen to:
        # - Avoid 1-token files getting infinite score/token ratio
        # - Prevent large files from being systematically starved
        # - Give cost-efficiency some weight without inverting the system
        k = 500
        return fs.boosted_score / (fs.tokens + k)

    ordered = sorted(scores.values(), key=score_per_token, reverse=True)

    included: list[FileScore] = []
    excluded: list[tuple[FileScore, str]] = []
    used = 0

    for fs in ordered:
        if fs.tokens > budget:
            excluded.append((fs, "excluded (single file exceeds remaining budget)"))
            continue
        if used + fs.tokens > budget:
            excluded.append((fs, "excluded (low score/token ratio)"))
            continue
        included.append(fs)
        used += fs.tokens

    return SelectionResult(included=included, excluded=excluded, used_tokens=used)
