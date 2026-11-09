"""
Stage 9: Bundle Generation (FR-12, FR-13, FR-16).

Writes a single output artifact: a small manifest (every candidate file,
its score, boost, token cost, and inclusion/exclusion reason) followed
by the full, unmodified contents of every selected file. The manifest
is for auditability; the bundle body is the actual deliverable an LLM
reads (PRD section 11a).
"""

from __future__ import annotations

import datetime as _dt

from .ast_parser import FileParseResult
from .scoring import FileScore
from .selection import SelectionResult


def _manifest_rows(selection: SelectionResult) -> list[str]:
    rows = []
    all_entries: list[tuple[FileScore, str]] = [
        (fs, "included") for fs in selection.included
    ] + list(selection.excluded)
    all_entries.sort(key=lambda pair: pair[0].boosted_score, reverse=True)

    header = f"{'path':<32}{'score':>8}{'boost':>8}{'tokens':>10}   status"
    rows.append(header)
    for fs, status in all_entries:
        rows.append(
            f"{fs.relpath:<32}{fs.boosted_score:>8.3f}{fs.boost:>7.1f}x{fs.tokens:>10,}   {status}"
        )
    return rows


def build_bundle_text(
    source_label: str,
    budget: int,
    selection: SelectionResult,
    parse_results: dict[str, FileParseResult],
    include_skeletons: bool = True,
) -> str:
    lines: list[str] = []
    lines.append("# RankContext Bundle")
    lines.append(f"# Source: {source_label}")
    lines.append(f"# Budget: {budget:,} tokens | Used: {selection.used_tokens:,} tokens")
    lines.append(f"# Generated: {_dt.datetime.now().isoformat(timespec='seconds')}")
    lines.append("")
    lines.append("## MANIFEST")
    lines.extend(_manifest_rows(selection))
    lines.append("")
    lines.append("## BUNDLE")

    for fs in selection.included:
        result = parse_results.get(fs.relpath)
        if result is None:
            raise ValueError(f"File {fs.relpath} selected but not in parse_results: pipeline bug")
        content = result.text
        lines.append(f"### FILE: {fs.relpath}")
        lines.append(content.rstrip("\n"))
        lines.append("")

    # ADDED: Include AST skeletons for excluded files to provide architectural
    # context without full implementations (typically ~500 tokens each).
    if include_skeletons and selection.excluded:
        lines.append("## AST SKELETONS (Excluded Files - Signatures Only)")
        lines.append("")
        skeleton_count = 0
        for fs, _reason in selection.excluded:
            result = parse_results.get(fs.relpath)
            if result is None:
                continue
            from .ast_parser import generate_ast_skeleton
            skeleton = generate_ast_skeleton(result)
            if skeleton:
                lines.append(f"### {fs.relpath}")
                lines.append(skeleton)
                lines.append("")
                skeleton_count += 1
                # Limit to avoid bloating bundle with too many skeletons
                if skeleton_count >= 20:
                    lines.append("... (additional skeletons omitted for brevity)")
                    break

    return "\n".join(lines)


def build_manifest_only_text(
    source_label: str, budget: int, selection: SelectionResult
) -> str:
    lines = [
        f"# RankContext Manifest (manifest-only mode)",
        f"# Source: {source_label}",
        f"# Budget: {budget:,} tokens | Used: {selection.used_tokens:,} tokens",
        "",
    ]
    lines.extend(_manifest_rows(selection))
    return "\n".join(lines)
