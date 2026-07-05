import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from bear_rag.bear_reader import BearReader
from tests.conftest import datetime_to_core_data


class TestBearReaderReadNotes:
    def test_excludes_trashed_notes_by_default(self, bear_db: Path) -> None:
        reader = BearReader(bear_db)
        notes = reader.read_notes()
        pks = [n.pk for n in notes]
        assert 3 not in pks, "Trashed note should be excluded"

    def test_excludes_archived_notes_by_default(self, bear_db: Path) -> None:
        reader = BearReader(bear_db)
        notes = reader.read_notes()
        pks = [n.pk for n in notes]
        assert 4 not in pks, "Archived note should be excluded by default"

    def test_include_archived_returns_archived_notes(self, bear_db: Path) -> None:
        reader = BearReader(bear_db)
        notes = reader.read_notes(include_archived=True)
        pks = [n.pk for n in notes]
        assert 4 in pks, "Archived note should appear when include_archived=True"
        assert 3 not in pks, "Trashed note should still be excluded"

    def test_tags_populated(self, bear_db: Path) -> None:
        reader = BearReader(bear_db)
        notes = reader.read_notes()
        normal_note = next(n for n in notes if n.pk == 1)
        assert sorted(normal_note.tags) == ["personal", "work"]

    def test_single_tag(self, bear_db: Path) -> None:
        reader = BearReader(bear_db)
        notes = reader.read_notes()
        recent_note = next(n for n in notes if n.pk == 2)
        assert recent_note.tags == ["recent"]

    def test_empty_tags_list(self, bear_db: Path) -> None:
        reader = BearReader(bear_db)
        notes = reader.read_notes()
        no_tags_note = next(n for n in notes if n.pk == 5)
        assert no_tags_note.tags == []

    def test_modified_at_is_datetime(self, bear_db: Path) -> None:
        reader = BearReader(bear_db)
        notes = reader.read_notes()
        for note in notes:
            assert isinstance(note.modified_at, datetime), (
                f"note.modified_at should be datetime, got {type(note.modified_at)}"
            )

    def test_modified_at_is_timezone_aware(self, bear_db: Path) -> None:
        reader = BearReader(bear_db)
        notes = reader.read_notes()
        for note in notes:
            assert note.modified_at.tzinfo is not None, (
                "note.modified_at should be timezone-aware"
            )


class TestBearReaderModifiedSince:
    def test_returns_only_recently_modified(self, bear_db: Path) -> None:
        reader = BearReader(bear_db)
        # Cutoff: June 10, 2024 — only the "recent" note (June 15) qualifies
        cutoff = datetime_to_core_data(datetime(2024, 6, 10, tzinfo=timezone.utc))
        notes = reader.read_notes_modified_since(cutoff)
        pks = [n.pk for n in notes]
        assert pks == [2], f"Expected only pk=2 (recent note), got {pks}"

    def test_excludes_trashed_notes(self, bear_db: Path) -> None:
        reader = BearReader(bear_db)
        # Very old cutoff — would include everything if not filtered
        cutoff = datetime_to_core_data(datetime(2000, 1, 1, tzinfo=timezone.utc))
        notes = reader.read_notes_modified_since(cutoff)
        pks = [n.pk for n in notes]
        assert 3 not in pks, "Trashed note should be excluded from modified_since"

    def test_returns_empty_when_nothing_new(self, bear_db: Path) -> None:
        reader = BearReader(bear_db)
        # Future cutoff — nothing should match
        cutoff = datetime_to_core_data(datetime(2030, 1, 1, tzinfo=timezone.utc))
        notes = reader.read_notes_modified_since(cutoff)
        assert notes == []


