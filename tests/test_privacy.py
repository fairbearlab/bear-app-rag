"""Privacy guardrail: the index/search path must never touch the network.

ADR-0002 promises that indexing, embedding, and search run entirely on-device.
This module *enforces* that promise rather than just asserting it in prose: it
blocks all outbound network sockets and verifies that ``NoteStore`` construction,
``upsert_chunks``, ``query``, and ``sync`` all still succeed.

The single documented network call on this path is the one-time ONNX embedding
model download from ``chroma-onnx-models.s3.amazonaws.com``. It is pre-warmed
(with the network available) by the module-scoped ``_warm_model_cache`` fixture
*before* sockets are blocked, so the guarded assertions exercise a cache hit, not
a cold download.

The generator / ``bear-rag ask`` path is deliberately NOT covered here: it
legitimately POSTs retrieved chunk text to the Anthropic API. This test asserts
the embedding/retrieval boundary, not "no network, ever".
"""

from __future__ import annotations

import socket
from pathlib import Path

import pytest
from pytest_socket import SocketBlockedError, disable_socket, enable_socket

from bear_rag.bear_reader import BearReader
from bear_rag.models import Chunk, ChunkMetadata
from bear_rag.store import NoteStore
from bear_rag.sync import full_index


def _sample_chunks() -> list[Chunk]:
    """A single hand-built chunk, so upsert/query don't depend on the chunker."""
    metadata: ChunkMetadata = {
        "note_pk": 1,
        "title": "Offline Note",
        "tags": ",privacy,",
        "chunk_index": 0,
        "heading_path": "",
        "modified_at": "2024-06-01T12:00:00+00:00",
        "source": "test",
    }
    return [
        Chunk(
            id="1_0",
            text="Local-first embeddings keep personal notes on the device.",
            metadata=metadata,
        )
    ]


@pytest.fixture(scope="module")
def _warm_model_cache(tmp_path_factory) -> None:
    """Download and cache the ONNX embedding model while the network is up.

    Runs once per module, before any socket is blocked. The model is fetched
    from chroma-onnx-models.s3.amazonaws.com on first use; touching the full
    embedding path here guarantees the guarded tests below hit a warm cache.
    """
    warm_dir: Path = tmp_path_factory.mktemp("warm")
    try:
        store = NoteStore(persist_dir=warm_dir / "chroma")
        store.upsert_chunks(_sample_chunks())
        store.query("warmup")
    except Exception as exc:
        # A cold model cache with no network can't be warmed. The offline
        # assertions below would then fail for the wrong reason, so degrade the
        # whole module to a skip instead of erroring. In CI (network available)
        # the model downloads here and the guarantee is enforced as intended.
        pytest.skip(f"ONNX embedding model unavailable (offline + cold cache?): {exc}")


@pytest.fixture
def no_network(_warm_model_cache: None):
    """Block all outbound network sockets for the duration of a test.

    Unix domain sockets are intentionally left available: the guarantee under
    test is about network egress (notes leaving the machine), not local IPC.
    Depending on ``_warm_model_cache`` guarantees the model is cached before the
    block is installed.
    """
    disable_socket(allow_unix_socket=True)
    try:
        yield
    finally:
        enable_socket()


def test_network_is_actually_blocked(no_network) -> None:
    """Negative control: opening an INET socket must raise while guarded.

    Without this, a guard that silently failed to install would let every
    assertion below pass vacuously.
    """
    with pytest.raises(SocketBlockedError):
        socket.socket(socket.AF_INET, socket.SOCK_STREAM)


def test_notestore_construction_is_offline(no_network, tmp_path: Path) -> None:
    """Constructing a NoteStore (which loads the ONNX model) makes no network call."""
    store = NoteStore(persist_dir=tmp_path / "chroma")
    assert store.get_stats()["count"] == 0


def test_upsert_and_query_are_offline(no_network, tmp_path: Path) -> None:
    """The embed-on-write and embed-on-read paths run entirely on-device."""
    store = NoteStore(persist_dir=tmp_path / "chroma")
    store.upsert_chunks(_sample_chunks())

    results = store.query("notes that stay on the device", n_results=3)

    assert len(results) == 1
    assert results[0].metadata["title"] == "Offline Note"


def test_sync_is_offline(no_network, tmp_path: Path, bear_db: Path) -> None:
    """A full index from a Bear database touches only local SQLite + ONNX."""
    store = NoteStore(persist_dir=tmp_path / "chroma")
    reader = BearReader(db_path=bear_db)

    result = full_index(store=store, reader=reader, state_path=tmp_path / "state.json")

    assert result.notes_updated >= 1
    assert store.get_stats()["count"] >= 1
