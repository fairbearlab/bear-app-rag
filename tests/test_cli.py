"""Tests for bear_rag.cli — command-line interface."""

from unittest.mock import MagicMock, patch

from bear_rag.cli import main


# ---------------------------------------------------------------------------
# index command
# ---------------------------------------------------------------------------

@patch("bear_rag.cli.BearReader")
@patch("bear_rag.cli.NoteStore")
@patch("bear_rag.cli.full_index")
def test_index_calls_full_index(mock_full_index, mock_store_cls, mock_reader_cls, monkeypatch):
    """bear-rag index should call full_index once."""
    monkeypatch.setattr("sys.argv", ["bear-rag", "index"])
    mock_full_index.return_value = MagicMock(notes_updated=5, notes_deleted=0, chunks_added=20)

    main()

    mock_full_index.assert_called_once()


# ---------------------------------------------------------------------------
# sync command
# ---------------------------------------------------------------------------

@patch("bear_rag.cli.BearReader")
@patch("bear_rag.cli.NoteStore")
@patch("bear_rag.cli.sync")
def test_sync_calls_sync(mock_sync, mock_store_cls, mock_reader_cls, monkeypatch):
    """bear-rag sync should call sync once."""
    monkeypatch.setattr("sys.argv", ["bear-rag", "sync"])
    mock_sync.return_value = MagicMock(notes_updated=2, notes_deleted=1, chunks_added=10)

    main()

    mock_sync.assert_called_once()


@patch("bear_rag.cli.BearReader")
@patch("bear_rag.cli.NoteStore")
@patch("bear_rag.cli.sync")
def test_sync_dry_run_passes_flag(mock_sync, mock_store_cls, mock_reader_cls, monkeypatch):
    """bear-rag sync --dry-run should pass dry_run=True to sync."""
    monkeypatch.setattr("sys.argv", ["bear-rag", "sync", "--dry-run"])
    mock_sync.return_value = MagicMock(notes_updated=2, notes_deleted=1, chunks_added=10)

    main()

    call_kwargs = mock_sync.call_args.kwargs
    assert call_kwargs.get("dry_run") is True


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


# ---------------------------------------------------------------------------
# status command
# ---------------------------------------------------------------------------

@patch("bear_rag.cli.BearReader")
@patch("bear_rag.cli.NoteStore")
def test_status_prints_info(mock_store_cls, mock_reader_cls, monkeypatch, capsys):
    """bear-rag status should print the chunk count from store.get_stats()."""
    monkeypatch.setattr("sys.argv", ["bear-rag", "status"])

    mock_store = MagicMock()
    mock_store.get_stats.return_value = {"count": 42, "note_count": 7}
    mock_store_cls.return_value = mock_store

    main()

    captured = capsys.readouterr()
    assert "42" in captured.out
