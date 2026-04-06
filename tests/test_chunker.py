"""Tests for bear_rag.chunker — written before implementation (TDD)."""

from datetime import datetime, timezone

import pytest

from bear_rag.models import BearNote, Chunk


def _make_note(
    text: str,
    pk: int = 1,
    title: str = "Test Note",
    tags: list[str] | None = None,
) -> BearNote:
    """Create a BearNote instance for testing."""
    return BearNote(
        pk=pk,
        title=title,
        text=text,
        modified_at=datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
        tags=tags if tags is not None else [],
        is_trashed=False,
        is_archived=False,
    )


# ---------------------------------------------------------------------------
# TestChunkNoteBasic
# ---------------------------------------------------------------------------


class TestChunkNoteBasic:
    def test_no_headings_single_chunk(self) -> None:
        from bear_rag.chunker import chunk_note

        text = "This is a simple note with no headings. " * 5
        note = _make_note(text)
        chunks = chunk_note(note)
        assert len(chunks) == 1, "No headings should produce exactly one chunk"

    def test_single_heading_produces_chunks(self) -> None:
        from bear_rag.chunker import chunk_note

        text = "# My Heading\n\nSome content under the heading. " * 3
        note = _make_note(text)
        chunks = chunk_note(note)
        # Should produce at least one chunk
        assert len(chunks) >= 1
        # The chunk text should contain the content
        all_text = " ".join(c.text for c in chunks)
        assert "My Heading" in all_text or "Some content" in all_text

    def test_multiple_headings_split(self) -> None:
        from bear_rag.chunker import chunk_note
        from bear_rag.config import MIN_CHUNK_WORDS

        # Use enough words per section so merge-up does not collapse them
        para = " ".join(["word"] * (MIN_CHUNK_WORDS * 2))
        text = (
            f"# Section One\n\n{para}\n\n"
            f"# Section Two\n\n{para}\n\n"
            f"# Section Three\n\n{para}\n"
        )
        note = _make_note(text)
        chunks = chunk_note(note)
        # Each heading should produce a separate chunk
        assert len(chunks) >= 2, "Multiple headings should split into multiple chunks"

    def test_heading_path_top_level(self) -> None:
        from bear_rag.chunker import chunk_note

        text = "# Introduction\n\nSome introductory text here with enough words to be a valid chunk."
        note = _make_note(text)
        chunks = chunk_note(note)
        # Find a chunk with heading path containing "Introduction"
        paths = [c.metadata["heading_path"] for c in chunks]
        assert any("Introduction" in p for p in paths), (
            f"Expected 'Introduction' in a heading_path, got: {paths}"
        )

    def test_heading_path_nested(self) -> None:
        from bear_rag.chunker import chunk_note
        from bear_rag.config import MIN_CHUNK_WORDS

        # Use enough words per section to survive merge-up
        para = " ".join(["word"] * (MIN_CHUNK_WORDS * 2))
        text = (
            f"# H1\n\n{para}\n\n"
            f"## H2\n\n{para}\n\n"
            f"### H3\n\n{para}\n"
        )
        note = _make_note(text)
        chunks = chunk_note(note)
        paths = [c.metadata["heading_path"] for c in chunks]
        # At least one path should show nesting
        nested = [p for p in paths if ">" in p]
        assert len(nested) >= 1, f"Expected at least one nested heading path, got: {paths}"

    def test_deeply_nested_heading_path_format(self) -> None:
        from bear_rag.chunker import chunk_note

        # Build text with enough content so chunks survive merge-up
        para = " ".join(["word"] * 40)
        text = (
            f"# H1\n\n{para}\n\n"
            f"## H2\n\n{para}\n\n"
            f"### H3\n\n{para}\n"
        )
        note = _make_note(text)
        chunks = chunk_note(note)
        paths = [c.metadata["heading_path"] for c in chunks]
        # Should have a path formatted as "# H1 > ## H2 > ### H3"
        assert any(p == "# H1 > ## H2 > ### H3" for p in paths), (
            f"Expected '# H1 > ## H2 > ### H3' in paths, got: {paths}"
        )

    def test_heading_path_resets_on_same_level(self) -> None:
        from bear_rag.chunker import chunk_note

        para = " ".join(["word"] * 40)
        text = (
            f"# H1\n\n{para}\n\n"
            f"## H2a\n\n{para}\n\n"
            f"## H2b\n\n{para}\n"
        )
        note = _make_note(text)
        chunks = chunk_note(note)
        paths = [c.metadata["heading_path"] for c in chunks]
        # H2b chunk should have "# H1 > ## H2b", not contain H2a
        h2b_paths = [p for p in paths if "H2b" in p]
        assert len(h2b_paths) >= 1, f"Expected chunk with H2b in path, got: {paths}"
        assert not any("H2a" in p for p in h2b_paths), (
            f"H2b path should not contain H2a, got: {h2b_paths}"
        )


