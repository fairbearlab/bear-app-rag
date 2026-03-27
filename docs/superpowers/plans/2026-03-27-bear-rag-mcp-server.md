# Bear Notes MCP Server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose Bear notes to Claude Code via an MCP server with 5 tools: semantic search, full-note read, metadata browsing, tag listing, and sync.

**Architecture:** Thin MCP server (`mcp_server.py`) over stdio, delegating to existing `BearReader`, `NoteStore`, and `sync` modules. Three new `BearReader` methods for structured queries. One new `NoteStore` method for filtered vector search.

**Tech Stack:** Python 3.11+, `mcp` SDK (FastMCP), existing ChromaDB + SQLite stack.

---

### Task 1: Add `mcp` dependency and entry point

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add `mcp` to dependencies and `bear-rag-mcp` entry point**

In `pyproject.toml`, add `mcp` to the dependencies list and a new entry point:

```toml
[project]
name = "bear-rag"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "anthropic>=0.49,<1.0",
    "chromadb>=1.0,<2.0",
    "mcp>=1.0,<2.0",
    "python-dotenv>=1.0,<2.0",
]

[project.optional-dependencies]
dev = ["pytest>=9.0,<10.0"]

[project.scripts]
bear-rag = "bear_rag.cli:main"
bear-rag-mcp = "bear_rag.mcp_server:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

- [ ] **Step 2: Install updated dependencies**

Run: `uv sync`
Expected: Installs `mcp` SDK and its dependencies. No errors.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "feat: add mcp dependency and bear-rag-mcp entry point"
```

---

### Task 2: BearReader.list_tags()

**Files:**
- Test: `tests/test_bear_reader.py`
- Modify: `bear_rag/bear_reader.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_bear_reader.py`:

```python
class TestBearReaderListTags:
    def test_returns_tags_with_counts(self, bear_db: Path) -> None:
        reader = BearReader(bear_db)
        tags = reader.list_tags()
        tag_dict = dict(tags)
        # From conftest: "work" on notes 1,3 but note 3 is trashed -> count 1
        # "personal" on notes 1,4 but note 4 is archived (not trashed) -> count 2
        # "recent" on note 2 -> count 1
        assert tag_dict["personal"] == 2
        assert tag_dict["work"] == 1
        assert tag_dict["recent"] == 1

    def test_sorted_by_count_descending(self, bear_db: Path) -> None:
        reader = BearReader(bear_db)
        tags = reader.list_tags()
        counts = [count for _, count in tags]
        assert counts == sorted(counts, reverse=True)

    def test_excludes_trashed_notes(self, bear_db: Path) -> None:
        reader = BearReader(bear_db)
        tags = reader.list_tags()
        tag_dict = dict(tags)
        # "work" is on note 1 (not trashed) and note 3 (trashed)
        # Should only count note 1
        assert tag_dict["work"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/adamboulware/Docker/bear-app-rag && uv run pytest tests/test_bear_reader.py::TestBearReaderListTags -v`
Expected: FAIL with `AttributeError: 'BearReader' object has no attribute 'list_tags'`

- [ ] **Step 3: Write minimal implementation**

Add to `bear_rag/bear_reader.py`, inside the `BearReader` class:

```python
def list_tags(self) -> list[tuple[str, int]]:
    """Return (tag_name, note_count) tuples sorted by count descending. Only counts non-trashed notes."""
    query = """
        SELECT t.ZTITLE, COUNT(*) as cnt
        FROM ZSFNOTETAG t
        JOIN Z_5TAGS jt ON jt.Z_13TAGS = t.Z_PK
        JOIN ZSFNOTE n ON n.Z_PK = jt.Z_5NOTES
        WHERE n.ZTRASHED = 0
        GROUP BY t.ZTITLE
        ORDER BY cnt DESC
    """
    with self._connect() as conn:
        cur = conn.cursor()
        cur.execute(query)
        return [(row[0], row[1]) for row in cur.fetchall()]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/adamboulware/Docker/bear-app-rag && uv run pytest tests/test_bear_reader.py::TestBearReaderListTags -v`
Expected: 3 tests PASS

