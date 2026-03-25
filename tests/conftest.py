import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest


CORE_DATA_EPOCH = datetime(2001, 1, 1, tzinfo=timezone.utc)


def datetime_to_core_data(dt: datetime) -> float:
    """Convert a datetime to a Core Data timestamp (seconds since 2001-01-01 UTC)."""
    return (dt - CORE_DATA_EPOCH).total_seconds()


@pytest.fixture
def bear_db(tmp_path: Path) -> Path:
    """Build a minimal Bear-schema SQLite database for testing."""
    db_path = tmp_path / "database.sqlite"
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()

    # Create main notes table
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

    # Create tag table
    cur.execute("""
        CREATE TABLE ZSFNOTETAG (
            Z_PK INTEGER PRIMARY KEY,
            ZTITLE TEXT
        )
    """)

    # Create join table
    cur.execute("""
        CREATE TABLE Z_5TAGS (
            Z_5NOTES INTEGER,
            Z_13TAGS INTEGER
        )
    """)

    # Insert tags
    cur.executemany(
        "INSERT INTO ZSFNOTETAG (Z_PK, ZTITLE) VALUES (?, ?)",
        [
            (1, "work"),
            (2, "personal"),
            (3, "recent"),
        ],
    )

    # Timestamps
    now = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    older = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    recent = datetime(2024, 6, 15, 8, 0, 0, tzinfo=timezone.utc)

    notes = [
        # (Z_PK, ZTITLE, ZTEXT, ZMODIFICATIONDATE, ZTRASHED, ZARCHIVED)
        (1, "Normal Note", "This is a normal note.", datetime_to_core_data(now), 0, 0),
        (2, "Recent Note", "Recently modified note.", datetime_to_core_data(recent), 0, 0),
        (3, "Trashed Note", "This note is trashed.", datetime_to_core_data(older), 1, 0),
        (4, "Archived Note", "This note is archived.", datetime_to_core_data(older), 0, 1),
        (5, "No Tags Note", "This note has no tags.", datetime_to_core_data(older), 0, 0),
    ]
    cur.executemany(
        "INSERT INTO ZSFNOTE (Z_PK, ZTITLE, ZTEXT, ZMODIFICATIONDATE, ZTRASHED, ZARCHIVED) VALUES (?, ?, ?, ?, ?, ?)",
        notes,
    )

    # Join table entries: note 1 has tags work+personal, note 2 has tag recent
    cur.executemany(
        "INSERT INTO Z_5TAGS (Z_5NOTES, Z_13TAGS) VALUES (?, ?)",
        [
            (1, 1),  # Normal Note -> work
            (1, 2),  # Normal Note -> personal
            (2, 3),  # Recent Note -> recent
            (3, 1),  # Trashed Note -> work
            (4, 2),  # Archived Note -> personal
        ],
    )

    conn.commit()
    conn.close()
    return db_path