# ---------------------------------------------------------------------------
# TestChunkNoteCodeBlocks
# ---------------------------------------------------------------------------


class TestChunkNoteCodeBlocks:
    def test_hash_inside_code_block_ignored(self) -> None:
        from bear_rag.chunker import chunk_note

        text = (
            "Some introductory text before code.\n\n"
            "```python\n"
            "# This is a Python comment, not a heading\n"
            "def foo():\n"
            "    pass\n"
            "```\n\n"
            "Some text after the code block.\n"
        )
        note = _make_note(text)
        chunks = chunk_note(note)
        # The # inside the code block must NOT split the chunk
        # All content should be in one chunk (or merged into one)
        all_text = " ".join(c.text for c in chunks)
        assert "# This is a Python comment" in all_text, (
            "Code block content should be preserved in chunk text"
        )

    def test_code_block_does_not_split(self) -> None:
        from bear_rag.chunker import chunk_note

        # Build content that stays within MAX_CHUNK_WORDS when not split on code comment
        para = "word " * 20
        text = (
            f"Intro paragraph. {para}\n\n"
            "```\n"
            "# fake heading inside code\n"
            "more code\n"
            "```\n\n"
            f"Outro paragraph. {para}\n"
        )
        note = _make_note(text)
        chunks = chunk_note(note)
        # The # inside code should not cause a split, so we should have at most
        # the number of real-heading splits (zero here), not more
        for chunk in chunks:
            assert "fake heading inside code" not in chunk.metadata["heading_path"], (
                "Code block comment should not appear in heading_path"
            )

    def test_heading_after_code_block_splits_normally(self) -> None:
        from bear_rag.chunker import chunk_note

        para = " ".join(["word"] * 40)
        text = (
            f"# Real Heading One\n\n{para}\n\n"
            "```python\n"
            "# comment in code\n"
            "x = 1\n"
            "```\n\n"
            f"# Real Heading Two\n\n{para}\n"
        )
        note = _make_note(text)
        chunks = chunk_note(note)
        paths = [c.metadata["heading_path"] for c in chunks]
        assert any("Real Heading One" in p for p in paths), (
            "Real Heading One should appear in paths"
        )
        assert any("Real Heading Two" in p for p in paths), (
            "Real Heading Two should appear in paths"
        )


# ---------------------------------------------------------------------------
# TestChunkNoteSecondarySplit
# ---------------------------------------------------------------------------


