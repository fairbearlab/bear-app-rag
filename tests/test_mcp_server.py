"""Tests for MCP server tool handlers.

Tests call the tool handler functions directly, not via MCP protocol.
"""

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from bear_rag import config, mcp_server
from bear_rag.bear_reader import BearReader
from bear_rag.models import BearNote, Chunk, ChunkMetadata, SyncResult
from bear_rag.store import NoteStore


@pytest.fixture(autouse=True)
def reset_globals():
    """Reset module-level singletons before each test."""
    mcp_server._reader = None
    mcp_server._store = None
    yield
    mcp_server._reader = None
    mcp_server._store = None


@pytest.fixture
def reader(bear_db: Path) -> BearReader:
    reader = BearReader(bear_db)
    mcp_server._reader = reader
    return reader


@pytest.fixture
def store(note_store: NoteStore) -> NoteStore:
    mcp_server._store = note_store
    return note_store


def _index_all_notes(reader, store):
    """Helper: chunk and index all notes from reader into store."""
    from bear_rag.chunker import chunk_note

    for note in reader.read_notes():
        store.upsert_chunks(chunk_note(note))


class TestSearchNotes:
    def test_returns_matching_chunks(self, reader, store) -> None:
        _index_all_notes(reader, store)
        results = mcp_server.search_notes("normal note")
        assert len(results) > 0
        assert all("title" in r for r in results)
        assert all("text" in r for r in results)

    def test_respects_limit(self, reader, store) -> None:
        _index_all_notes(reader, store)
        results = mcp_server.search_notes("note", limit=1)
        assert len(results) <= 1

    def test_empty_store_returns_empty(self, reader, store) -> None:
        results = mcp_server.search_notes("anything")
        assert results == []

    def test_tags_returned_as_list(self, reader, store) -> None:
        """search_notes should return tags as a list, not a comma-separated string."""
        _index_all_notes(reader, store)
        results = mcp_server.search_notes("normal note")
        assert len(results) > 0
        assert isinstance(results[0]["tags"], list)

    def test_single_tag_filter(self, reader, store) -> None:
        """Filtering by a single tag returns only matching chunks."""
        _index_all_notes(reader, store)
        results = mcp_server.search_notes("note", tags=["work"])
        assert len(results) > 0
        for r in results:
            assert "work" in r["tags"]

    def test_multi_tag_filter(self, reader, store) -> None:
        """Filtering by multiple tags returns chunks matching any tag."""
        _index_all_notes(reader, store)
        results = mcp_server.search_notes("note", tags=["work", "recent"])
        assert len(results) > 0
        for r in results:
            assert "work" in r["tags"] or "recent" in r["tags"]

    def test_tag_filter_no_substring_match(self, reader, store) -> None:
        """Tag 'work' must not match notes tagged 'homework' (regression test for delimiter fix)."""
        from bear_rag.models import Chunk, ChunkMetadata

        store.upsert_chunks([
            Chunk(
                id="100_0",
                text="Office productivity tips",
                metadata=ChunkMetadata(
                    note_pk=100, title="Work Note", tags=",work,",
                    chunk_index=0, heading_path="", modified_at="2024-01-01T00:00:00+00:00", source="bear",
                ),
            ),
            Chunk(
                id="101_0",
                text="Math homework assignment",
                metadata=ChunkMetadata(
                    note_pk=101, title="Homework Note", tags=",homework,",
                    chunk_index=0, heading_path="", modified_at="2024-01-01T00:00:00+00:00", source="bear",
                ),
            ),
        ])
        results = mcp_server.search_notes("tasks", tags=["work"])
        pks = {r["note_pk"] for r in results}
        assert 101 not in pks, "Tag 'work' should not match 'homework'"


class TestReadNote:
    def test_finds_note_by_title(self, reader) -> None:
        result = mcp_server.read_note("Normal Note")
        assert result["title"] == "Normal Note"
        assert "text" in result
        assert "tags" in result

    def test_case_insensitive(self, reader) -> None:
        result = mcp_server.read_note("normal note")
        assert result["title"] == "Normal Note"

    def test_returns_error_for_missing(self, reader) -> None:
        result = mcp_server.read_note("Does Not Exist")
        assert "error" in result


