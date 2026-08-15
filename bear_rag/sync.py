"""Incremental sync and full index for Bear notes into the vector store."""

import json
from datetime import UTC, datetime
from pathlib import Path

from bear_rag import config
from bear_rag.bear_reader import CORE_DATA_EPOCH, BearReader
from bear_rag.chunker import chunk_note
from bear_rag.models import SyncResult
from bear_rag.store import NoteStore


def _read_timestamp(state_path: Path) -> float:
    """Return the last-synced Core Data timestamp, or 0.0 if the state file doesn't exist."""
    if not state_path.exists():
        return 0.0
    try:
        state = json.loads(state_path.read_text())
        return float(state.get("timestamp", 0.0))
    except (json.JSONDecodeError, KeyError, ValueError):
        return 0.0


def _write_state(state_path: Path, timestamp: float) -> None:
    """Write sync state (timestamp + human-readable synced_at + index version) to *state_path*."""
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state = {
        "timestamp": timestamp,
        "synced_at": datetime.now(tz=UTC).isoformat(),
        "index_version": config.INDEX_VERSION,
    }
    state_path.write_text(json.dumps(state))


def check_index_version(state_path: Path = config.SYNC_STATE_PATH) -> bool:
    """Return True if the stored index version matches the current version.

    Returns True (compatible) when no state file exists (fresh install).
    """
    if not state_path.exists():
        return True
    try:
        state = json.loads(state_path.read_text())
        return state.get("index_version") == config.INDEX_VERSION
    except (json.JSONDecodeError, KeyError, ValueError):
        return False


def sync(
    store: NoteStore,
    reader: BearReader | None = None,
    state_path: Path = config.SYNC_STATE_PATH,
    dry_run: bool = False,
) -> SyncResult:
    """Incrementally sync changed Bear notes into *store*.

    Parameters
    ----------
    store:
        The :class:`~bear_rag.store.NoteStore` to update.
    reader:
        A :class:`~bear_rag.bear_reader.BearReader` instance.  Defaults to
        one pointing at the configured Bear database path.
    state_path:
        Path to the JSON file used to persist the last-sync timestamp.
    dry_run:
        When *True*, compute what would change but do not modify *store* or
        write *state_path*.

    Returns
    -------
    SyncResult
        Counts of notes updated, notes deleted and chunks added.
    """
    if reader is None:
        reader = BearReader(db_path=config.BEAR_DB_PATH)

    if not check_index_version(state_path):
        return full_index(store=store, reader=reader, state_path=state_path)

    last_timestamp = _read_timestamp(state_path)

    # Notes modified since the last sync. This query excludes trashed notes but
    # *includes* archived ones, so we can both advance the cursor past
    # archive-only edits (D12) and drop archived notes from the update set.
    modified_notes = reader.read_notes_modified_since(last_timestamp)
    changed_notes = [note for note in modified_notes if not note.is_archived]

    # Reconciliation (D18): the index must mirror Bear's live *active* set
    # (non-trashed, non-archived). Any note still in the index but absent from
    # that set — archived, trashed, or deleted outright — is stale and removed.
    # We diff indexed pks against live active pks rather than relying on
    # archived/trashed notes surfacing in the modified-since scan: a read-only
    # probe of the real Bear DB could not confirm archiving reliably bumps
    # ZMODIFICATIONDATE (and trashing does not), so reconciliation is the fix
    # that holds either way. It also subsumes the old trashed-pk deletion.
    active_pks = reader.read_active_pks()
    stale_pks = store.indexed_note_pks() - active_pks

    notes_updated = len(changed_notes)
    notes_deleted = len(stale_pks)

    # Chunk all changed notes once (used for both dry-run counting and upserting).
    chunks_by_note = [(note, chunk_note(note)) for note in changed_notes]
    chunks_added = sum(len(chunks) for _, chunks in chunks_by_note)

    if dry_run:
        return SyncResult(
            notes_updated=notes_updated,
            notes_deleted=notes_deleted,
            chunks_added=chunks_added,
        )

    # Apply changes to the store
    for note, chunks in chunks_by_note:
        store.delete_note(note.pk)
        store.upsert_chunks(chunks)

    for pk in stale_pks:
        store.delete_note(pk)

    # Compute the new cursor: max ZMODIFICATIONDATE across ALL notes modified
    # since the last sync — kept *and* archived (D12). The previous code advanced
    # only over kept notes, so an archive-only edit (when it bumps
    # ZMODIFICATIONDATE) would never move the cursor, re-scanning that row and
    # reporting phantom deletes on every run. Trashed rows are excluded from the
    # modified-since scan by design and are handled by reconciliation, so they
    # need no part in the cursor.
    if modified_notes:
        latest_dt = max(note.modified_at for note in modified_notes)
        new_timestamp = (latest_dt - CORE_DATA_EPOCH).total_seconds()
    else:
        new_timestamp = last_timestamp

    _write_state(state_path, new_timestamp)

    return SyncResult(
        notes_updated=notes_updated,
        notes_deleted=notes_deleted,
        chunks_added=chunks_added,
    )


def full_index(
    store: NoteStore,
    reader: BearReader | None = None,
    state_path: Path = config.SYNC_STATE_PATH,
) -> SyncResult:
    """Wipe *store* and re-index all notes from scratch.

    Parameters
    ----------
    store:
        The :class:`~bear_rag.store.NoteStore` to rebuild.
    reader:
        A :class:`~bear_rag.bear_reader.BearReader` instance.  Defaults to
        one pointing at the configured Bear database path.
    state_path:
        Path to the sync state file; deleted before re-indexing so that
        :func:`sync` picks up all notes.
    """
    store.reset()

    if state_path.exists():
        state_path.unlink()

    return sync(store=store, reader=reader, state_path=state_path)