class TestBearReaderTrashedPks:
    def test_returns_trashed_pks_default(self, bear_db: Path) -> None:
        reader = BearReader(bear_db)
        pks = reader.read_trashed_pks()
        assert pks == [3]

    def test_returns_list_of_ints(self, bear_db: Path) -> None:
        reader = BearReader(bear_db)
        pks = reader.read_trashed_pks()
        for pk in pks:
            assert isinstance(pk, int), f"Expected int pk, got {type(pk)}"

    def test_timestamp_filter_returns_recently_trashed(self, bear_db: Path) -> None:
        """With a very old timestamp, returns all trashed notes."""
        reader = BearReader(bear_db)
        pks = reader.read_trashed_pks(since_timestamp=0.0)
        assert pks == [3]

    def test_timestamp_filter_excludes_old_trash(self, bear_db: Path) -> None:
        """With a future timestamp, returns no trashed notes."""
        reader = BearReader(bear_db)
        future = datetime_to_core_data(datetime(2030, 1, 1, tzinfo=timezone.utc))
        pks = reader.read_trashed_pks(since_timestamp=future)
        assert pks == []


class TestBearReaderReadActivePks:
    """Unit tests for the reconciliation source-of-truth set (D18).

    conftest ``bear_db`` fixture recap:
      note 1 (kept), note 2 (kept), note 3 (trashed),
      note 4 (archived), note 5 (kept).
    """

    def test_returns_only_live_notes(self, bear_db: Path) -> None:
        reader = BearReader(bear_db)
        assert reader.read_active_pks() == {1, 2, 5}

    def test_excludes_archived(self, bear_db: Path) -> None:
        reader = BearReader(bear_db)
        assert 4 not in reader.read_active_pks()

    def test_excludes_trashed(self, bear_db: Path) -> None:
        reader = BearReader(bear_db)
        assert 3 not in reader.read_active_pks()

    def test_returns_set(self, bear_db: Path) -> None:
        reader = BearReader(bear_db)
        assert isinstance(reader.read_active_pks(), set)


class TestBearReaderListTags:
    def test_returns_tags_with_counts(self, bear_db: Path) -> None:
        reader = BearReader(bear_db)
        tags = reader.list_tags()
        tag_dict = dict(tags)
        # From conftest: "work" on notes 1,3 but note 3 is trashed -> count 1
        # "personal" on notes 1,4 but note 4 is archived -> excluded (D17) -> count 1
        # "recent" on note 2 -> count 1
        assert tag_dict["personal"] == 1
        assert tag_dict["work"] == 1
        assert tag_dict["recent"] == 1

    def test_excludes_archived_notes(self, bear_db: Path) -> None:
        """Archived notes must not contribute to tag counts (D17)."""
        reader = BearReader(bear_db)
        tag_dict = dict(reader.list_tags())
        # "personal" is on note 1 (kept) and note 4 (archived) -> only note 1
        assert tag_dict["personal"] == 1

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


class TestBearReaderListNotes:
    def test_no_filters_returns_non_trashed(self, bear_db: Path) -> None:
        reader = BearReader(bear_db)
        notes = reader.list_notes()
        pks = [n.pk for n in notes]
        assert 3 not in pks, "Trashed note should be excluded"
        assert 4 not in pks, "Archived note should be excluded (D17)"
        assert len(notes) == 3  # notes 1, 2, 5

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

    def test_modified_since_respects_timezone_offset(self, bear_db: Path) -> None:
        """A timestamp with an offset should be converted to UTC, not stamped as UTC."""
        reader = BearReader(bear_db)
        # Note 2 is modified at 2024-06-15T08:00:00Z.
        # 2024-06-15T04:00:00-05:00 == 2024-06-15T09:00:00Z, which is AFTER note 2.
        notes = reader.list_notes(modified_since="2024-06-15T04:00:00-05:00")
        pks = [n.pk for n in notes]
        assert 2 not in pks, "Offset should convert to 09:00 UTC, excluding note modified at 08:00 UTC"

    def test_modified_before_respects_timezone_offset(self, bear_db: Path) -> None:
        reader = BearReader(bear_db)
        # 2024-06-15T04:00:00-05:00 == 2024-06-15T09:00:00Z, which is AFTER note 2.
        notes = reader.list_notes(modified_before="2024-06-15T04:00:00-05:00")
        pks = [n.pk for n in notes]
        assert 2 in pks, "Offset should convert to 09:00 UTC, including note modified at 08:00 UTC"

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


