"""Tests for bear_rag.sync — incremental sync and full index."""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from bear_rag.bear_reader import BearReader, CORE_DATA_EPOCH
from bear_rag.store import NoteStore
from bear_rag.sync import full_index, sync


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _datetime_to_core_data(dt: datetime) -> float:
    return (dt - CORE_DATA_EPOCH).total_seconds()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sync_state_path(tmp_path: Path) -> Path:
    return tmp_path / "last_sync.json"


@pytest.fixture
def mock_reader(bear_db: Path) -> BearReader:
    return BearReader(db_path=bear_db)


@pytest.fixture
def note_store_sync(tmp_path: Path) -> NoteStore:
    """Separate NoteStore for sync tests to avoid conflicts with conftest fixture."""
    return NoteStore(persist_dir=tmp_path / "chroma_sync")


@pytest.fixture
def empty_bear_db(tmp_path: Path) -> Path:
    """A Bear database containing only a trashed note."""
    db_path = tmp_path / "empty_database.sqlite"
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE ZSFNOTE (
            Z_PK INTEGER PRIMARY KEY,
            ZTITLE TEXT,
            ZTEXT TEXT,
            ZMODIFICATIONDATE REAL,
            ZTRASHED INTEGER DEFAULT 0,
            ZARCHIVED INTEGER DEFAULT 0
        )
    """)
    cur.execute("""
        CREATE TABLE ZSFNOTETAG (
            Z_PK INTEGER PRIMARY KEY,
            ZTITLE TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE Z_5TAGS (
            Z_5NOTES INTEGER,
            Z_13TAGS INTEGER
        )
    """)

    ts = _datetime_to_core_data(datetime(2024, 1, 1, tzinfo=timezone.utc))
    cur.execute(
        "INSERT INTO ZSFNOTE (Z_PK, ZTITLE, ZTEXT, ZMODIFICATIONDATE, ZTRASHED, ZARCHIVED) VALUES (?, ?, ?, ?, ?, ?)",
        (1, "Trashed Only", "This is trashed.", ts, 1, 0),
    )

    conn.commit()
    conn.close()
    return db_path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_first_sync_indexes_all_notes(mock_reader, note_store_sync, sync_state_path):
    """First sync with no state file should index all 3 non-trashed, non-archived notes."""
    result = sync(store=note_store_sync, reader=mock_reader, state_path=sync_state_path)

    # PKs 1, 2, 5 are non-trashed and non-archived
    assert result.notes_updated == 3
    assert result.chunks_added > 0
    assert note_store_sync.get_stats()["count"] > 0


def test_sync_writes_state_file(mock_reader, note_store_sync, sync_state_path):
    """After sync, state file must exist with 'timestamp' (float) and 'synced_at' (str)."""
    sync(store=note_store_sync, reader=mock_reader, state_path=sync_state_path)

    assert sync_state_path.exists()
    state = json.loads(sync_state_path.read_text())
    assert isinstance(state["timestamp"], float)
    assert isinstance(state["synced_at"], str)


def test_incremental_sync_only_updates_changed(mock_reader, note_store_sync, sync_state_path):
    """Second sync after a full first sync should report no changes."""
    sync(store=note_store_sync, reader=mock_reader, state_path=sync_state_path)
    count_after_first = note_store_sync.get_stats()["count"]

    result = sync(store=note_store_sync, reader=mock_reader, state_path=sync_state_path)

    assert result.notes_updated == 0
    assert note_store_sync.get_stats()["count"] == count_after_first


def test_dry_run_does_not_modify_store(mock_reader, note_store_sync, sync_state_path):
    """dry_run=True should report what would change but not write to store or state file."""
    result = sync(
        store=note_store_sync,
        reader=mock_reader,
        state_path=sync_state_path,
        dry_run=True,
    )

    assert result.notes_updated > 0
    assert note_store_sync.get_stats()["count"] == 0
    assert not sync_state_path.exists()


def test_full_index_resets_and_syncs(mock_reader, note_store_sync, sync_state_path):
    """full_index should clear stale data and re-index all current notes."""
    # Pre-populate with a stale chunk that belongs to a non-existent note pk 999
    from bear_rag.models import Chunk, ChunkMetadata
    stale_chunk = Chunk(
        id="999_0",
        text="Stale content",
        metadata=ChunkMetadata(
            note_pk=999,
            title="Stale Note",
            tags="",
            chunk_index=0,
            heading_path="",
            modified_at="2020-01-01T00:00:00+00:00",
            source="bear",
        ),
    )
    note_store_sync.upsert_chunks([stale_chunk])
    assert note_store_sync.get_stats()["count"] == 1

    result = full_index(store=note_store_sync, reader=mock_reader, state_path=sync_state_path)

    # Stale chunk must be gone
    stats = note_store_sync.get_stats()
    assert stats["count"] > 0

    # Verify stale chunk id "999_0" is no longer present by checking note PKs in store
    # (query with a broad search and verify 999 is absent from results)
    from bear_rag.store import NoteStore
    raw = note_store_sync._collection.get()
    note_pks_in_store = {m["note_pk"] for m in raw["metadatas"]}
    assert 999 not in note_pks_in_store

    assert result.notes_updated == 3
    assert result.chunks_added > 0


def test_sync_empty_db_returns_zero_result(empty_bear_db, tmp_path, sync_state_path):
    """Syncing a DB with only trashed notes should return zeros."""
    reader = BearReader(db_path=empty_bear_db)
    store = NoteStore(persist_dir=tmp_path / "chroma_empty")

    result = sync(store=store, reader=reader, state_path=sync_state_path)

    assert result.notes_updated == 0
    assert result.chunks_added == 0
