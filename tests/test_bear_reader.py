from datetime import datetime, timezone
from pathlib import Path

import pytest

from bear_rag.bear_reader import BearReader


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
        cutoff = datetime(2024, 6, 10, 0, 0, 0, tzinfo=timezone.utc).timestamp()
        notes = reader.read_notes_modified_since(cutoff)
        pks = [n.pk for n in notes]
        assert pks == [2], f"Expected only pk=2 (recent note), got {pks}"

    def test_excludes_trashed_notes(self, bear_db: Path) -> None:
        reader = BearReader(bear_db)
        # Very old cutoff — would include everything if not filtered
        cutoff = datetime(2000, 1, 1, tzinfo=timezone.utc).timestamp()
        notes = reader.read_notes_modified_since(cutoff)
        pks = [n.pk for n in notes]
        assert 3 not in pks, "Trashed note should be excluded from modified_since"

    def test_returns_empty_when_nothing_new(self, bear_db: Path) -> None:
        reader = BearReader(bear_db)
        # Future cutoff — nothing should match
        cutoff = datetime(2030, 1, 1, tzinfo=timezone.utc).timestamp()
        notes = reader.read_notes_modified_since(cutoff)
        assert notes == []


class TestBearReaderTrashedPks:
    def test_returns_trashed_pks(self, bear_db: Path) -> None:
        reader = BearReader(bear_db)
        pks = reader.read_trashed_pks()
        assert pks == [3]

    def test_returns_list_of_ints(self, bear_db: Path) -> None:
        reader = BearReader(bear_db)
        pks = reader.read_trashed_pks()
        for pk in pks:
            assert isinstance(pk, int), f"Expected int pk, got {type(pk)}"


class TestBearReaderDbNotFound:
    def test_raises_file_not_found(self, tmp_path: Path) -> None:
        missing = tmp_path / "nonexistent.sqlite"
        with pytest.raises(FileNotFoundError) as exc_info:
            BearReader(missing)
        assert str(missing) in str(exc_info.value), (
            "FileNotFoundError message should include the missing path"
        )
