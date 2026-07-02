from pathlib import Path

import pytest

from bear_rag.models import Chunk, ChunkMetadata
from bear_rag.store import NoteStore


def _make_chunk(note_pk: int, chunk_index: int, text: str) -> Chunk:
    return Chunk(
        id=f"{note_pk}_{chunk_index}",
        text=text,
        metadata=ChunkMetadata(
            note_pk=note_pk,
            title=f"Note {note_pk}",
            tags="tag1",
            chunk_index=chunk_index,
            heading_path="",
            modified_at="2024-01-01T00:00:00+00:00",
            source=f"bear://x-callback-url/open-note?id={note_pk}",
        ),
    )


class TestNoteStoreUpsert:
    def test_add_chunks_count(self, note_store: NoteStore) -> None:
        chunks = [
            _make_chunk(1, 0, "Hello world"),
            _make_chunk(1, 1, "Another chunk"),
        ]
        note_store.upsert_chunks(chunks)
        assert note_store.get_stats()["count"] == 2

    def test_upsert_idempotent(self, note_store: NoteStore) -> None:
        chunk = _make_chunk(1, 0, "Hello world")
        note_store.upsert_chunks([chunk])
        note_store.upsert_chunks([chunk])
        assert note_store.get_stats()["count"] == 1

    def test_upsert_updates_existing(self, note_store: NoteStore) -> None:
        chunk = _make_chunk(1, 0, "Original text")
        note_store.upsert_chunks([chunk])

        updated_chunk = _make_chunk(1, 0, "Updated text")
        note_store.upsert_chunks([updated_chunk])

        results = note_store.query("Updated text", n_results=1)
        assert len(results) == 1
        assert results[0].text == "Updated text"

    def test_upsert_empty_list_noop(self, note_store: NoteStore) -> None:
        note_store.upsert_chunks([])
        assert note_store.get_stats()["count"] == 0


class TestNoteStoreDelete:
    def test_delete_note_removes_all_chunks(self, note_store: NoteStore) -> None:
        # Add 2 chunks for note 1, 1 chunk for note 2
        chunks = [
            _make_chunk(1, 0, "Note 1 chunk A"),
            _make_chunk(1, 1, "Note 1 chunk B"),
            _make_chunk(2, 0, "Note 2 chunk A"),
        ]
        note_store.upsert_chunks(chunks)
        assert note_store.get_stats()["count"] == 3

        note_store.delete_note(1)
        assert note_store.get_stats()["count"] == 1

    def test_delete_nonexistent_note_noop(self, note_store: NoteStore) -> None:
        chunk = _make_chunk(1, 0, "Some text")
        note_store.upsert_chunks([chunk])
        note_store.delete_note(999)
        assert note_store.get_stats()["count"] == 1


class TestNoteStoreQuery:
    def test_returns_relevant_chunks_ranked(self, note_store: NoteStore) -> None:
        chunks = [
            _make_chunk(1, 0, "Python programming language for data science"),
            _make_chunk(2, 0, "How to bake a chocolate cake with frosting"),
        ]
        note_store.upsert_chunks(chunks)

        results = note_store.query("Python programming", n_results=2)
        assert len(results) >= 1
        # The Python chunk should rank first (most relevant)
        assert "Python" in results[0].text

    def test_returns_chunk_objects_with_correct_metadata(self, note_store: NoteStore) -> None:
        chunk = _make_chunk(42, 3, "Test content for metadata check")
        note_store.upsert_chunks([chunk])

        results = note_store.query("Test content metadata", n_results=1)
        assert len(results) == 1
        result = results[0]

        assert isinstance(result, Chunk)
        assert result.id == "42_3"
        assert result.text == "Test content for metadata check"
        assert result.metadata["note_pk"] == 42
        assert isinstance(result.metadata["note_pk"], int)
        assert result.metadata["chunk_index"] == 3
        assert isinstance(result.metadata["chunk_index"], int)
        assert result.metadata["title"] == "Note 42"

    def test_query_empty_store_returns_empty(self, note_store: NoteStore) -> None:
        results = note_store.query("anything", n_results=5)
        assert results == []

    def test_query_n_results_capped_at_count(self, note_store: NoteStore) -> None:
        note_store.upsert_chunks([_make_chunk(1, 0, "Only one chunk")])
        results = note_store.query("chunk", n_results=10)
        assert len(results) == 1


