"""
Stage 6: Token Costing (FR-8).

Uses tiktoken when it's importable AND its encoding files are reachable
(tiktoken downloads its BPE ranks on first use, which requires network).
In fully offline environments this degrades to a documented character-
based approximation instead of crashing - consistent with RankContext's
"no paid API / works offline" non-functional requirement.
"""

from __future__ import annotations

from functools import lru_cache

_encoder = None
_encoder_checked = False


def _get_tiktoken_encoder():
    global _encoder, _encoder_checked
    if _encoder_checked:
        return _encoder
    _encoder_checked = True
    try:
        import tiktoken  # type: ignore

        _encoder = tiktoken.get_encoding("cl100k_base")
    except Exception:
        _encoder = None
    return _encoder


def using_tiktoken() -> bool:
    return _get_tiktoken_encoder() is not None


@lru_cache(maxsize=None)
def _approx_tokens(text: str) -> int:
    # Rough heuristic consistent with common English/code token density:
    # ~4 characters per token. Documented as an approximation, not exact.
    return max(1, len(text) // 4)


def count_tokens(text: str) -> int:
    encoder = _get_tiktoken_encoder()
    if encoder is not None:
        return len(encoder.encode(text, disallowed_special=()))
    return _approx_tokens(text)
