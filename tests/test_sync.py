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


def test_sync_removes_archived_note_chunks(
    mock_reader, note_store_sync, sync_state_path, bear_db
):
    """Regression (D6/D18): a note archived after indexing must have its chunks
    removed on the next sync.

    The note is archived WITHOUT bumping ZMODIFICATIONDATE — the worst case for a
    modified-since-based deletion strategy (archiving may not touch the mod date;
    verification was inconclusive). Reconciliation must catch it regardless.
    """
    sync(store=note_store_sync, reader=mock_reader, state_path=sync_state_path)
    assert 1 in note_store_sync.indexed_note_pks(), "note 1 should be indexed initially"

    # Archive note 1 in Bear, leaving ZMODIFICATIONDATE untouched.
    conn = sqlite3.connect(str(bear_db))
    conn.execute("UPDATE ZSFNOTE SET ZARCHIVED = 1 WHERE Z_PK = 1")
    conn.commit()
    conn.close()

    result = sync(store=note_store_sync, reader=mock_reader, state_path=sync_state_path)

    assert result.notes_deleted == 1
    assert 1 not in note_store_sync.indexed_note_pks(), "archived note's chunks must be gone"


def test_second_sync_after_archive_is_idempotent(
    mock_reader, note_store_sync, sync_state_path, bear_db
):
    """Regression (D12): once an archived note is reconciled away, further syncs
    must report 0 updated / 0 deleted — no phantom re-deletes, stable counts."""
    sync(store=note_store_sync, reader=mock_reader, state_path=sync_state_path)

    conn = sqlite3.connect(str(bear_db))
    conn.execute("UPDATE ZSFNOTE SET ZARCHIVED = 1 WHERE Z_PK = 1")
    conn.commit()
    conn.close()

    sync(store=note_store_sync, reader=mock_reader, state_path=sync_state_path)  # removes note 1
    result = sync(store=note_store_sync, reader=mock_reader, state_path=sync_state_path)

    assert result.notes_updated == 0
    assert result.notes_deleted == 0


def test_repeated_sync_no_changes_is_idempotent(
    mock_reader, note_store_sync, sync_state_path
):
    """A plain second sync with no Bear changes reports 0 updated / 0 deleted."""
    sync(store=note_store_sync, reader=mock_reader, state_path=sync_state_path)
    result = sync(store=note_store_sync, reader=mock_reader, state_path=sync_state_path)
    assert result.notes_updated == 0
    assert result.notes_deleted == 0


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

    # Verify stale chunk id "999_0" is no longer present.
    assert 999 not in note_store_sync.indexed_note_pks()

    assert result.notes_updated == 3
    assert result.chunks_added > 0


def test_sync_empty_db_returns_zero_result(empty_bear_db, tmp_path, sync_state_path):
    """Syncing a DB with only trashed notes should return zeros."""
    reader = BearReader(db_path=empty_bear_db)
    store = NoteStore(persist_dir=tmp_path / "chroma_empty")

    result = sync(store=store, reader=reader, state_path=sync_state_path)

    assert result.notes_updated == 0
    assert result.chunks_added == 0


def test_sync_writes_index_version(mock_reader, note_store_sync, sync_state_path):
    """Sync state file should include the current index version."""
    sync(store=note_store_sync, reader=mock_reader, state_path=sync_state_path)

    state = json.loads(sync_state_path.read_text())
    from bear_rag import config
    assert state["index_version"] == config.INDEX_VERSION


# ---------------------------------------------------------------------------
# check_index_version
# ---------------------------------------------------------------------------

def test_sync_triggers_full_reindex_on_version_mismatch(
    mock_reader, note_store_sync, sync_state_path
):
    """sync() should force a full reindex when the stored index version doesn't match."""
    # First sync to populate the store and state file.
    result = sync(store=note_store_sync, reader=mock_reader, state_path=sync_state_path)
    initial_count = result.notes_updated
    assert initial_count > 0

    # Tamper with the stored version to simulate an upgrade.
    state = json.loads(sync_state_path.read_text())
    state["index_version"] = -999
    sync_state_path.write_text(json.dumps(state))

    # Next sync should detect the mismatch and do a full reindex.
    result2 = sync(store=note_store_sync, reader=mock_reader, state_path=sync_state_path)
    assert result2.notes_updated == initial_count  # all notes re-indexed

    # State file should now have the correct version.
    from bear_rag import config
    state2 = json.loads(sync_state_path.read_text())
    assert state2["index_version"] == config.INDEX_VERSION


def test_check_index_version_matches(tmp_path):
    """Returns True when stored version matches current."""
    from bear_rag.sync import check_index_version
    from bear_rag import config

    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"timestamp": 0.0, "index_version": config.INDEX_VERSION}))
    assert check_index_version(state_path) is True


def test_check_index_version_mismatch(tmp_path):
    """Returns False when stored version is outdated."""
    from bear_rag.sync import check_index_version

    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"timestamp": 0.0, "index_version": 1}))
    assert check_index_version(state_path) is False


def test_check_index_version_no_file(tmp_path):
    """Returns True when no state file exists (fresh install)."""
    from bear_rag.sync import check_index_version

    assert check_index_version(tmp_path / "nonexistent.json") is True


def test_check_index_version_missing_field(tmp_path):
    """Returns False when state file has no index_version field."""
    from bear_rag.sync import check_index_version

    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"timestamp": 0.0}))
    assert check_index_version(state_path) is False
