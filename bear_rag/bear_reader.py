import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from bear_rag.models import BearNote


CORE_DATA_EPOCH = datetime(2001, 1, 1, tzinfo=timezone.utc)


def _core_data_to_datetime(ts: float) -> datetime:
    """Convert a Core Data timestamp (seconds since 2001-01-01 UTC) to a datetime."""
    return datetime.fromtimestamp(CORE_DATA_EPOCH.timestamp() + ts, tz=timezone.utc)


def _datetime_to_core_data(dt: datetime) -> float:
    """Convert a datetime to a Core Data timestamp (seconds since 2001-01-01 UTC)."""
    return (dt - CORE_DATA_EPOCH).total_seconds()


class BearReader:
    """Read notes from a Bear SQLite database."""

    def __init__(self, db_path: Path) -> None:
        db_path = Path(db_path)
        if not db_path.exists():
            raise FileNotFoundError(f"Bear database not found: {db_path}")
        # Read-only URI connection
        self._uri = f"file:{db_path}?mode=ro"

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._uri, uri=True)

    def read_notes(self, include_archived: bool = False) -> list[BearNote]:
        """Return all non-trashed notes, optionally including archived ones."""
        archive_filter = "" if include_archived else "AND n.ZARCHIVED = 0"
        query = f"""
            SELECT
                n.Z_PK,
                n.ZTITLE,
                n.ZTEXT,
                n.ZMODIFICATIONDATE,
                n.ZTRASHED,
                n.ZARCHIVED
            FROM ZSFNOTE n
            WHERE n.ZTRASHED = 0
              {archive_filter}
            ORDER BY n.Z_PK
        """
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(query)
            rows = cur.fetchall()

            notes = []
            for row in rows:
                pk, title, text, mod_ts, is_trashed, is_archived = row
                tags = self._fetch_tags(cur, pk)
                notes.append(
                    BearNote(
                        pk=pk,
                        title=title or "",
                        text=text or "",
                        modified_at=_core_data_to_datetime(mod_ts),
                        tags=tags,
                        is_trashed=bool(is_trashed),
                        is_archived=bool(is_archived),
                    )
                )
        return notes

    def read_notes_modified_since(self, timestamp: float) -> list[BearNote]:
        """Return non-trashed notes modified after the given Unix timestamp."""
        # Convert Unix timestamp to Core Data timestamp
        core_data_cutoff = timestamp - CORE_DATA_EPOCH.timestamp()
        query = """
            SELECT
                n.Z_PK,
                n.ZTITLE,
                n.ZTEXT,
                n.ZMODIFICATIONDATE,
                n.ZTRASHED,
                n.ZARCHIVED
            FROM ZSFNOTE n
            WHERE n.ZTRASHED = 0
              AND n.ZMODIFICATIONDATE > ?
            ORDER BY n.Z_PK
        """
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(query, (core_data_cutoff,))
            rows = cur.fetchall()

            notes = []
            for row in rows:
                pk, title, text, mod_ts, is_trashed, is_archived = row
                tags = self._fetch_tags(cur, pk)
                notes.append(
                    BearNote(
                        pk=pk,
                        title=title or "",
                        text=text or "",
                        modified_at=_core_data_to_datetime(mod_ts),
                        tags=tags,
                        is_trashed=bool(is_trashed),
                        is_archived=bool(is_archived),
                    )
                )
        return notes

    def read_trashed_pks(self) -> list[int]:
        """Return primary keys of all trashed notes."""
        query = "SELECT Z_PK FROM ZSFNOTE WHERE ZTRASHED = 1 ORDER BY Z_PK"
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(query)
            return [row[0] for row in cur.fetchall()]

    def _fetch_tags(self, cur: sqlite3.Cursor, note_pk: int) -> list[str]:
        """Fetch tag names for a given note PK."""
        cur.execute(
            """
            SELECT t.ZTITLE
            FROM ZSFNOTETAG t
            JOIN Z_5TAGS jt ON jt.Z_13TAGS = t.Z_PK
            WHERE jt.Z_5NOTES = ?
            ORDER BY t.ZTITLE
            """,
            (note_pk,),
        )
        return [row[0] for row in cur.fetchall()]
