import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from bear_rag.models import BearNote

CORE_DATA_EPOCH = datetime(2001, 1, 1, tzinfo=UTC)


def _core_data_to_datetime(ts: float) -> datetime:
    """Convert a Core Data timestamp (seconds since 2001-01-01 UTC) to a datetime."""
    return datetime.fromtimestamp(CORE_DATA_EPOCH.timestamp() + ts, tz=UTC)


def _datetime_to_core_data(dt: datetime) -> float:
    """Convert a datetime to a Core Data timestamp (seconds since 2001-01-01 UTC)."""
    return (dt - CORE_DATA_EPOCH).total_seconds()


class BearReader:
    """Read notes from a Bear SQLite database."""

    def __init__(self, db_path: Path | None = None) -> None:
        if db_path is None:
            from bear_rag import config

            db_path = config.BEAR_DB_PATH
        db_path = Path(db_path)
        if not db_path.exists():
            raise FileNotFoundError(f"Bear database not found at {db_path}. Is Bear installed?")
        self._uri = f"file:{db_path}?mode=ro"

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._uri, uri=True)

    def _rows_to_notes(self, rows: list[tuple], cur: sqlite3.Cursor) -> list[BearNote]:
        pks = [row[0] for row in rows]
        tags_by_pk = self._fetch_tags_batch(cur, pks)
        notes = []
        for row in rows:
            pk, title, text, mod_ts, is_trashed, is_archived = row
            notes.append(
                BearNote(
                    pk=pk,
                    title=title or "",
                    text=text or "",
                    modified_at=_core_data_to_datetime(mod_ts),
                    tags=tags_by_pk.get(pk, []),
                    is_trashed=bool(is_trashed),
                    is_archived=bool(is_archived),
                )
            )
        return notes

    def read_notes(self, include_archived: bool = False) -> list[BearNote]:
        """Return all non-trashed notes, optionally including archived ones."""
        archive_filter = "" if include_archived else "AND n.ZARCHIVED = 0"
        query = f"""
            SELECT
                n.Z_PK, n.ZTITLE, n.ZTEXT,
                n.ZMODIFICATIONDATE, n.ZTRASHED, n.ZARCHIVED
            FROM ZSFNOTE n
            WHERE n.ZTRASHED = 0 {archive_filter}
            ORDER BY n.Z_PK
        """  # noqa: S608 — only literal clauses and "?" placeholders are interpolated
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(query)
            return self._rows_to_notes(cur.fetchall(), cur)

    def read_notes_modified_since(self, timestamp: float) -> list[BearNote]:
        """Return non-trashed notes modified after the given Core Data timestamp."""
        query = """
            SELECT
                n.Z_PK, n.ZTITLE, n.ZTEXT,
                n.ZMODIFICATIONDATE, n.ZTRASHED, n.ZARCHIVED
            FROM ZSFNOTE n
            WHERE n.ZTRASHED = 0 AND n.ZMODIFICATIONDATE > ?
            ORDER BY n.Z_PK
        """
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(query, (timestamp,))
            return self._rows_to_notes(cur.fetchall(), cur)

    def read_trashed_pks(self, since_timestamp: float = 0.0) -> list[int]:
        """Return primary keys of trashed notes modified after the given Core Data timestamp."""
        query = """
            SELECT Z_PK FROM ZSFNOTE
            WHERE ZTRASHED = 1 AND ZMODIFICATIONDATE > ?
            ORDER BY Z_PK
        """
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(query, (since_timestamp,))
            return [row[0] for row in cur.fetchall()]

    def read_active_pks(self) -> set[int]:
        """Return the PKs of all live (non-trashed, non-archived) notes.

        This is the authoritative "what should be in the index" set used by
        :func:`~bear_rag.sync.sync` for reconciliation (D18): any note present in
        the index but absent from this set — archived, trashed, or deleted
        outright — is stale and gets dropped. Deliberately independent of
        ``ZMODIFICATIONDATE`` so the fix holds whether or not archiving bumps
        that timestamp (a read-only probe of the real Bear DB was inconclusive;
        trashing, notably, does not bump it).
        """
        query = """
            SELECT Z_PK FROM ZSFNOTE
            WHERE ZTRASHED = 0 AND ZARCHIVED = 0
        """
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(query)
            return {row[0] for row in cur.fetchall()}

    def note_pks_for_tags(self, tags: list[str]) -> set[int]:
        """Return the PKs of non-trashed, non-archived notes carrying any of *tags*.

        Dedicated tag->pk resolver for the MCP search path (see
        ``mcp_server.search_notes``). Deliberately NOT ``list_notes``: this is
        multi-tag (OR semantics), uncapped (no ``LIMIT``), and returns bare pks
        rather than full ``BearNote`` objects. Like every sibling reader it
        excludes both trashed (``ZTRASHED = 0``) and archived (``ZARCHIVED = 0``,
        D14) notes, so tag filtering never resurfaces a note the rest of the
        surface hides. Matching is exact-segment on ``ZTITLE`` (consistent with
        ``list_notes``), so ``work`` never matches ``homework``.
        """
        if not tags:
            return set()
        placeholders = ",".join("?" for _ in tags)
        query = f"""
            SELECT DISTINCT n.Z_PK
            FROM ZSFNOTE n
            JOIN Z_5TAGS jt ON jt.Z_5NOTES = n.Z_PK
            JOIN ZSFNOTETAG t ON t.Z_PK = jt.Z_13TAGS
            WHERE n.ZTRASHED = 0 AND n.ZARCHIVED = 0 AND t.ZTITLE IN ({placeholders})
        """  # noqa: S608 — only literal clauses and "?" placeholders are interpolated
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(query, tags)
            return {row[0] for row in cur.fetchall()}

    def list_tags(self) -> list[tuple[str, int]]:
        """Return (tag_name, note_count) tuples sorted by count descending.

        Counts only live notes: both trashed and archived notes are excluded so
        this browse surface mirrors Bear's own UI (D17), consistent with the
        search and ``list_notes`` paths.
        """
        query = """
            SELECT t.ZTITLE, COUNT(*) as cnt
            FROM ZSFNOTETAG t
            JOIN Z_5TAGS jt ON jt.Z_13TAGS = t.Z_PK
            JOIN ZSFNOTE n ON n.Z_PK = jt.Z_5NOTES
            WHERE n.ZTRASHED = 0 AND n.ZARCHIVED = 0
            GROUP BY t.ZTITLE
            ORDER BY cnt DESC
        """
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(query)
            return [(row[0], row[1]) for row in cur.fetchall()]

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

    def list_notes(
        self,
        tag: str | None = None,
        modified_since: str | None = None,
        modified_before: str | None = None,
        title_contains: str | None = None,
        limit: int = 50,
    ) -> list[BearNote]:
        """Return live notes matching the given filters, ordered by modified date descending.

        Excludes both trashed and archived notes so this browse surface mirrors
        Bear's own UI (D17). Use :meth:`read_note_by_title` for the deliberate
        direct fetch that can still surface an archived note.
        """
        conditions = ["n.ZTRASHED = 0", "n.ZARCHIVED = 0"]
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
            dt = datetime.fromisoformat(modified_since)
            dt = dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)
            conditions.append("n.ZMODIFICATIONDATE > ?")
            params.append(_datetime_to_core_data(dt))

        if modified_before is not None:
            dt = datetime.fromisoformat(modified_before)
            dt = dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)
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
        """  # noqa: S608 — only literal clauses and "?" placeholders are interpolated
        params.append(limit)

        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(query, params)
            return self._rows_to_notes(cur.fetchall(), cur)

    @staticmethod
    def _fetch_tags_batch(cur: sqlite3.Cursor, pks: list[int]) -> dict[int, list[str]]:
        """Fetch tag names for multiple note PKs in a single query.

        Splits *pks* into chunks to stay under SQLite's host-parameter
        limit (commonly 999).
        """
        if not pks:
            return {}
        tags_by_pk: dict[int, list[str]] = {}
        chunk_size = 900  # well under SQLite's default 999 variable limit
        for start in range(0, len(pks), chunk_size):
            chunk = pks[start : start + chunk_size]
            placeholders = ",".join("?" for _ in chunk)
            cur.execute(
                f"""
                SELECT jt.Z_5NOTES, t.ZTITLE
                FROM ZSFNOTETAG t
                JOIN Z_5TAGS jt ON jt.Z_13TAGS = t.Z_PK
                WHERE jt.Z_5NOTES IN ({placeholders})
                ORDER BY jt.Z_5NOTES, t.ZTITLE
                """,  # noqa: S608 — placeholders only; values are bound
                chunk,
            )
            for note_pk, tag_title in cur.fetchall():
                tags_by_pk.setdefault(note_pk, []).append(tag_title)
        return tags_by_pk
