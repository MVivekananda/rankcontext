"""
Pipeline orchestration: wires stages 1-9 together.

Both cli.py and webapp.py call `run_pipeline()` so there is exactly one
implementation of the core logic (PRD section 12: "the web UI ... should
not contain any scoring or ranking logic of its own").
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass

from . import ast_parser, bundler, git_history, graph, ingestion, scoring, selection, tokens
from .config import DEFAULT_MAX_FILES, DEFAULT_WEIGHTS


@dataclass
class PipelineResult:
    source_label: str
    budget: int
    used_tokens: int
    total_candidate_files: int
    included_count: int
    excluded_count: int
    manifest_text: str
    bundle_text: str | None  # None when manifest_only=True
    used_tiktoken: bool


def run_pipeline(
    source: str,
    budget: int = 50_000,
    exclude_patterns: list[str] | None = None,
    weights: tuple[float, float, float] = DEFAULT_WEIGHTS,
    manifest_only: bool = False,
    max_files: int = DEFAULT_MAX_FILES,
    include_skeletons: bool = True,
) -> PipelineResult:
    resolved = ingestion.resolve_source(source)
    try:
        root = resolved.root

        # Stage 1
        files = ingestion.collect_files(root, exclude_patterns or (), max_files=max_files)
        file_strs = [f.as_posix() for f in files]

        # Stage 2
        parse_results = ast_parser.parse_all(root, files)

        # Stages 3-4
        import_graph = graph.build_import_graph(parse_results, file_strs)
        centrality = graph.compute_centrality(import_graph)

        # Stage 5
        git_stats = git_history.get_commit_stats(root) if resolved.is_git_repo else {}
        recency = scoring.compute_recency_scores(git_stats, file_strs)

        # Stage 6
        token_counts = {
            f: tokens.count_tokens(parse_results[f].text) for f in file_strs
        }

        # Stage 7 (incl. documentation/config boost)
        scores = scoring.compute_scores(
            file_strs, centrality, recency, token_counts, weights
        )

        # Stage 8: Apply 5% budget headroom for manifest and formatting overhead
        effective_budget = int(budget * 0.95)
        sel = selection.greedy_select(scores, effective_budget)

        # Stage 9
        manifest_text = bundler.build_manifest_only_text(source, budget, sel)
        bundle_text = None
        if not manifest_only:
            bundle_text = bundler.build_bundle_text(
                source, budget, sel, parse_results, include_skeletons=include_skeletons
            )

        return PipelineResult(
            source_label=source,
            budget=budget,
            used_tokens=sel.used_tokens,
            total_candidate_files=len(file_strs),
            included_count=len(sel.included),
            excluded_count=len(sel.excluded),
            manifest_text=manifest_text,
            bundle_text=bundle_text,
            used_tiktoken=tokens.using_tiktoken(),
        )
    finally:
        if resolved.is_temp_clone:
            shutil.rmtree(resolved.root, ignore_errors=True)
