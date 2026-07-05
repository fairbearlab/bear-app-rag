"""Unit tests for the shared `get_status` helper (CLI + MCP `status`).

Focus: reading the sync-state JSON file must *fail open* — a missing,
unreadable, or malformed state file yields ``last_sync=None`` rather than
crashing the CLI or surfacing an "Internal error" through the MCP server.
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from bear_rag import config
from bear_rag.status import get_status


@pytest.fixture
def store() -> MagicMock:
    s = MagicMock()
    s.get_stats.return_value = {"count": 42, "note_count": 7}
    return s


@pytest.fixture
def state_path(tmp_path: Path, monkeypatch) -> Path:
    path = tmp_path / "last_sync.json"
    monkeypatch.setattr(config, "SYNC_STATE_PATH", path)
    return path


def test_reads_synced_at_from_valid_state(store, state_path: Path) -> None:
    state_path.write_text('{"synced_at": "2026-07-05T12:00:00+00:00"}')
    result = get_status(store)
    assert result == {
        "index_count": 42,
        "note_count": 7,
        "last_sync": "2026-07-05T12:00:00+00:00",
    }


def test_missing_state_file_yields_none(store, state_path: Path) -> None:
    assert not state_path.exists()
    assert get_status(store)["last_sync"] is None


def test_malformed_json_fails_open(store, state_path: Path) -> None:
    state_path.write_text("{not valid json")
    assert get_status(store)["last_sync"] is None


def test_non_dict_json_fails_open(store, state_path: Path) -> None:
    """Valid JSON that isn't an object (e.g. a bare list) must not crash."""
    state_path.write_text("[1, 2, 3]")
    assert get_status(store)["last_sync"] is None


def test_missing_synced_at_key_yields_none(store, state_path: Path) -> None:
    state_path.write_text('{"timestamp": 123.0}')
    assert get_status(store)["last_sync"] is None
