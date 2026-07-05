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
        """Filtering by a single tag returns only chunks from notes carrying it.

        Uses pks that exist in the conftest ``bear_db`` fixture: tag 'work' is
        on note 1 (kept) and note 3 (trashed, excluded), so the reader resolves
        it to {1}.
        """
        _index_all_notes(reader, store)
        results = mcp_server.search_notes("note", tags=["work"])
        assert len(results) > 0
        pks = {r["note_pk"] for r in results}
        assert pks == {1}
        for r in results:
            assert "work" in r["tags"]

    def test_multi_tag_filter(self, reader, store) -> None:
        """Filtering by multiple tags returns chunks from notes matching any tag.

        'work' -> note 1, 'recent' -> note 2 in the conftest ``bear_db`` fixture.
        """
        _index_all_notes(reader, store)
        results = mcp_server.search_notes("note", tags=["work", "recent"])
        assert len(results) > 0
        pks = {r["note_pk"] for r in results}
        assert pks <= {1, 2}
        for r in results:
            assert "work" in r["tags"] or "recent" in r["tags"]

    def test_tag_filter_excludes_archived(self, reader, store) -> None:
        """Tag 'personal' is on note 1 (kept) and note 4 (archived); the archived
        note must not surface (D14)."""
        _index_all_notes(reader, store)
        results = mcp_server.search_notes("note", tags=["personal"])
        pks = {r["note_pk"] for r in results}
        assert 4 not in pks, "Archived note must not surface via tag filter"

    def test_no_match_tag_returns_empty(self, reader, store) -> None:
        """A tag that resolves to zero pks must short-circuit to [] (D4), never
        fall back to unfiltered matching via {"$in": []}."""
        _index_all_notes(reader, store)
        results = mcp_server.search_notes("note", tags=["nonexistent-tag-xyz"])
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

    def test_returns_is_archived_flag(self, reader) -> None:
        """read_note surfaces is_archived so callers can mirror Bear's UX (D17)."""
        result = mcp_server.read_note("Normal Note")
        assert result["is_archived"] is False

    def test_reads_archived_note_with_flag(self, reader) -> None:
        """read_note is a deliberate direct fetch: it STILL returns an archived
        note (unlike search/list), flagged is_archived=True (D17)."""
        result = mcp_server.read_note("Archived Note")
        assert "error" not in result
        assert result["title"] == "Archived Note"
        assert result["is_archived"] is True


class TestListNotes:
    def test_returns_all_non_trashed(self, reader) -> None:
        results = mcp_server.list_notes()
        pks = [r["note_pk"] for r in results]
        assert 3 not in pks  # trashed

    def test_excludes_archived(self, reader) -> None:
        """Archived notes must not surface via list_notes (D17)."""
        results = mcp_server.list_notes()
        pks = [r["note_pk"] for r in results]
        assert 4 not in pks  # archived

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
    def test_file_not_found_returns_generic_message_no_path(self, tmp_path) -> None:
        """FileNotFoundError must return a fixed generic message — never the DB path.

        bear_reader.py's own FileNotFoundError message embeds the full DB path
        (which embeds the user's home directory / username); the handler must
        not forward that to the connected agent.
        """
        mcp_server._reader = None
        mcp_server._store = None
        leaky_path = "/Users/definitely-not-a-real-user/Library/Group Containers/db.sqlite"
        with patch(
            "bear_rag.mcp_server._get_reader",
            side_effect=FileNotFoundError(f"Bear database not found at {leaky_path}. Is Bear installed?"),
        ):
            result = mcp_server.read_note("Any Title")
        assert result == {"error": "Bear database not found. Is Bear installed?"}
        assert leaky_path not in result["error"]

    def test_unexpected_exception_returns_generic_message(self) -> None:
        """An unexpected exception must return the generic catch-all message.

        Raw str(exc) must never reach the agent — it can leak filesystem
        paths or other local details, and it masks the real bug behind a
        confusing agent-facing message.
        """
        mcp_server._reader = None
        mcp_server._store = None
        leaky_path = "/Users/definitely-not-a-real-user/some-internal-state.db"
        with patch(
            "bear_rag.mcp_server._get_reader",
            side_effect=RuntimeError(f"unexpected failure touching {leaky_path}"),
        ):
            result = mcp_server.read_note("Any Title")
        assert result == {"error": "Internal error (see server logs)"}
        assert leaky_path not in result["error"]

    def test_value_error_response_has_no_filesystem_path(self, reader) -> None:
        """The ValueError handler's response must also carry no filesystem path."""
        result = mcp_server.list_notes(modified_since="not-a-date")
        assert "error" in result
        assert str(config.BEAR_DB_PATH) not in result["error"]

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
