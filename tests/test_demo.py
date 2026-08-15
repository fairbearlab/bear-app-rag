"""Tests for bear_rag.demo — self-contained RAG vs keyword demo."""

import os
import tempfile
from unittest.mock import patch

import pytest

from bear_rag.demo import DEMO_CORPUS, run_demo

# ---------------------------------------------------------------------------
# 1. Happy path — run_demo completes without error
# ---------------------------------------------------------------------------


@pytest.mark.eval
def test_run_demo_happy_path(capsys):
    """run_demo() should complete and print the summary line.

    Marked ``eval`` because it runs the real embedding path, which downloads
    the ~90MB ONNX model on a cold cache. Deselected from default CI via the
    ``-m 'not eval'`` addopts; run explicitly with ``pytest -m eval``.
    """
    run_demo()

    captured = capsys.readouterr()
    assert "bear-rag demo" in captured.out
    assert "Summary:" in captured.out


# ---------------------------------------------------------------------------
# 2. CLI routing — main() with ["demo"] dispatches correctly
# ---------------------------------------------------------------------------


def test_cli_routes_demo_command(monkeypatch):
    """bear-rag demo should dispatch to run_demo()."""
    monkeypatch.setattr("sys.argv", ["bear-rag", "demo"])

    from bear_rag.cli import main

    with patch("bear_rag.demo.run_demo") as mock_rd:
        main()

    mock_rd.assert_called_once()


# ---------------------------------------------------------------------------
# 3. Temp dir failure — mkdtemp raises OSError
# ---------------------------------------------------------------------------


def test_temp_dir_failure_prints_message(capsys):
    """When mkdtemp raises OSError, demo should print an error and return."""
    with patch("bear_rag.demo.tempfile.mkdtemp", side_effect=OSError("disk full")):
        run_demo()

    captured = capsys.readouterr()
    assert "Could not create temporary directory for demo" in captured.out


# ---------------------------------------------------------------------------
# 4. Model download failure — NoteStore init raises
# ---------------------------------------------------------------------------


def test_model_download_failure_prints_offline_message(capsys):
    """When NoteStore init fails (e.g. model download), demo prints offline message."""
    with patch(
        "bear_rag.demo.NoteStore",
        side_effect=RuntimeError("could not download model"),
    ):
        run_demo()

    captured = capsys.readouterr()
    assert "Embedding model not yet cached" in captured.out
    assert "~90MB download" in captured.out


# ---------------------------------------------------------------------------
# 5. Cleanup on success — temp dir removed after successful run
# ---------------------------------------------------------------------------


def test_cleanup_on_success():
    """Temp dir should not exist after a successful run_demo()."""
    created_dirs: list[str] = []
    original_mkdtemp = tempfile.mkdtemp

    def tracking_mkdtemp(**kwargs):
        d = original_mkdtemp(**kwargs)
        created_dirs.append(d)
        return d

    with patch("bear_rag.demo.tempfile.mkdtemp", side_effect=tracking_mkdtemp):
        run_demo()

    assert len(created_dirs) == 1
    assert not os.path.exists(created_dirs[0])


# ---------------------------------------------------------------------------
# 6. Cleanup on failure — temp dir removed even when error occurs
# ---------------------------------------------------------------------------


def test_cleanup_on_failure():
    """Temp dir should be cleaned up even when an error occurs mid-run."""
    created_dirs: list[str] = []
    original_mkdtemp = tempfile.mkdtemp

    def tracking_mkdtemp(**kwargs):
        d = original_mkdtemp(**kwargs)
        created_dirs.append(d)
        return d

    with patch("bear_rag.demo.tempfile.mkdtemp", side_effect=tracking_mkdtemp):
        # Force NoteStore to raise after tmp dir is created
        with patch(
            "bear_rag.demo.NoteStore",
            side_effect=RuntimeError("could not load model"),
        ):
            run_demo()

    assert len(created_dirs) == 1
    assert not os.path.exists(created_dirs[0])


# ---------------------------------------------------------------------------
# 7. Corpus validation — DEMO_CORPUS structure
# ---------------------------------------------------------------------------


def test_corpus_has_five_entries_with_required_keys():
    """DEMO_CORPUS should have 5 entries, each with required keys."""
    assert len(DEMO_CORPUS) == 5

    required_keys = {"pk", "title", "text", "tags", "modified_at"}
    for entry in DEMO_CORPUS:
        assert required_keys.issubset(entry.keys()), (
            f"Entry pk={entry.get('pk')} missing keys: {required_keys - entry.keys()}"
        )


# ---------------------------------------------------------------------------
# 8. Telemetry disabled — config sets ANONYMIZED_TELEMETRY
# ---------------------------------------------------------------------------


def test_telemetry_disabled(monkeypatch):
    """Importing bear_rag.config should set ANONYMIZED_TELEMETRY to 'False'.

    config.py uses ``os.environ.setdefault``, so the assertion is only
    meaningful when the var is unset and the module is freshly imported.
    Clear the var and reload to make this deterministic regardless of the
    ambient environment or prior imports in the session.
    """
    import importlib

    import bear_rag.config

    monkeypatch.delenv("ANONYMIZED_TELEMETRY", raising=False)
    importlib.reload(bear_rag.config)

    assert os.environ.get("ANONYMIZED_TELEMETRY") == "False"
