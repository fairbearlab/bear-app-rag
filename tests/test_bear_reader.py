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


class TestBearReaderDbNotFound:
    def test_raises_file_not_found(self, tmp_path: Path) -> None:
        missing = tmp_path / "nonexistent.sqlite"
        with pytest.raises(FileNotFoundError) as exc_info:
            BearReader(missing)
        assert str(missing) in str(exc_info.value), (
            "FileNotFoundError message should include the missing path"
        )
