"""Markdown-aware chunker for Bear notes."""

from __future__ import annotations

import re
from typing import NamedTuple

from bear_rag.config import MAX_CHUNK_WORDS, MIN_CHUNK_WORDS, OVERLAP_WORDS
from bear_rag.models import BearNote, Chunk, ChunkMetadata

_HEADING_RE = re.compile(r"^(#{1,6}) (.+)$")
_FENCE_RE = re.compile(r"^```")


class _Section(NamedTuple):
    """Raw section produced by the primary heading split."""

    heading_line: str  # e.g. "## My Heading" or "" for pre-heading content
    body: str  # text after the heading line


def _split_on_headings(text: str) -> list[_Section]:
    """Split *text* on ATX headings, ignoring headings inside fenced code blocks.

    Returns a list of (heading_line, body) pairs.  The first pair may have an
    empty heading_line if there is text before the first heading.
    """
    sections: list[_Section] = []
    current_heading = ""
    current_body_lines: list[str] = []
    in_code_block = False

    for line in text.splitlines():
        # Toggle fenced code block state
        if _FENCE_RE.match(line):
            in_code_block = not in_code_block
            current_body_lines.append(line)
            continue

        if not in_code_block and _HEADING_RE.match(line):
            # Save the current section
            sections.append(_Section(current_heading, "\n".join(current_body_lines)))
            current_heading = line
            current_body_lines = []
        else:
            current_body_lines.append(line)

    # Don't forget the last section
    sections.append(_Section(current_heading, "\n".join(current_body_lines)))

    return sections


def _build_heading_path(stack: list[tuple[int, str]], new_heading: str) -> str:
    """Return the full heading path string for *new_heading* given the current stack.

    *stack* is a list of (level, heading_line) tuples maintained by the caller.
    This function mutates *stack* in place and returns the formatted path.
    """
    m = _HEADING_RE.match(new_heading)
    if m is None:
        return ""
    level = len(m.group(1))  # number of # characters

    # Pop entries whose level >= new level (same or deeper siblings)
    while stack and stack[-1][0] >= level:
        stack.pop()

    stack.append((level, new_heading))
    return " > ".join(h for _, h in stack)


def _word_count(text: str) -> int:
    return len(text.split())


def _split_oversized(text: str, max_words: int, overlap_words: int) -> list[str]:
    """Split *text* at paragraph boundaries when it exceeds *max_words*.

    Consecutive chunks share *overlap_words* words of overlap at their boundary.
    """
    paragraphs = re.split(r"\n\n+", text)

    chunks: list[str] = []
    current_paras: list[str] = []
    current_words = 0

    for para in paragraphs:
        para_words = _word_count(para)

        if current_words + para_words > max_words and current_paras:
            # Flush current chunk
            chunk_text = "\n\n".join(current_paras)
            chunks.append(chunk_text)

            # Build overlap: take the last overlap_words words from the flushed chunk
            all_words = chunk_text.split()
            overlap = all_words[-overlap_words:] if len(all_words) >= overlap_words else all_words
            overlap_text = " ".join(overlap)

            # Start new chunk with overlap text prepended (as its own pseudo-para)
            current_paras = [overlap_text, para] if overlap_text else [para]
            current_words = _word_count(" ".join(current_paras))
        else:
            current_paras.append(para)
            current_words += para_words

    if current_paras:
        chunks.append("\n\n".join(current_paras))

    return chunks if chunks else [text]


