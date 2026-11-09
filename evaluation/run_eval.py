"""
Evaluation: RankContext (ranked) vs a gitingest-style flat/alphabetical
dump, at the same token budget, per PRD section 14.

What this measures, per repo, per budget:
  - avg centrality of the included set        (higher = denser in
                                                 structurally important files)
  - top-decile hit rate                        (what fraction of the
                                                 repo's most-central files
                                                 made it into the budget)
  - whether README / top-level docs made it in
  - files included, tokens used

The flat baseline mimics gitingest's actual behaviour: walk the tree in
sorted path order and keep appending whole files until the next one
would exceed the budget - no ranking signal at all.

Repos used: real, on-disk Python source trees (Flask and NetworkX, via
their installed packages) plus RankContext's own repo. This sandbox has
no network access to `git clone` arbitrary GitHub repos, so these stand
in as the "small / medium / large" real-world repos the PRD's
evaluation plan calls for. Flask/NetworkX are installed via pip, so
they have no .git directory - recency contributes 0 for them, meaning
their ranked selection is driven by centrality + token cost + the
doc/config boost only. RankContext's own repo does have real git
history, so it demonstrates the recency signal too.

Run with:  python3 evaluation/run_eval.py
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rankcontext import ast_parser, git_history, graph, ingestion, scoring, tokens
from rankcontext.config import DEFAULT_WEIGHTS


@dataclass
class EvalRow:
    repo: str
    budget: int
    method: str
    files_included: int
    total_files: int
    tokens_used: int
    avg_centrality_included: float
    top_decile_hit_rate: float
    readme_included: bool


def flat_select(all_files: list[str], token_counts: dict[str, int], budget: int) -> list[str]:
    """gitingest-style baseline: sorted path order, fill until budget exhausted."""
    included = []
    used = 0
    for f in sorted(all_files):
        cost = token_counts.get(f, 0)
        if used + cost > budget:
            continue  # gitingest keeps walking and skips files that don't fit, doesn't stop early
        included.append(f)
        used += cost
    return included


def ranked_select(scores, budget: int) -> list[str]:
    from rankcontext.selection import greedy_select
    result = greedy_select(scores, budget)
    return [fs.relpath for fs in result.included]


def evaluate_repo(repo_path: Path, repo_label: str, budgets: list[int]) -> list[EvalRow]:
    files = ingestion.collect_files(repo_path, max_files=2000)
    file_strs = [f.as_posix() for f in files]
    parse_results = ast_parser.parse_all(repo_path, files)

    import_graph = graph.build_import_graph(parse_results, file_strs)
    centrality = graph.compute_centrality(import_graph)

    git_stats = git_history.get_commit_stats(repo_path) if git_history.is_git_repo(repo_path) else {}
    recency = scoring.compute_recency_scores(git_stats, file_strs)

    token_counts = {f: tokens.count_tokens(parse_results[f].text) for f in file_strs}
    scores = scoring.compute_scores(file_strs, centrality, recency, token_counts, DEFAULT_WEIGHTS)

    centrality_norm = {f: scores[f].centrality for f in file_strs}
    sorted_centrality = sorted(centrality_norm.values(), reverse=True)
    top_decile_cutoff_idx = max(1, len(sorted_centrality) // 10)
    top_decile_threshold = sorted_centrality[top_decile_cutoff_idx - 1] if sorted_centrality else 0.0
    top_decile_files = {f for f, c in centrality_norm.items() if c >= top_decile_threshold}

    readme_files = {f for f in file_strs if Path(f).name.lower().startswith("readme")}

    rows: list[EvalRow] = []
    for budget in budgets:
        for method_name, selected in (
            ("ranked (RankContext)", ranked_select(scores, budget)),
            ("flat (gitingest-style)", flat_select(file_strs, token_counts, budget)),
        ):
            used = sum(token_counts.get(f, 0) for f in selected)
            avg_cent = (
                sum(centrality_norm.get(f, 0.0) for f in selected) / len(selected)
                if selected else 0.0
            )
            hit_rate = (
                len(top_decile_files & set(selected)) / len(top_decile_files)
                if top_decile_files else 0.0
            )
            rows.append(EvalRow(
                repo=repo_label,
                budget=budget,
                method=method_name,
                files_included=len(selected),
                total_files=len(file_strs),
                tokens_used=used,
                avg_centrality_included=avg_cent,
                top_decile_hit_rate=hit_rate,
                readme_included=bool(readme_files & set(selected)),
            ))
    return rows


def print_report(rows: list[EvalRow]) -> None:
    header = (
        f"{'repo':<14}{'budget':>8}  {'method':<24}{'files':>8}{'tokens':>10}"
        f"{'avg_cent':>10}{'top10%_hit':>12}{'readme':>8}"
    )
    print(header)
    print("-" * len(header))
    for r in rows:
        print(
            f"{r.repo:<14}{r.budget:>8}  {r.method:<24}{r.files_included:>4}/{r.total_files:<3}"
            f"{r.tokens_used:>10,}{r.avg_centrality_included:>10.3f}"
            f"{r.top_decile_hit_rate*100:>11.1f}%{('yes' if r.readme_included else 'no'):>8}"
        )


def main() -> None:
    import flask
    import networkx as nx

    targets = [
        ("rankcontext (self)", Path(__file__).resolve().parent.parent, [1500, 4000]),
        ("flask", Path(os.path.dirname(flask.__file__)), [3000, 10000]),
        ("networkx", Path(os.path.dirname(nx.__file__)), [5000, 20000]),
    ]

    all_rows: list[EvalRow] = []
    for label, path, budgets in targets:
        print(f"\n=== {label}  ({path}) ===")
        rows = evaluate_repo(path, label, budgets)
        print_report(rows)
        all_rows.extend(rows)

    print("\n\n=== Summary: ranked vs flat, averaged across all repos/budgets ===")
    for method in ("ranked (RankContext)", "flat (gitingest-style)"):
        subset = [r for r in all_rows if r.method == method]
        avg_cent = sum(r.avg_centrality_included for r in subset) / len(subset)
        avg_hit = sum(r.top_decile_hit_rate for r in subset) / len(subset)
        readme_rate = sum(r.readme_included for r in subset) / len(subset)
        print(
            f"{method:<24} avg_centrality={avg_cent:.3f}  "
            f"avg_top10%_hit_rate={avg_hit*100:.1f}%  "
            f"readme_included_rate={readme_rate*100:.0f}%"
        )


if __name__ == "__main__":
    main()
