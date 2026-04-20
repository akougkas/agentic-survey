from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = ["ChunkSpan", "chunk_text", "estimate_tokens"]

_CHARS_PER_TOKEN = 4  # rough English estimate per OpenAI tokenizer rule-of-thumb
_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")


@dataclass(slots=True, frozen=True)
class ChunkSpan:
    content: str
    start_char: int
    end_char: int
    token_count_estimate: int


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // _CHARS_PER_TOKEN)


def chunk_text(
    content: str,
    window_tokens: int = 800,
    stride_tokens: int = 200,
) -> list[ChunkSpan]:
    """Deterministic sliding-window chunker with sentence-boundary snapping.

    Tokens are approximated at four characters each; a ``window_tokens`` of
    800 lands at roughly 3200 chars per chunk. The window advances by
    ``stride_tokens`` so adjacent chunks overlap. When the raw window edge
    falls mid-sentence, the chunker snaps the boundary back to the nearest
    prior sentence terminator so retrieval hits include coherent spans.
    """
    text = (content or "").strip()
    if not text:
        return []
    if stride_tokens <= 0:
        raise ValueError("stride_tokens must be > 0")
    if window_tokens <= 0:
        raise ValueError("window_tokens must be > 0")

    window_chars = window_tokens * _CHARS_PER_TOKEN
    stride_chars = max(1, stride_tokens * _CHARS_PER_TOKEN)

    spans: list[ChunkSpan] = []
    start = 0
    text_len = len(text)

    while start < text_len:
        raw_end = min(start + window_chars, text_len)
        end = _snap_to_sentence_end(text, start, raw_end)
        if end <= start:
            end = raw_end
        chunk_body = text[start:end].strip()
        if chunk_body:
            chunk_start = start + _leading_whitespace(text, start, end)
            chunk_end = chunk_start + len(chunk_body)
            spans.append(
                ChunkSpan(
                    content=chunk_body,
                    start_char=chunk_start,
                    end_char=chunk_end,
                    token_count_estimate=estimate_tokens(chunk_body),
                )
            )
        if end >= text_len:
            break
        next_start = max(start + stride_chars, end - window_chars + stride_chars)
        if next_start <= start:
            next_start = start + stride_chars
        start = next_start
    return spans


def _snap_to_sentence_end(text: str, start: int, raw_end: int) -> int:
    if raw_end >= len(text):
        return len(text)
    window = text[start:raw_end]
    matches = list(_SENTENCE_BOUNDARY_RE.finditer(window))
    if not matches:
        return raw_end
    last = matches[-1]
    return start + last.start()


def _leading_whitespace(text: str, start: int, end: int) -> int:
    offset = 0
    while start + offset < end and text[start + offset].isspace():
        offset += 1
    return offset