- [ ] **Step 5: Run full test suite**

Run: `cd /Users/adamboulware/Docker/bear-app-rag && uv run pytest -v`
Expected: All tests PASS (existing + new)

- [ ] **Step 6: Commit**

```bash
git add bear_rag/bear_reader.py tests/test_bear_reader.py
git commit -m "feat: add BearReader.list_tags() with non-trashed filtering"
```

---

### Task 3: BearReader.read_note_by_title()

**Files:**
- Test: `tests/test_bear_reader.py`
- Modify: `bear_rag/bear_reader.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_bear_reader.py`:

```python
class TestBearReaderReadNoteByTitle:
    def test_finds_note_by_exact_title(self, bear_db: Path) -> None:
        reader = BearReader(bear_db)
        note = reader.read_note_by_title("Normal Note")
        assert note is not None
        assert note.pk == 1
        assert note.title == "Normal Note"
        assert note.text == "This is a normal note."

    def test_case_insensitive_match(self, bear_db: Path) -> None:
        reader = BearReader(bear_db)
        note = reader.read_note_by_title("normal note")
        assert note is not None
        assert note.pk == 1

    def test_returns_none_for_missing_title(self, bear_db: Path) -> None:
        reader = BearReader(bear_db)
        note = reader.read_note_by_title("Nonexistent Note")
        assert note is None

    def test_excludes_trashed_notes(self, bear_db: Path) -> None:
        reader = BearReader(bear_db)
        note = reader.read_note_by_title("Trashed Note")
        assert note is None

    def test_includes_tags(self, bear_db: Path) -> None:
        reader = BearReader(bear_db)
        note = reader.read_note_by_title("Normal Note")
        assert note is not None
        assert sorted(note.tags) == ["personal", "work"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/adamboulware/Docker/bear-app-rag && uv run pytest tests/test_bear_reader.py::TestBearReaderReadNoteByTitle -v`
Expected: FAIL with `AttributeError: 'BearReader' object has no attribute 'read_note_by_title'`

- [ ] **Step 3: Write minimal implementation**

Add to `bear_rag/bear_reader.py`, inside the `BearReader` class:

```python
def read_note_by_title(self, title: str) -> BearNote | None:
    """Return a non-trashed note matching the title (case-insensitive), or None."""
    query = """
        SELECT
            n.Z_PK, n.ZTITLE, n.ZTEXT,
            n.ZMODIFICATIONDATE, n.ZTRASHED, n.ZARCHIVED
        FROM ZSFNOTE n
        WHERE LOWER(n.ZTITLE) = LOWER(?) AND n.ZTRASHED = 0
    """
    with self._connect() as conn:
        cur = conn.cursor()
        cur.execute(query, (title,))
        rows = cur.fetchall()
        if not rows:
            return None
        notes = self._rows_to_notes(rows, cur)
        return notes[0]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/adamboulware/Docker/bear-app-rag && uv run pytest tests/test_bear_reader.py::TestBearReaderReadNoteByTitle -v`