class TestListNotes:
    def test_returns_all_non_trashed(self, reader) -> None:
        results = mcp_server.list_notes()
        pks = [r["note_pk"] for r in results]
        assert 3 not in pks  # trashed

    def test_filter_by_tag(self, reader) -> None:
        results = mcp_server.list_notes(tag="work")
        pks = [r["note_pk"] for r in results]
        assert pks == [1]

    def test_filter_by_title_contains(self, reader) -> None:
        results = mcp_server.list_notes(title_contains="recent")
        pks = [r["note_pk"] for r in results]
        assert pks == [2]

    def test_includes_metadata_fields(self, reader) -> None:
        results = mcp_server.list_notes()
        assert len(results) > 0
        first = results[0]
        assert "title" in first
        assert "tags" in first
        assert "modified_at" in first
        assert "note_pk" in first


class TestListTags:
    def test_returns_tags_with_counts(self, reader) -> None:
        results = mcp_server.list_tags()
        tag_names = [r["tag"] for r in results]
        assert "work" in tag_names
        assert "personal" in tag_names
        assert all("count" in r for r in results)


class TestSyncNotes:
    def test_returns_sync_result(self, reader, store) -> None:
        result = mcp_server.sync_notes()
        assert "notes_updated" in result
        assert "notes_deleted" in result
        assert "chunks_indexed" in result


class TestStatus:
    def test_returns_stats_after_sync(self, reader, store, tmp_path) -> None:
        """status() returns correct counts after indexing."""
        _index_all_notes(reader, store)
        # Write a fake state file
        state_path = tmp_path / "last_sync.json"
        state_path.write_text(json.dumps({"synced_at": "2024-06-01T00:00:00Z", "timestamp": 0.0, "index_version": 2}))
        with patch.object(config, "SYNC_STATE_PATH", state_path):
            result = mcp_server.status()
        assert result["index_count"] > 0
        assert result["note_count"] > 0
        assert result["last_sync"] == "2024-06-01T00:00:00Z"

    def test_returns_null_last_sync_when_never_synced(self, reader, store, tmp_path) -> None:
        """status() returns last_sync=None when no state file exists."""
        with patch.object(config, "SYNC_STATE_PATH", tmp_path / "nonexistent.json"):
            result = mcp_server.status()
        assert result["last_sync"] is None

    def test_empty_store(self, reader, store, tmp_path) -> None:
        """status() works with an empty index."""
        with patch.object(config, "SYNC_STATE_PATH", tmp_path / "nonexistent.json"):
            result = mcp_server.status()
        assert result["index_count"] == 0
        assert result["note_count"] == 0


class TestHandleErrors:
    def test_file_not_found_returns_error_dict(self, tmp_path) -> None:
        """When Bear DB is missing, tools should return an error dict, not crash."""
        mcp_server._reader = None
        mcp_server._store = None
        # Point reader at a non-existent DB
        with patch("bear_rag.mcp_server._get_reader", side_effect=FileNotFoundError("no db")):
            result = mcp_server.read_note("Any Title")
        assert "error" in result
        assert "not found" in result["error"].lower()

    def test_normal_return_passes_through(self, reader) -> None:
        """Decorator should not interfere with normal tool returns."""
        result = mcp_server.read_note("Normal Note")
        assert "error" not in result
        assert result["title"] == "Normal Note"


class TestIntegration:
    def test_sync_search_read_flow(self, reader, store) -> None:
        """End-to-end: sync → search → read. The primary agent workflow."""
        # Use _index_all_notes to populate the store (sync_notes depends on state path)
        _index_all_notes(reader, store)

        search_results = mcp_server.search_notes("normal note")
        assert len(search_results) > 0
        title = search_results[0]["title"]

        note = mcp_server.read_note(title)
        assert "error" not in note
        assert note["title"] == title
        assert len(note["text"]) > 0