class TestNoteStoreReset:
    def test_reset_clears_collection(self, note_store: NoteStore) -> None:
        note_store.upsert_chunks([_make_chunk(1, 0, "Some text")])
        assert note_store.get_stats()["count"] == 1

        note_store.reset()
        assert note_store.get_stats()["count"] == 0

    def test_reset_allows_subsequent_upsert(self, note_store: NoteStore) -> None:
        note_store.upsert_chunks([_make_chunk(1, 0, "Before reset")])
        note_store.reset()
        note_store.upsert_chunks([_make_chunk(2, 0, "After reset")])
        assert note_store.get_stats()["count"] == 1


def _make_tagged_chunk(note_pk: int, chunk_index: int, text: str, tags: str = "", title: str = "Test") -> Chunk:
    return Chunk(
        id=f"{note_pk}_{chunk_index}",
        text=text,
        metadata=ChunkMetadata(
            note_pk=note_pk,
            title=title,
            tags=tags,
            chunk_index=chunk_index,
            heading_path="",
            modified_at="2024-06-01T12:00:00+00:00",
            source="bear",
        ),
    )


class TestNoteStoreQueryWithFilter:
    """The store applies a Chroma-native `where` filter and does no post-filtering.

    Tag->pk resolution now lives in ``mcp_server.search_notes`` (D2); the store
    only ever sees a scalar ``{"note_pk": {"$in": [...]}}`` filter. The old
    hand-rolled ``$contains`` post-filter engine was deleted in T4.
    """

    def test_query_filters_by_note_pk_in(self, note_store: NoteStore) -> None:
        note_store.upsert_chunks([
            _make_tagged_chunk(1, 0, "Python web framework tutorial"),
            _make_tagged_chunk(2, 0, "Rust systems programming guide"),
            _make_tagged_chunk(3, 0, "Go networking library"),
        ])
        results = note_store.query(
            "programming", n_results=10, where={"note_pk": {"$in": [1, 3]}}
        )
        result_pks = {c.metadata["note_pk"] for c in results}
        assert result_pks == {1, 3}

    def test_query_single_pk_in(self, note_store: NoteStore) -> None:
        note_store.upsert_chunks([
            _make_tagged_chunk(1, 0, "Python web framework tutorial"),
            _make_tagged_chunk(2, 0, "Rust systems programming guide"),
        ])
        results = note_store.query(
            "programming", n_results=10, where={"note_pk": {"$in": [2]}}
        )
        result_pks = {c.metadata["note_pk"] for c in results}
        assert result_pks == {2}

    def test_query_without_filter_returns_all(self, note_store: NoteStore) -> None:
        note_store.upsert_chunks([
            _make_tagged_chunk(1, 0, "Python web framework tutorial"),
            _make_tagged_chunk(2, 0, "Rust systems programming guide"),
        ])
        results = note_store.query("programming", n_results=10)
        assert len(results) == 2

    def test_query_large_pk_in_list(self, note_store: NoteStore) -> None:
        """D22 scale check: a popular tag resolves to thousands of pks. Chroma's
        native `$in` must accept a large list without a validation error, so no
        batched fallback is needed."""
        chunks = [
            _make_tagged_chunk(pk, 0, f"Note {pk} about programming and systems")
            for pk in range(1, 3001)
        ]
        note_store.upsert_chunks(chunks)
        big_pks = list(range(1, 2501))  # 2500 pks in the filter
        results = note_store.query(
            "programming", n_results=10, where={"note_pk": {"$in": big_pks}}
        )
        assert len(results) == 10
        assert all(c.metadata["note_pk"] in set(big_pks) for c in results)


class TestNoteStoreStats:
    def test_stats_empty_store(self, note_store: NoteStore) -> None:
        stats = note_store.get_stats()
        assert stats == {"count": 0, "note_count": 0}

    def test_stats_after_adding_chunks(self, note_store: NoteStore) -> None:
        note_store.upsert_chunks([
            _make_chunk(1, 0, "First chunk"),
            _make_chunk(1, 1, "Second chunk"),
        ])
        stats = note_store.get_stats()
        assert stats == {"count": 2, "note_count": 1}

    def test_stats_note_count_distinct(self, note_store: NoteStore) -> None:
        note_store.upsert_chunks([
            _make_chunk(1, 0, "Note one chunk one"),
            _make_chunk(1, 1, "Note one chunk two"),
            _make_chunk(2, 0, "Note two chunk one"),
        ])
        stats = note_store.get_stats()
        assert stats == {"count": 3, "note_count": 2}
