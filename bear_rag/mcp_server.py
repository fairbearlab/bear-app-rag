"""MCP server exposing Bear notes to Claude Code.

Local-only: runs over stdio, never exposes network transport.
Read-only: Bear SQLite accessed via ?mode=ro URI.
"""

import functools

from mcp.server.fastmcp import FastMCP

from bear_rag import config
from bear_rag.bear_reader import BearReader
from bear_rag.store import NoteStore
from bear_rag.sync import sync as run_sync


def _handle_errors(func):
    """Decorator that catches known exceptions and returns structured error dicts."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except FileNotFoundError as exc:
            return {"error": f"Bear database not found: {exc}"}
        except ValueError as exc:
            return {"error": f"Invalid input: {exc}"}

    return wrapper

server = FastMCP("bear-notes")

_reader = None
_store = None


def _get_reader() -> BearReader:
    global _reader
    if _reader is None:
        _reader = BearReader()
    return _reader


def _get_store() -> NoteStore:
    global _store
    if _store is None:
        _store = NoteStore()
    return _store


@server.tool()
@_handle_errors
def search_notes(query: str, tags: list[str] | None = None, limit: int = 10) -> list[dict]:
    """Semantic search over Bear notes. Finds content by meaning.

    Use this to discover notes relevant to a topic. Returns ranked chunks
    (excerpts) with metadata. For full note text, follow up with read_note.
    """
    store = _get_store()

    where = None
    if tags:
        if len(tags) == 1:
            where = {"tags": {"$contains": "," + tags[0] + ","}}
        else:
            where = {"$or": [{"tags": {"$contains": "," + t + ","}} for t in tags]}

    chunks = store.query(text=query, n_results=limit, where=where)
    return [
        {
            "title": c.metadata["title"],
            "text": c.text,
            "tags": [t for t in c.metadata["tags"].split(",") if t],
            "heading_path": c.metadata["heading_path"],
            "note_pk": c.metadata["note_pk"],
            "chunk_index": c.metadata["chunk_index"],
            "modified_at": c.metadata["modified_at"],
        }
        for c in chunks
    ]


@server.tool()
@_handle_errors
def read_note(title: str) -> dict:
    """Get the full text of a specific Bear note by title (case-insensitive).

    Use this after search_notes when you need the complete note content,
    not just a chunk excerpt.
    """
    reader = _get_reader()
    note = reader.read_note_by_title(title)
    if note is None:
        return {"error": f"No note found with title '{title}'"}
    return {
        "title": note.title,
        "text": note.text,
        "tags": note.tags,
        "modified_at": note.modified_at.isoformat(),
    }


@server.tool()
@_handle_errors
def list_notes(
    tag: str | None = None,
    modified_since: str | None = None,
    modified_before: str | None = None,
    title_contains: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """Browse and filter Bear notes by metadata.

    Returns note metadata (title, tags, date) without full text.
    Use read_note to get the full content of specific notes.
    All parameters are optional. With no filters, returns the most recent notes.
    Date parameters use ISO format (e.g. "2026-01-01").
    """
    reader = _get_reader()
    notes = reader.list_notes(
        tag=tag,
        modified_since=modified_since,
        modified_before=modified_before,
        title_contains=title_contains,
        limit=limit,
    )
    return [
        {
            "title": n.title,
            "tags": n.tags,
            "modified_at": n.modified_at.isoformat(),
            "note_pk": n.pk,
        }
        for n in notes
    ]


@server.tool()
@_handle_errors
def list_tags() -> list[dict]:
    """List all Bear note tags with note counts.

    Use this to discover what topics and categories exist in the notes
    before drilling down with search_notes or list_notes.
    """
    reader = _get_reader()
    tags = reader.list_tags()
    return [{"tag": name, "count": count} for name, count in tags]


@server.tool()
@_handle_errors
def sync_notes() -> dict:
    """Sync recent Bear note changes into the search index.

    Run this if notes were recently edited in Bear and you want
    the latest content available for search.
    """
    store = _get_store()
    reader = _get_reader()
    result = run_sync(store=store, reader=reader)
    return {
        "notes_updated": result.notes_updated,
        "notes_deleted": result.notes_deleted,
        "chunks_indexed": result.chunks_added,
    }


@server.tool()
@_handle_errors
def status() -> dict:
    """Show the current state of the search index.

    Returns the number of indexed chunks, unique notes, and the last sync
    timestamp. Use this to check whether the index is populated and fresh.
    """
    store = _get_store()
    stats = store.get_stats()

    last_sync = None
    if config.SYNC_STATE_PATH.exists():
        import json

        try:
            state = json.loads(config.SYNC_STATE_PATH.read_text())
            last_sync = state.get("synced_at")
        except (json.JSONDecodeError, KeyError):
            pass

    return {
        "index_count": stats["count"],
        "note_count": stats["note_count"],
        "last_sync": last_sync,
    }


def main():
    server.run(transport="stdio")
