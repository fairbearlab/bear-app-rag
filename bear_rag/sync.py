"""Incremental sync and full index for Bear notes into the vector store."""

import json
from datetime import datetime, timezone
from pathlib import Path

from bear_rag import config
from bear_rag.bear_reader import BearReader, CORE_DATA_EPOCH
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
    """Write sync state (timestamp + human-readable synced_at) to *state_path*."""
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state = {
        "timestamp": timestamp,
        "synced_at": datetime.now(tz=timezone.utc).isoformat(),
    }
    state_path.write_text(json.dumps(state))


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

    last_timestamp = _read_timestamp(state_path)

    changed_notes = [
        note
        for note in reader.read_notes_modified_since(last_timestamp)
        if not note.is_archived
    ]
    trashed_pks = reader.read_trashed_pks()

    notes_updated = len(changed_notes)
    notes_deleted = len(trashed_pks)

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

    for pk in trashed_pks:
        store.delete_note(pk)

    # Compute new timestamp: max ZMODIFICATIONDATE from changed notes, converted
    # back to a Core Data timestamp float.
    if changed_notes:
        latest_dt = max(note.modified_at for note in changed_notes)
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