Expected: 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add bear_rag/bear_reader.py tests/test_bear_reader.py
git commit -m "feat: add BearReader.read_note_by_title() with case-insensitive lookup"
```

---

### Task 4: BearReader.list_notes()

**Files:**
- Test: `tests/test_bear_reader.py`
- Modify: `bear_rag/bear_reader.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_bear_reader.py`. You'll need to import `datetime` and `timezone` (already imported in the file):

```python
class TestBearReaderListNotes:
    def test_no_filters_returns_non_trashed(self, bear_db: Path) -> None:
        reader = BearReader(bear_db)
        notes = reader.list_notes()
        pks = [n.pk for n in notes]
        assert 3 not in pks, "Trashed note should be excluded"
        assert len(notes) == 4  # notes 1, 2, 4, 5

    def test_filter_by_tag(self, bear_db: Path) -> None:
        reader = BearReader(bear_db)
        notes = reader.list_notes(tag="work")
        pks = [n.pk for n in notes]
        assert pks == [1], f"Expected only note 1 with tag 'work', got {pks}"

    def test_filter_by_modified_since(self, bear_db: Path) -> None:
        reader = BearReader(bear_db)
        notes = reader.list_notes(modified_since="2024-06-10")
        pks = [n.pk for n in notes]
        assert 2 in pks, "Recent note should be included"
        assert 5 not in pks, "Old note should be excluded"

    def test_filter_by_modified_before(self, bear_db: Path) -> None:
        reader = BearReader(bear_db)
        notes = reader.list_notes(modified_before="2024-02-01")
        pks = [n.pk for n in notes]
        # Notes with older timestamp: 4 (archived, Jan 1) and 5 (no tags, Jan 1)
        assert all(pk in [4, 5] for pk in pks)

    def test_filter_by_title_contains(self, bear_db: Path) -> None:
        reader = BearReader(bear_db)
        notes = reader.list_notes(title_contains="recent")
        pks = [n.pk for n in notes]
        assert pks == [2]

    def test_title_contains_case_insensitive(self, bear_db: Path) -> None:
        reader = BearReader(bear_db)
        notes = reader.list_notes(title_contains="NORMAL")
        pks = [n.pk for n in notes]
        assert pks == [1]

    def test_limit(self, bear_db: Path) -> None:
        reader = BearReader(bear_db)
        notes = reader.list_notes(limit=2)
        assert len(notes) <= 2

    def test_combined_filters(self, bear_db: Path) -> None:
        reader = BearReader(bear_db)
        notes = reader.list_notes(tag="personal", title_contains="normal")
        pks = [n.pk for n in notes]
        assert pks == [1]

    def test_ordered_by_modified_descending(self, bear_db: Path) -> None:
        reader = BearReader(bear_db)
        notes = reader.list_notes()
        dates = [n.modified_at for n in notes]
        assert dates == sorted(dates, reverse=True)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/adamboulware/Docker/bear-app-rag && uv run pytest tests/test_bear_reader.py::TestBearReaderListNotes -v`
Expected: FAIL with `AttributeError: 'BearReader' object has no attribute 'list_notes'`

- [ ] **Step 3: Write minimal implementation**

Add to `bear_rag/bear_reader.py`. First, add this helper function at module level (after the existing `_core_data_to_datetime`):

```python
def _datetime_to_core_data(dt: datetime) -> float:
    """Convert a datetime to a Core Data timestamp (seconds since 2001-01-01 UTC)."""
    return (dt - CORE_DATA_EPOCH).total_seconds()
```

Then add to the `BearReader` class:

```python
def list_notes(
    self,
    tag: str | None = None,
    modified_since: str | None = None,
    modified_before: str | None = None,
    title_contains: str | None = None,
    limit: int = 50,
) -> list[BearNote]:
    """Return non-trashed notes matching the given filters, ordered by modified date descending."""
    conditions = ["n.ZTRASHED = 0"]
    params: list = []
    joins = ""

    if tag is not None:
        joins = """
            JOIN Z_5TAGS jt ON jt.Z_5NOTES = n.Z_PK
            JOIN ZSFNOTETAG t ON t.Z_PK = jt.Z_13TAGS
        """
        conditions.append("t.ZTITLE = ?")
        params.append(tag)

    if modified_since is not None:
        dt = datetime.fromisoformat(modified_since).replace(tzinfo=timezone.utc)
        conditions.append("n.ZMODIFICATIONDATE > ?")
        params.append(_datetime_to_core_data(dt))

    if modified_before is not None:
        dt = datetime.fromisoformat(modified_before).replace(tzinfo=timezone.utc)
        conditions.append("n.ZMODIFICATIONDATE < ?")
        params.append(_datetime_to_core_data(dt))

    if title_contains is not None:
        conditions.append("LOWER(n.ZTITLE) LIKE ?")
        params.append(f"%{title_contains.lower()}%")

    where_clause = " AND ".join(conditions)
    query = f"""
        SELECT
            n.Z_PK, n.ZTITLE, n.ZTEXT,
            n.ZMODIFICATIONDATE, n.ZTRASHED, n.ZARCHIVED
        FROM ZSFNOTE n
        {joins}
        WHERE {where_clause}
        ORDER BY n.ZMODIFICATIONDATE DESC
        LIMIT ?
    """
    params.append(limit)

    with self._connect() as conn:
        cur = conn.cursor()
        cur.execute(query, params)
        return self._rows_to_notes(cur.fetchall(), cur)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/adamboulware/Docker/bear-app-rag && uv run pytest tests/test_bear_reader.py::TestBearReaderListNotes -v`
Expected: 9 tests PASS

- [ ] **Step 5: Run full test suite**

Run: `cd /Users/adamboulware/Docker/bear-app-rag && uv run pytest -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add bear_rag/bear_reader.py tests/test_bear_reader.py
git commit -m "feat: add BearReader.list_notes() with tag, date, and title filters"
```

---

### Task 5: NoteStore.query() with tag filtering

**Files:**
- Test: `tests/test_store.py`
- Modify: `bear_rag/store.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_store.py`:

```python
from bear_rag.models import Chunk, ChunkMetadata


