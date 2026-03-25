"""Tests for bear_rag.cli — command-line interface."""

from unittest.mock import MagicMock, patch

import pytest

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


# ---------------------------------------------------------------------------
# ask command — API key guard
# ---------------------------------------------------------------------------

@patch("bear_rag.cli.BearReader")
@patch("bear_rag.cli.NoteStore")
def test_ask_requires_api_key(mock_store_cls, mock_reader_cls, monkeypatch):
    """bear-rag ask without ANTHROPIC_API_KEY should exit with status 1."""
    monkeypatch.setattr("sys.argv", ["bear-rag", "ask", "What is Python?"])
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# ask command — one-shot mode
# ---------------------------------------------------------------------------

@patch("bear_rag.cli.BearReader")
@patch("bear_rag.cli.NoteStore")
@patch("bear_rag.cli.Retriever")
@patch("bear_rag.cli.generate_answer")
def test_ask_with_question(
    mock_generate, mock_retriever_cls, mock_store_cls, mock_reader_cls, monkeypatch, capsys
):
    """bear-rag ask 'question' should retrieve and generate once, printing the answer."""
    monkeypatch.setattr("sys.argv", ["bear-rag", "ask", "What is Python?"])
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    mock_retriever = MagicMock()
    mock_retriever.retrieve.return_value = [MagicMock()]
    mock_retriever_cls.return_value = mock_retriever
    mock_generate.return_value = "Python is a programming language."

    main()

    mock_retriever.retrieve.assert_called_once_with("What is Python?")
    mock_generate.assert_called_once()
    captured = capsys.readouterr()
    assert "Python is a programming language." in captured.out


# ---------------------------------------------------------------------------
# ask command — REPL mode
# ---------------------------------------------------------------------------

@patch("bear_rag.cli.BearReader")
@patch("bear_rag.cli.NoteStore")
@patch("bear_rag.cli.Retriever")
@patch("bear_rag.cli.generate_answer")
@patch("builtins.input", side_effect=["What is Python?", "What is Rust?", "quit"])
def test_ask_repl_mode(
    mock_input,
    mock_generate,
    mock_retriever_cls,
    mock_store_cls,
    mock_reader_cls,
    monkeypatch,
):
    """bear-rag ask (no question) should enter REPL, processing each line until quit."""
    monkeypatch.setattr("sys.argv", ["bear-rag", "ask"])
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    mock_retriever = MagicMock()
    mock_retriever.retrieve.return_value = [MagicMock()]
    mock_retriever_cls.return_value = mock_retriever
    mock_generate.return_value = "An answer."

    main()

    assert mock_retriever.retrieve.call_count == 2
    assert mock_generate.call_count == 2


@patch("bear_rag.cli.BearReader")
@patch("bear_rag.cli.NoteStore")
@patch("bear_rag.cli.Retriever")
@patch("bear_rag.cli.generate_answer")
@patch("builtins.input", side_effect=EOFError)
def test_ask_repl_exits_on_eof(
    mock_input,
    mock_generate,
    mock_retriever_cls,
    mock_store_cls,
    mock_reader_cls,
    monkeypatch,
):
    """bear-rag ask (no question) REPL should exit cleanly on EOFError (Ctrl+D)."""
    monkeypatch.setattr("sys.argv", ["bear-rag", "ask"])
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    mock_retriever = MagicMock()
    mock_retriever_cls.return_value = mock_retriever
    mock_generate.return_value = "An answer."

    # Should not raise
    main()

    mock_retriever.retrieve.assert_not_called()
    mock_generate.assert_not_called()


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