class TestChunkNoteSecondarySplit:
    def test_oversized_chunk_split_at_paragraph_boundary(self) -> None:
        from bear_rag.chunker import chunk_note
        from bear_rag.config import MAX_CHUNK_WORDS

        # Build a body with two paragraphs that together exceed MAX_CHUNK_WORDS
        para = " ".join([f"word{i}" for i in range(MAX_CHUNK_WORDS // 2 + 10)])
        text = f"# Section\n\n{para}\n\n{para}\n"
        note = _make_note(text)
        chunks = chunk_note(note)
        assert len(chunks) >= 2, (
            "Oversized chunk should be split into at least 2 chunks"
        )

    def test_oversized_split_respects_max_words(self) -> None:
        from bear_rag.chunker import chunk_note
        from bear_rag.config import MAX_CHUNK_WORDS, OVERLAP_WORDS

        para = " ".join([f"word{i}" for i in range(MAX_CHUNK_WORDS // 2 + 10)])
        text = f"# Section\n\n{para}\n\n{para}\n\n{para}\n"
        note = _make_note(text)
        chunks = chunk_note(note)
        # Each chunk should not greatly exceed MAX_CHUNK_WORDS (overlap allowance)
        for chunk in chunks:
            word_count = len(chunk.text.split())
            assert word_count <= MAX_CHUNK_WORDS + OVERLAP_WORDS + 10, (
                f"Chunk has {word_count} words, expected <= {MAX_CHUNK_WORDS + OVERLAP_WORDS + 10}"
            )

    def test_overlap_present_between_split_chunks(self) -> None:
        from bear_rag.chunker import chunk_note
        from bear_rag.config import MAX_CHUNK_WORDS, OVERLAP_WORDS

        # Two large paragraphs to force a split
        para_a = " ".join([f"alpha{i}" for i in range(MAX_CHUNK_WORDS // 2 + 5)])
        para_b = " ".join([f"beta{i}" for i in range(MAX_CHUNK_WORDS // 2 + 5)])
        text = f"# Section\n\n{para_a}\n\n{para_b}\n"
        note = _make_note(text)
        chunks = chunk_note(note)
        assert len(chunks) >= 2, "Expected at least 2 chunks for overlap test"

        # The last OVERLAP_WORDS of chunk[0] should appear at the start of chunk[1]
        chunk0_words = chunks[0].text.split()
        chunk1_words = chunks[1].text.split()
        overlap_words = chunk0_words[-OVERLAP_WORDS:]
        # At least some overlap words should appear at the beginning of chunk1
        chunk1_start = chunk1_words[:OVERLAP_WORDS * 2]
        overlap_found = any(w in chunk1_start for w in overlap_words)
        assert overlap_found, (
            f"Expected overlap between consecutive chunks.\n"
            f"End of chunk0: {chunk0_words[-10:]}\n"
            f"Start of chunk1: {chunk1_words[:10]}"
        )


# ---------------------------------------------------------------------------
# TestChunkNoteMergeUp
# ---------------------------------------------------------------------------


class TestChunkNoteMergeUp:
    def test_undersized_chunk_merged_into_preceding(self) -> None:
        from bear_rag.chunker import chunk_note
        from bear_rag.config import MIN_CHUNK_WORDS

        # Large first section, tiny second section
        large_para = " ".join(["word"] * (MIN_CHUNK_WORDS * 3))
        tiny_para = "Too short."
        text = f"# Section One\n\n{large_para}\n\n# Section Two\n\n{tiny_para}\n"
        note = _make_note(text)
        chunks = chunk_note(note)
        # Section Two is under MIN_CHUNK_WORDS and should merge into Section One
        assert len(chunks) == 1, (
            f"Undersized chunk should merge into preceding. Got {len(chunks)} chunks."
        )
        assert "Too short" in chunks[0].text

    def test_first_chunk_undersized_merges_forward(self) -> None:
        from bear_rag.chunker import chunk_note
        from bear_rag.config import MIN_CHUNK_WORDS

        tiny_intro = "Tiny intro."
        large_para = " ".join(["word"] * (MIN_CHUNK_WORDS * 3))
        text = f"# Tiny Intro\n\n{tiny_intro}\n\n# Big Section\n\n{large_para}\n"
        note = _make_note(text)
        chunks = chunk_note(note)
        # The tiny first chunk has no preceding chunk, so it merges into next
        assert len(chunks) == 1, (
            f"First undersized chunk should merge forward. Got {len(chunks)} chunks."
        )
        assert "Tiny intro" in chunks[0].text
        assert "word" in chunks[0].text

    def test_all_chunks_undersized_produces_single_chunk(self) -> None:
        from bear_rag.chunker import chunk_note

        text = (
            "# A\n\nTiny.\n\n"
            "# B\n\nAlso tiny.\n\n"
            "# C\n\nStill tiny.\n"
        )
        note = _make_note(text)
        chunks = chunk_note(note)
        assert len(chunks) == 1, (
            f"All undersized chunks should produce single chunk. Got {len(chunks)} chunks."
        )

    def test_normal_sized_chunks_not_merged(self) -> None:
        from bear_rag.chunker import chunk_note
        from bear_rag.config import MIN_CHUNK_WORDS

        para = " ".join(["word"] * (MIN_CHUNK_WORDS * 2))
        text = f"# Section One\n\n{para}\n\n# Section Two\n\n{para}\n"
        note = _make_note(text)
        chunks = chunk_note(note)
        assert len(chunks) == 2, (
            f"Normal-sized chunks should remain separate. Got {len(chunks)} chunks."
        )


# ---------------------------------------------------------------------------
# TestChunkNoteMetadata
# ---------------------------------------------------------------------------


class TestChunkNoteMetadata:
    def test_chunk_id_format(self) -> None:
        from bear_rag.chunker import chunk_note

        note = _make_note("Some content with enough words to be a valid chunk.", pk=42)
        chunks = chunk_note(note)
        for i, chunk in enumerate(chunks):
            assert chunk.id == f"42_{i}", (
                f"Expected chunk id '42_{i}', got '{chunk.id}'"
            )

    def test_sequential_chunk_index(self) -> None:
        from bear_rag.chunker import chunk_note
        from bear_rag.config import MIN_CHUNK_WORDS

        para = " ".join(["word"] * (MIN_CHUNK_WORDS * 2))
        text = f"# Section One\n\n{para}\n\n# Section Two\n\n{para}\n"
        note = _make_note(text)
        chunks = chunk_note(note)
        for i, chunk in enumerate(chunks):
            assert chunk.metadata["chunk_index"] == i, (
                f"chunk_index should be {i}, got {chunk.metadata['chunk_index']}"
            )

    def test_tags_comma_separated(self) -> None:
        from bear_rag.chunker import chunk_note

        note = _make_note(
            "Content with enough words here to form a valid chunk.",
            tags=["python", "rag", "notes"],
        )
        chunks = chunk_note(note)
        assert len(chunks) >= 1
        tags_str = chunks[0].metadata["tags"]
        assert isinstance(tags_str, str), f"tags should be str, got {type(tags_str)}"
        assert tags_str == ",python,rag,notes,", (
            f"Expected ',python,rag,notes,', got '{tags_str}'"
        )

    def test_tags_empty_list(self) -> None:
        from bear_rag.chunker import chunk_note

        note = _make_note("Some content here that is long enough.", tags=[])
        chunks = chunk_note(note)
        assert chunks[0].metadata["tags"] == ""

    def test_source_is_bear(self) -> None:
        from bear_rag.chunker import chunk_note

        note = _make_note("Enough content to form a valid chunk here.")
        chunks = chunk_note(note)
        for chunk in chunks:
            assert chunk.metadata["source"] == "bear"

    def test_modified_at_iso_format(self) -> None:
        from bear_rag.chunker import chunk_note

        dt = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        note = _make_note("Content with enough words to be valid chunk.", pk=1)
        note = BearNote(
            pk=1,
            title="Test",
            text="Content with enough words to be valid chunk.",
            modified_at=dt,
            tags=[],
            is_trashed=False,
            is_archived=False,
        )
        chunks = chunk_note(note)
        assert len(chunks) >= 1
        modified_at = chunks[0].metadata["modified_at"]
        assert isinstance(modified_at, str), "modified_at should be a string"
        # Should be parseable as ISO 8601
        parsed = datetime.fromisoformat(modified_at)
        assert parsed.year == 2024
        assert parsed.month == 6
        assert parsed.day == 1

    def test_note_pk_in_metadata(self) -> None:
        from bear_rag.chunker import chunk_note

        note = _make_note("Some content here that is long enough for a valid chunk.", pk=99)
        chunks = chunk_note(note)
        for chunk in chunks:
            assert chunk.metadata["note_pk"] == 99

    def test_title_in_metadata(self) -> None:
        from bear_rag.chunker import chunk_note

        note = _make_note(
            "Some content here that is long enough for a valid chunk.",
            title="My Special Note",
        )
        chunks = chunk_note(note)
        for chunk in chunks:
            assert chunk.metadata["title"] == "My Special Note"

    def test_chunk_index_in_id_matches_metadata(self) -> None:
        from bear_rag.chunker import chunk_note
        from bear_rag.config import MIN_CHUNK_WORDS

        para = " ".join(["word"] * (MIN_CHUNK_WORDS * 2))
        note = _make_note(
            f"# A\n\n{para}\n\n# B\n\n{para}\n",
            pk=7,
        )
        chunks = chunk_note(note)
        for chunk in chunks:
            idx = chunk.metadata["chunk_index"]
            assert chunk.id == f"7_{idx}", (
                f"chunk.id '{chunk.id}' does not match expected '7_{idx}'"
            )
