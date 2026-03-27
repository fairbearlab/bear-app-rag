"""Tests for MCP server tool handlers.

Tests call the tool handler functions directly, not via MCP protocol.
"""

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from bear_rag import mcp_server
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


class TestSearchNotes:
    def test_returns_matching_chunks(self, reader, store) -> None:
        from bear_rag.chunker import chunk_note

        notes = reader.read_notes()
        for note in notes:
            chunks = chunk_note(note)
            store.upsert_chunks(chunks)

        results = mcp_server.search_notes("normal note")
        assert len(results) > 0
        assert all("title" in r for r in results)
        assert all("text" in r for r in results)

    def test_respects_limit(self, reader, store) -> None:
        from bear_rag.chunker import chunk_note

        notes = reader.read_notes()
        for note in notes:
            store.upsert_chunks(chunk_note(note))

        results = mcp_server.search_notes("note", limit=1)
        assert len(results) <= 1

    def test_empty_store_returns_empty(self, reader, store) -> None:
        results = mcp_server.search_notes("anything")
        assert results == []


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
