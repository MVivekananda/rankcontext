"""
CLI entry point (PRD section 11).

Examples:
    rankcontext https://github.com/user/repo --budget 50000 --output context.txt
    rankcontext ./my-local-repo --budget 20000 --exclude tests/ --output bundle.md
    rankcontext ./my-local-repo --budget 30000 --weights 0.5,0.3,0.2
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import DEFAULT_WEIGHTS
from .pipeline import run_pipeline


def _parse_weights(raw: str) -> tuple[float, float, float]:
    parts = [p.strip() for p in raw.split(",")]
    if len(parts) != 3:
        raise argparse.ArgumentTypeError("--weights must be 3 comma-separated numbers, e.g. 0.5,0.3,0.2")
    try:
        w1, w2, w3 = (float(p) for p in parts)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"--weights values must be numeric: {exc}") from exc
    return (w1, w2, w3)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rankcontext",
        description="Relevance-ranked, token-budgeted codebase context extraction for LLMs.",
    )
    parser.add_argument("source", help="Local path or Git URL of the repository to analyze.")
    parser.add_argument("--budget", type=int, default=50_000, help="Maximum token count for the output bundle (default: 50000).")
    parser.add_argument("--output", default="context_bundle.txt", help="Output file path (default: context_bundle.txt).")
    parser.add_argument("--exclude", action="append", default=[], metavar="PATTERN", help="Additional glob pattern to exclude. Repeatable.")
    parser.add_argument("--weights", type=_parse_weights, default=DEFAULT_WEIGHTS, help="Comma-separated weights for centrality,recency,cost (default: 0.5,0.3,0.2).")
    parser.add_argument("--manifest-only", action="store_true", help="Print the ranked manifest without writing the bundle.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        result = run_pipeline(
            source=args.source,
            budget=args.budget,
            exclude_patterns=args.exclude,
            weights=args.weights,
            manifest_only=args.manifest_only,
        )
    except (FileNotFoundError, RuntimeError) as exc:
        print(f"rankcontext: error: {exc}", file=sys.stderr)
        return 1

    if not result.used_tiktoken:
        print(
            "rankcontext: note: tiktoken unavailable/offline - using an approximate "
            "character-based token count instead of exact BPE tokenization.",
            file=sys.stderr,
        )

    if args.manifest_only:
        print(result.manifest_text)
        return 0

    output_path = Path(args.output)
    output_path.write_text(result.bundle_text or "", encoding="utf-8")

    print(
        f"rankcontext: {result.included_count}/{result.total_candidate_files} files included "
        f"({result.used_tokens:,}/{result.budget:,} tokens) -> {output_path}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
