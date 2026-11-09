"""
Stage 3: Import Graph Construction (FR-5).
Stage 4: Centrality Scoring via PageRank (FR-6).

Builds a directed graph where nodes are files and an edge A -> B means
"A imports B", then runs PageRank over it. Files imported by many other
important files score highest - this is the same intuition PageRank
uses for web pages and inbound links (PRD section 7.1).
"""

from __future__ import annotations

from pathlib import PurePosixPath

import networkx as nx

from .ast_parser import FileParseResult


def _module_name_for(relpath: str) -> str:
    """Convert a relpath like 'src/core/pipeline.py' into 'src.core.pipeline'."""
    p = PurePosixPath(relpath)
    parts = list(p.parts[:-1]) + [p.stem]
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _build_module_map(parse_results: dict[str, FileParseResult]) -> dict[str, str]:
    """dotted module name -> relpath, for every parsed Python file."""
    module_map: dict[str, str] = {}
    for relpath, result in parse_results.items():
        if result.is_python:
            module_map[_module_name_for(relpath)] = relpath
    return module_map


def _importer_package(relpath: str) -> str:
    """Dotted package name that `relpath` lives in (its containing dir)."""
    p = PurePosixPath(relpath)
    parts = list(p.parts[:-1])
    return ".".join(parts)


def _resolve_relative(importer_relpath: str, import_name: str) -> str | None:
    """Resolve a relative import ('.foo', '..bar.baz') to a dotted module name."""
    level = len(import_name) - len(import_name.lstrip("."))
    remainder = import_name[level:]
    pkg_parts = _importer_package(importer_relpath).split(".") if _importer_package(importer_relpath) else []

    # level=1 means "from this package"; each extra dot walks up one level.
    up = level - 1
    base_parts = pkg_parts[: len(pkg_parts) - up] if up <= len(pkg_parts) else []
    if remainder:
        base_parts = base_parts + remainder.split(".")
    return ".".join(p for p in base_parts if p) or None


def _resolve_absolute(import_name: str, module_map: dict[str, str]) -> str | None:
    """Best-effort resolution of an absolute dotted import to a known module."""
    if import_name in module_map:
        return module_map[import_name]
    # Try progressively shorter prefixes: "pkg.sub.thing" -> "pkg.sub" -> "pkg"
    components = import_name.split(".")
    for i in range(len(components) - 1, 0, -1):
        candidate = ".".join(components[:i])
        if candidate in module_map:
            return module_map[candidate]
    return None


def build_import_graph(
    parse_results: dict[str, FileParseResult],
    all_files: list[str],
) -> nx.DiGraph:
    """
    Build a directed graph over ALL candidate files (so non-Python and
    unresolved files still appear as isolated nodes and get a PageRank
    score, just a low one).
    """
    graph = nx.DiGraph()
    graph.add_nodes_from(all_files)

    module_map = _build_module_map(parse_results)

    for relpath, result in parse_results.items():
        if not result.is_python or not result.parse_ok:
            continue
        for raw_import in result.imports:
            if raw_import.startswith("."):
                dotted = _resolve_relative(relpath, raw_import)
                target = module_map.get(dotted) if dotted else None
                if target is None and dotted:
                    target = _resolve_absolute(dotted, module_map)
            else:
                target = _resolve_absolute(raw_import, module_map)

            if target is not None and target != relpath:
                graph.add_edge(relpath, target)

    return graph


def compute_centrality(graph: nx.DiGraph) -> dict[str, float]:
    """
    PageRank over the import graph. Handles graphs with cycles natively
    (no special-casing needed, unlike a topological sort - see PRD
    viva notes) and degrades to a uniform score if the graph has no
    edges at all (e.g. a repo with no resolvable imports).
    """
    if graph.number_of_nodes() == 0:
        return {}
    if graph.number_of_edges() == 0:
        uniform = 1.0 / graph.number_of_nodes()
        return {node: uniform for node in graph.nodes}
    return nx.pagerank(graph)
