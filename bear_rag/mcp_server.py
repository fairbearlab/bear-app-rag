"""MCP server exposing Bear notes to Claude Code.

Local-only: runs over stdio, never exposes network transport.
Read-only: Bear SQLite accessed via ?mode=ro URI.
"""

import functools
import logging

from mcp.server.fastmcp import FastMCP

from bear_rag.bear_reader import BearReader
from bear_rag.status import get_status
from bear_rag.store import NoteStore
from bear_rag.sync import sync as run_sync

logger = logging.getLogger(__name__)


def _handle_errors(func):
    """Decorator that catches known exceptions and returns structured error dicts.

    Responses returned to the connected agent are intentionally generic: they
    must never embed local filesystem paths (which can leak the machine's
    username/home directory) or raw exception text (which can mask real bugs
    behind a confusing agent-facing message). Full detail — including the
    original exception and, for unexpected errors, a full traceback — is
    logged server-side only.
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except FileNotFoundError as exc:
            logger.error("Bear database not found: %s", exc)
            return {"error": "Bear database not found. Is Bear installed?"}
        except ValueError as exc:
            logger.error("Invalid input to %s: %s", func.__name__, exc)
            return {"error": "Invalid input. Check that arguments (e.g. dates) are well-formed."}
        except Exception:
            logger.exception("Unexpected error in %s", func.__name__)
            return {"error": "Internal error (see server logs)"}

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

    When *tags* are given, results are restricted to notes carrying any of them
    (OR semantics), excluding trashed and archived notes. Snapshot semantics:
    tag membership is resolved from *live* Bear SQL while chunk content comes
    from the indexed snapshot. A tag edited in Bear since the last sync can
    therefore filter against membership the index hasn't caught up to yet; the
    gap only affects tag edits since the last sync and self-heals on the next
    sync (see ADR-0004). For the same reason, each result's ``tags`` field is
    read from the indexed snapshot: a note may be included by the live filter on
    a freshly-added tag that does not yet appear in its returned ``tags`` list
    until the next sync.
    """
    store = _get_store()

    where = None
    if tags:
        reader = _get_reader()
        pks = reader.note_pks_for_tags(tags)
        # D4: a tag that resolves to no notes must short-circuit to an empty
        # result. Never pass {"$in": []} to Chroma — an empty list is a no-op
        # filter there, silently returning unfiltered matches.
        if not pks:
            return []
        where = {"note_pk": {"$in": sorted(pks)}}

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
    not just a chunk excerpt. Unlike search_notes/list_notes/list_tags, this is
    a deliberate direct fetch that can still return an *archived* note; the
    returned ``is_archived`` flag lets the caller mirror Bear's UX (D17).
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
        "is_archived": note.is_archived,
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
    Trashed and archived notes are excluded, mirroring Bear's own UI (D17).
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
    before drilling down with search_notes or list_notes. Counts exclude
    trashed and archived notes, mirroring Bear's own UI (D17).
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
    return get_status(_get_store())


def main():
    server.run(transport="stdio")