def _make_chunk(note_pk: int, chunk_index: int, text: str, tags: str = "", title: str = "Test") -> Chunk:
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
    def test_query_filters_by_single_tag(self, note_store: NoteStore) -> None:
        note_store.upsert_chunks([
            _make_chunk(1, 0, "Python web framework tutorial", tags="python,web"),
            _make_chunk(2, 0, "Rust systems programming guide", tags="rust,systems"),
            _make_chunk(3, 0, "Python data science notebook", tags="python,data"),
        ])
        results = note_store.query("programming", n_results=10, where={"tags": {"$contains": "python"}})
        result_pks = {c.metadata["note_pk"] for c in results}
        assert result_pks == {1, 3}

    def test_query_without_filter_returns_all(self, note_store: NoteStore) -> None:
        note_store.upsert_chunks([
            _make_chunk(1, 0, "Python web framework tutorial", tags="python,web"),
            _make_chunk(2, 0, "Rust systems programming guide", tags="rust,systems"),
        ])
        results = note_store.query("programming", n_results=10)
        assert len(results) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/adamboulware/Docker/bear-app-rag && uv run pytest tests/test_store.py::TestNoteStoreQueryWithFilter -v`
Expected: FAIL with `TypeError: query() got an unexpected keyword argument 'where'`

- [ ] **Step 3: Write minimal implementation**

Modify the `query` method in `bear_rag/store.py` to accept an optional `where` parameter:

```python
def query(self, text: str, n_results: int = 5, where: dict | None = None) -> list[Chunk]:
    """Return up to n_results chunks most relevant to text, optionally filtered by where clause."""
    count = self._collection.count()
    if count == 0:
        return []
    n_results = min(n_results, count)
    raw = self._collection.query(query_texts=[text], n_results=n_results, where=where)

    chunks: list[Chunk] = []
    for chunk_id, document, metadata in zip(
        raw["ids"][0], raw["documents"][0], raw["metadatas"][0]
    ):
        chunk_metadata = ChunkMetadata(
            note_pk=int(metadata["note_pk"]),
            title=str(metadata["title"]),
            tags=str(metadata["tags"]),
            chunk_index=int(metadata["chunk_index"]),
            heading_path=str(metadata["heading_path"]),
            modified_at=str(metadata["modified_at"]),
            source=str(metadata["source"]),
        )
        chunks.append(Chunk(id=chunk_id, text=document, metadata=chunk_metadata))
    return chunks
```

The key change: add `where: dict | None = None` parameter and pass it to `self._collection.query()`. ChromaDB's `query()` already accepts `where=None` as a no-op.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/adamboulware/Docker/bear-app-rag && uv run pytest tests/test_store.py::TestNoteStoreQueryWithFilter -v`
Expected: 2 tests PASS

- [ ] **Step 5: Run full test suite**

Run: `cd /Users/adamboulware/Docker/bear-app-rag && uv run pytest -v`
Expected: All tests PASS (existing query tests still work since `where` defaults to `None`)

- [ ] **Step 6: Commit**

```bash
git add bear_rag/store.py tests/test_store.py
git commit -m "feat: add optional where filter to NoteStore.query()"
```

---