def _merge_up(chunks: list[tuple[str, str, str]]) -> list[tuple[str, str, str]]:
    """Merge undersized chunks into adjacent chunks.

    *chunks* is a list of (heading_path, heading_line, body) triples.
    Returns the merged list.

    Rules:
    - Chunks with fewer than MIN_CHUNK_WORDS are merged into their predecessor.
    - If the first chunk is undersized, it merges into the next chunk (forward).
    - If all chunks are undersized, they are concatenated into a single chunk.
    """
    if not chunks:
        return chunks

    def _text(heading_line: str, body: str) -> str:
        parts = []
        if heading_line:
            parts.append(heading_line)
        if body:
            parts.append(body)
        return "\n\n".join(parts)

    def _size(triple: tuple[str, str, str]) -> int:
        _, hl, body = triple
        return _word_count(_text(hl, body))

    # Check whether all are undersized
    if all(_size(c) < MIN_CHUNK_WORDS for c in chunks):
        combined_heading_path = chunks[0][0]
        combined_text = "\n\n".join(_text(hl, body) for _, hl, body in chunks)
        return [(combined_heading_path, "", combined_text)]

    result: list[tuple[str, str, str]] = list(chunks)

    # Forward pass: merge undersized first chunk into next
    while len(result) > 1 and _size(result[0]) < MIN_CHUNK_WORDS:
        _first_path, first_hl, first_body = result[0]
        second_path, second_hl, second_body = result[1]
        # Combine: prepend first content into second's body
        new_text = _text(first_hl, first_body) + "\n\n" + _text(second_hl, second_body)
        result = [(second_path, "", new_text), *result[2:]]

    # Backward pass: merge undersized non-first chunks into predecessor
    changed = True
    while changed:
        changed = False
        new_result: list[tuple[str, str, str]] = []
        i = 0
        while i < len(result):
            if i > 0 and _size(result[i]) < MIN_CHUNK_WORDS:
                # Merge into predecessor
                prev_path, prev_hl, prev_body = new_result[-1]
                _curr_path, curr_hl, curr_body = result[i]
                merged_text = _text(prev_hl, prev_body) + "\n\n" + _text(curr_hl, curr_body)
                new_result[-1] = (prev_path, "", merged_text)
                changed = True
            else:
                new_result.append(result[i])
            i += 1
        result = new_result

    return result


def chunk_note(note: BearNote) -> list[Chunk]:
    """Chunk a *BearNote* into a list of *Chunk* objects.

    Algorithm:
    1. Primary split on ATX headings (ignoring headings in fenced code blocks).
    2. Build heading_path stack for each section.
    3. Secondary split oversized sections at paragraph boundaries with overlap.
    4. Merge-up: undersized chunks fold into adjacent chunks.
    5. Assign sequential IDs and build ChunkMetadata.
    """
    raw_sections = _split_on_headings(note.text)

    # Build (heading_path, heading_line, body) triples while tracking the stack
    heading_stack: list[tuple[int, str]] = []
    sections_with_path: list[tuple[str, str, str]] = []

    for heading_line, body in raw_sections:
        if heading_line:
            path = _build_heading_path(heading_stack, heading_line)
        else:
            path = ""

        sections_with_path.append((path, heading_line, body))

    # Secondary split for oversized sections
    expanded: list[tuple[str, str, str]] = []
    for path, heading_line, body in sections_with_path:
        full_text = (heading_line + "\n\n" + body).strip() if heading_line else body.strip()
        if _word_count(full_text) > MAX_CHUNK_WORDS:
            sub_texts = _split_oversized(full_text, MAX_CHUNK_WORDS, OVERLAP_WORDS)
            for sub in sub_texts:
                expanded.append((path, "", sub))
        else:
            expanded.append((path, heading_line, body))

    # Filter out completely empty sections (no heading, no body)
    expanded = [(path, hl, body) for path, hl, body in expanded if (hl.strip() or body.strip())]

    # Merge-up undersized chunks
    merged = _merge_up(expanded)

    # Build Chunk objects
    tags_str = "," + ",".join(note.tags) + "," if note.tags else ""
    modified_at_str = note.modified_at.isoformat()

    chunks: list[Chunk] = []
    for idx, (path, heading_line, body) in enumerate(merged):
        if heading_line:
            text = (heading_line + "\n\n" + body).strip()
        else:
            text = body.strip()

        metadata: ChunkMetadata = {
            "note_pk": note.pk,
            "title": note.title,
            "tags": tags_str,
            "chunk_index": idx,
            "heading_path": path,
            "modified_at": modified_at_str,
            "source": "bear",
        }

        chunks.append(Chunk(id=f"{note.pk}_{idx}", text=text, metadata=metadata))

    return chunks
