"""
Stage 2: AST Parsing (FR-4).

Parses each Python source file with the standard library `ast` module
and extracts import statements and top-level definitions. Non-Python
files, or Python files that fail to parse, degrade gracefully: they are
still included as candidates later, just without AST-based signal
(FR-14).
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class FileParseResult:
    relpath: str
    is_python: bool
    parse_ok: bool
    imports: list[str] = field(default_factory=list)
    top_level_defs: list[str] = field(default_factory=list)
    text: str = ""
    read_ok: bool = True


def _read_text(path: Path) -> tuple[str, bool]:
    try:
        return path.read_text(encoding="utf-8", errors="replace"), True
    except OSError:
        return "", False


def _extract_imports(tree: ast.Module) -> list[str]:
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                # node.level > 0 means a relative import (from . import x);
                # we keep the module name as-is and let graph.py resolve it.
                prefix = "." * node.level
                imports.append(f"{prefix}{node.module}")
            elif node.level > 0:
                imports.append("." * node.level)
    return imports


def _extract_top_level_defs(tree: ast.Module) -> list[str]:
    names = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.append(node.name)
    return names


def parse_file(root: Path, relpath: Path) -> FileParseResult:
    full_path = root / relpath
    rel_str = relpath.as_posix()
    text, read_ok = _read_text(full_path)

    if not read_ok:
        return FileParseResult(relpath=rel_str, is_python=False, parse_ok=False, read_ok=False)

    is_python = relpath.suffix == ".py"
    if not is_python:
        return FileParseResult(relpath=rel_str, is_python=False, parse_ok=True, text=text)

    try:
        tree = ast.parse(text, filename=rel_str)
    except SyntaxError:
        return FileParseResult(relpath=rel_str, is_python=True, parse_ok=False, text=text)

    return FileParseResult(
        relpath=rel_str,
        is_python=True,
        parse_ok=True,
        imports=_extract_imports(tree),
        top_level_defs=_extract_top_level_defs(tree),
        text=text,
    )


def parse_all(root: Path, files: list[Path]) -> dict[str, FileParseResult]:
    return {f.as_posix(): parse_file(root, f) for f in files}


def generate_ast_skeleton(parse_result: FileParseResult) -> str:
    """
    Extract a minimal AST skeleton: class names, function signatures,
    and their docstrings. Useful for excluded files to provide architectural
    context without the full implementation (~500 tokens vs 5000+).

    Returns empty string if file is not Python or failed to parse.
    """
    if not parse_result.parse_ok or not parse_result.is_python:
        return ""

    lines: list[str] = []
    try:
        tree = ast.parse(parse_result.text)
    except SyntaxError:
        return ""

    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            # Class signature with bases
            sig = f"class {node.name}"
            if node.bases:
                base_strs = []
                for base in node.bases:
                    try:
                        base_str = ast.unparse(base)
                        if len(base_str) > 50:
                            base_str = base_str[:47] + "..."
                        base_strs.append(base_str)
                    except Exception:
                        base_strs.append("...")
                sig += f"({', '.join(base_strs)})"
            lines.append(sig + ":")

            # Class docstring
            doc = ast.get_docstring(node)
            if doc:
                lines.append(f'    """{doc[:200]}"""')

            # Method signatures (not implementation)
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    prefix = "async " if isinstance(item, ast.AsyncFunctionDef) else ""
                    lines.append(f"    {prefix}def {item.name}(...)")
                    method_doc = ast.get_docstring(item)
                    if method_doc:
                        lines.append(f'        """{method_doc[:100]}"""')
            lines.append("")

        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # Top-level function signature
            prefix = "async " if isinstance(node, ast.AsyncFunctionDef) else ""
            lines.append(f"{prefix}def {node.name}(...)")
            doc = ast.get_docstring(node)
            if doc:
                lines.append(f'    """{doc[:200]}"""')
            lines.append("")

    return "\n".join(lines)