class TestBearReaderNotePksForTags:
    """Unit tests for the tag->pk resolver used by mcp_server.search_notes (D15).

    conftest ``bear_db`` fixture recap:
      note 1 -> work, personal   (kept)
      note 2 -> recent           (kept)
      note 3 -> work             (trashed)
      note 4 -> personal         (archived)
      note 5 -> (no tags)        (kept)
    """

    def test_single_tag(self, bear_db: Path) -> None:
        reader = BearReader(bear_db)
        assert reader.note_pks_for_tags(["recent"]) == {2}

    def test_multi_tag_or_dedup(self, bear_db: Path) -> None:
        """OR union across tags; a note carrying two of the tags appears once."""
        reader = BearReader(bear_db)
        # note 1 has both work AND personal -> must dedup to a single pk;
        # note 2 has recent. note 3 (work) is trashed, note 4 (personal) archived.
        assert reader.note_pks_for_tags(["work", "personal", "recent"]) == {1, 2}

    def test_no_match_returns_empty_set(self, bear_db: Path) -> None:
        reader = BearReader(bear_db)
        assert reader.note_pks_for_tags(["nonexistent-tag-xyz"]) == set()

    def test_empty_tag_list_returns_empty_set(self, bear_db: Path) -> None:
        reader = BearReader(bear_db)
        assert reader.note_pks_for_tags([]) == set()

    def test_archived_excluded(self, bear_db: Path) -> None:
        """'personal' is on note 1 (kept) and note 4 (archived); only note 1."""
        reader = BearReader(bear_db)
        assert reader.note_pks_for_tags(["personal"]) == {1}

    def test_trashed_excluded(self, bear_db: Path) -> None:
        """'work' is on note 1 (kept) and note 3 (trashed); only note 1."""
        reader = BearReader(bear_db)
        assert reader.note_pks_for_tags(["work"]) == {1}

    def test_uncapped_over_50_notes(self, tmp_path: Path) -> None:
        """The resolver has no LIMIT, unlike list_notes (limit=50)."""
        db_path = tmp_path / "bulk.sqlite"
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        cur.execute(
            "CREATE TABLE ZSFNOTE (Z_PK INTEGER PRIMARY KEY, ZTITLE TEXT, ZTEXT TEXT, "
            "ZMODIFICATIONDATE REAL, ZTRASHED INTEGER DEFAULT 0, ZARCHIVED INTEGER DEFAULT 0)"
        )
        cur.execute("CREATE TABLE ZSFNOTETAG (Z_PK INTEGER PRIMARY KEY, ZTITLE TEXT)")
        cur.execute("CREATE TABLE Z_5TAGS (Z_5NOTES INTEGER, Z_13TAGS INTEGER)")
        cur.execute("INSERT INTO ZSFNOTETAG (Z_PK, ZTITLE) VALUES (1, 'bulk')")
        n = 120
        cur.executemany(
            "INSERT INTO ZSFNOTE (Z_PK, ZTITLE, ZTEXT, ZMODIFICATIONDATE, ZTRASHED, ZARCHIVED) "
            "VALUES (?, ?, ?, 0.0, 0, 0)",
            [(pk, f"Note {pk}", "body") for pk in range(1, n + 1)],
        )
        cur.executemany(
            "INSERT INTO Z_5TAGS (Z_5NOTES, Z_13TAGS) VALUES (?, 1)",
            [(pk,) for pk in range(1, n + 1)],
        )
        conn.commit()
        conn.close()

        reader = BearReader(db_path)
        pks = reader.note_pks_for_tags(["bulk"])
        assert len(pks) == n
        assert pks == set(range(1, n + 1))


class TestBearReaderDbNotFound:
    def test_raises_file_not_found(self, tmp_path: Path) -> None:
        missing = tmp_path / "nonexistent.sqlite"
        with pytest.raises(FileNotFoundError) as exc_info:
            BearReader(missing)
        assert str(missing) in str(exc_info.value), (
            "FileNotFoundError message should include the missing path"
        )