### Task 6: CLI --quiet flag for sync

**Files:**
- Test: `tests/test_cli.py`
- Modify: `bear_rag/cli.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_cli.py`:

```python
@patch("bear_rag.cli.BearReader")
@patch("bear_rag.cli.NoteStore")
@patch("bear_rag.cli.sync")
def test_sync_quiet_suppresses_no_change_output(mock_sync, mock_store_cls, mock_reader_cls, monkeypatch, capsys):
    """bear-rag sync --quiet should print nothing when there are no changes."""
    monkeypatch.setattr("sys.argv", ["bear-rag", "sync", "--quiet"])
    mock_sync.return_value = MagicMock(notes_updated=0, notes_deleted=0, chunks_added=0)

    main()

    captured = capsys.readouterr()
    assert captured.out == ""


@patch("bear_rag.cli.BearReader")
@patch("bear_rag.cli.NoteStore")
@patch("bear_rag.cli.sync")
def test_sync_quiet_prints_when_changes(mock_sync, mock_store_cls, mock_reader_cls, monkeypatch, capsys):
    """bear-rag sync --quiet should still print when there are changes."""
    monkeypatch.setattr("sys.argv", ["bear-rag", "sync", "--quiet"])
    mock_sync.return_value = MagicMock(notes_updated=3, notes_deleted=1, chunks_added=12)

    main()

    captured = capsys.readouterr()
    assert "3" in captured.out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/adamboulware/Docker/bear-app-rag && uv run pytest tests/test_cli.py::test_sync_quiet_suppresses_no_change_output tests/test_cli.py::test_sync_quiet_prints_when_changes -v`
Expected: FAIL (unrecognized argument `--quiet`)

- [ ] **Step 3: Write minimal implementation**

In `bear_rag/cli.py`, modify the sync subparser and `_cmd_sync` function:

Add `--quiet` argument to the sync subparser (after the `--dry-run` argument):

```python
sync_parser.add_argument(
    "--quiet",
    action="store_true",
    default=False,
    help="Suppress output when there are no changes.",
)
```

Modify `_cmd_sync` to check for the quiet flag:

```python
def _cmd_sync(args, store, reader):
    dry_run = args.dry_run
    quiet = args.quiet
    if dry_run:
        print("Dry run — no changes will be made.")
    try:
        result = sync(store=store, reader=reader, dry_run=dry_run)
    except Exception as exc:
        print(f"Error during sync: {exc}", file=sys.stderr)
        print("Try running 'bear-rag index' to rebuild the index.", file=sys.stderr)
        sys.exit(1)
    if quiet and result.notes_updated == 0 and result.notes_deleted == 0:
        return
    verb = "Would update" if dry_run else "Updated"
    _print_sync_result(result, verb=verb)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/adamboulware/Docker/bear-app-rag && uv run pytest tests/test_cli.py::test_sync_quiet_suppresses_no_change_output tests/test_cli.py::test_sync_quiet_prints_when_changes -v`
Expected: 2 tests PASS

- [ ] **Step 5: Run full test suite**

Run: `cd /Users/adamboulware/Docker/bear-app-rag && uv run pytest -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add bear_rag/cli.py tests/test_cli.py
git commit -m "feat: add --quiet flag to sync for use in pre-session hooks"
```

---

### Task 7: MCP server module

**Files:**
- Create: `bear_rag/mcp_server.py`

- [ ] **Step 1: Create the MCP server module**

Create `bear_rag/mcp_server.py`:

```python
"""MCP server exposing Bear notes to Claude Code.

Local-only: runs over stdio, never exposes network transport.
Read-only: Bear SQLite accessed via ?mode=ro URI.
"""

from mcp.server.fastmcp import FastMCP

from bear_rag.bear_reader import BearReader
from bear_rag.store import NoteStore
from bear_rag.sync import sync as run_sync

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
def search_notes(query: str, tags: list[str] | None = None, limit: int = 10) -> list[dict]:
    """Semantic search over Bear notes. Finds content by meaning.

    Use this to discover notes relevant to a topic. Returns ranked chunks
    (excerpts) with metadata. For full note text, follow up with read_note.
    """
    store = _get_store()

    where = None
    if tags:
        if len(tags) == 1:
            where = {"tags": {"$contains": tags[0]}}
        else:
            where = {"$or": [{"tags": {"$contains": t}} for t in tags]}

    chunks = store.query(text=query, n_results=limit, where=where)
    return [
        {
            "title": c.metadata["title"],
            "text": c.text,
            "tags": c.metadata["tags"],
            "heading_path": c.metadata["heading_path"],
            "note_pk": c.metadata["note_pk"],
            "chunk_index": c.metadata["chunk_index"],
            "modified_at": c.metadata["modified_at"],
        }
        for c in chunks
    ]


@server.tool()
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
def list_tags() -> list[dict]:
    """List all Bear note tags with note counts.

    Use this to discover what topics and categories exist in the notes
    before drilling down with search_notes or list_notes.
    """
    reader = _get_reader()
    tags = reader.list_tags()
    return [{"tag": name, "count": count} for name, count in tags]


@server.tool()
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


def main():
    server.run(transport="stdio")
```

- [ ] **Step 2: Verify the module imports cleanly**

Run: `cd /Users/adamboulware/Docker/bear-app-rag && uv run python -c "from bear_rag.mcp_server import server; print(f'Server name: {server.name}')"`
Expected: `Server name: bear-notes`

- [ ] **Step 3: Commit**

```bash
git add bear_rag/mcp_server.py
git commit -m "feat: add MCP server with 5 tools for Bear notes"
```

---

### Task 8: MCP server tests

**Files:**
- Create: `tests/test_mcp_server.py`

- [ ] **Step 1: Write tests for MCP tool handlers**

Create `tests/test_mcp_server.py`:

```python
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
```

- [ ] **Step 2: Run tests**

Run: `cd /Users/adamboulware/Docker/bear-app-rag && uv run pytest tests/test_mcp_server.py -v`
Expected: All tests PASS

Note: The `sync_notes` test uses the test Bear DB and ephemeral ChromaDB from conftest fixtures. The sync will pick up the test notes and index them. The `bear_db` fixture is pulled in transitively via the `reader` fixture.

- [ ] **Step 3: Run full test suite**

Run: `cd /Users/adamboulware/Docker/bear-app-rag && uv run pytest -v`
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_mcp_server.py
git commit -m "test: add tests for MCP server tool handlers"
```

---

### Task 9: Configure Claude Code integration

**Files:**
- None (manual configuration steps)

This task is manual — it configures Claude Code settings on your machine. These are not committed to the repo.

- [ ] **Step 1: Add MCP server to Claude Code settings**

Add the bear-notes MCP server to your Claude Code settings. This can be done in `~/.claude/settings.json` (global) or the project-level `.claude/settings.json`:

```json
{
  "mcpServers": {
    "bear-notes": {
      "command": "uv",
      "args": ["run", "--directory", "/Users/adamboulware/Docker/bear-app-rag", "bear-rag-mcp"]
    }
  }
}
```

- [ ] **Step 2: Add pre-session sync hook**

Add to your Claude Code settings:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "command": "cd /Users/adamboulware/Docker/bear-app-rag && uv run bear-rag sync --quiet",
        "timeout": 30000
      }
    ]
  }
}
```

- [ ] **Step 3: Add CLAUDE.md hint**

Add to `~/.claude/CLAUDE.md`:

```
When I ask about my notes, Bear notes, or reference personal knowledge,
use the bear-notes MCP tools. Use multiple search strategies (tags,
semantic search, browsing) to be thorough.
```

- [ ] **Step 4: Verify MCP server starts**

Run: `cd /Users/adamboulware/Docker/bear-app-rag && echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}' | uv run bear-rag-mcp`

Expected: JSON response with server capabilities (the server will read from stdin and write a JSON-RPC response to stdout, then wait for more input — you can Ctrl+C after seeing the response).

- [ ] **Step 5: Verify in Claude Code**

Start a new Claude Code session and ask: "List my Bear note tags"

Expected: Claude Code uses the `list_tags` tool from the bear-notes MCP server and returns your actual tags.
