from pathlib import Path
from typing import cast

import chromadb
from chromadb.api.types import Embeddable, EmbeddingFunction, Metadata
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

# Import config before chromadb so ANONYMIZED_TELEMETRY is set in the
# environment before chromadb reads it (e.g. when NoteStore is imported
# directly, without going through demo.py / cli.py first). See config.py.
from bear_rag import config
from bear_rag.models import Chunk, ChunkMetadata

_COLLECTION_NAME = "bear_notes"


def _metadata_int(value: object) -> int:
    """Narrow a ChromaDB metadata value to ``int``.

    Chroma types metadata values as a wide union (str | int | float | bool |
    list | SparseVector | None); the fields we read back were written as ints.
    """
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        raise TypeError(f"expected a numeric metadata value, got {value!r}")
    return int(value)


class NoteStore:
    def __init__(
        self,
        persist_dir: Path = config.CHROMA_DIR,
        embedding_function: EmbeddingFunction[Embeddable] | None = None,
    ) -> None:
        # Default to ChromaDB's local ONNX all-MiniLM-L6-v2 (see ADR-0002). The
        # injection point exists so the eval harness can benchmark alternate
        # local models (see tests/eval/embedding_sweep.py and ADR-0008); the
        # production path always uses the pinned default.
        # DefaultEmbeddingFunction is EmbeddingFunction[Documents]; the collection
        # API wants EmbeddingFunction[Embeddable]. Chroma's own API surface papers
        # over the same mismatch with `type: ignore`, so a cast here is honest.
        self._embedding_function: EmbeddingFunction[Embeddable] = embedding_function or cast(
            EmbeddingFunction[Embeddable], DefaultEmbeddingFunction()
        )
        persist_dir.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(
            path=str(persist_dir),
            settings=chromadb.config.Settings(anonymized_telemetry=False),
        )
        self._collection = self._client.get_or_create_collection(
            name=_COLLECTION_NAME,
            embedding_function=self._embedding_function,
        )

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def upsert_chunks(self, chunks: list[Chunk]) -> None:
        """Upsert a list of chunks into the collection, batched in groups of ~100."""
        if not chunks:
            return
        for i in range(0, len(chunks), 100):
            batch = chunks[i : i + 100]
            self._collection.upsert(
                ids=[c.id for c in batch],
                documents=[c.text for c in batch],
                # ChunkMetadata is a TypedDict of str/int values, which is a valid
                # chroma Metadata mapping; mypy cannot prove that through TypedDict.
                metadatas=[cast(Metadata, dict(c.metadata)) for c in batch],
            )

    def delete_note(self, note_pk: int) -> None:
        """Delete all chunks belonging to the given note_pk."""
        self._collection.delete(where={"note_pk": note_pk})

    def reset(self) -> None:
        """Delete and recreate the collection, clearing all data."""
        self._client.delete_collection(name=_COLLECTION_NAME)
        self._collection = self._client.create_collection(
            name=_COLLECTION_NAME,
            embedding_function=self._embedding_function,
        )

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def query(self, text: str, n_results: int = 5, where: dict | None = None) -> list[Chunk]:
        """Return up to n_results chunks most relevant to text, optionally filtered by *where*.

        *where* is passed straight through to ChromaDB's native metadata filter
        (e.g. ``{"note_pk": {"$in": [...]}}``). The store performs no
        post-filtering and holds no knowledge of tags or the reader — tag->pk
        resolution lives in ``mcp_server.search_notes`` (D2), keeping this a pure
        vector layer.
        """
        count = self._collection.count()
        if count == 0:
            return []

        raw = self._collection.query(
            query_texts=[text], n_results=min(n_results, count), where=where
        )

        documents, metadatas = raw["documents"], raw["metadatas"]
        # Both are always present with the default `include`; None only appears
        # when a caller opts out of them, which query() never does.
        assert documents is not None and metadatas is not None

        chunks: list[Chunk] = []
        for chunk_id, document, metadata in zip(
            raw["ids"][0], documents[0], metadatas[0], strict=True
        ):
            chunk_metadata = ChunkMetadata(
                note_pk=_metadata_int(metadata["note_pk"]),
                title=str(metadata["title"]),
                tags=str(metadata["tags"]),
                chunk_index=_metadata_int(metadata["chunk_index"]),
                heading_path=str(metadata["heading_path"]),
                modified_at=str(metadata["modified_at"]),
                source=str(metadata["source"]),
            )
            chunks.append(Chunk(id=chunk_id, text=document, metadata=chunk_metadata))
        return chunks

    def indexed_note_pks(self) -> set[int]:
        """Return the set of note PKs with at least one chunk in the collection.

        Public accessor so callers (sync reconciliation, get_stats) need not
        reach into the underlying ChromaDB collection.
        """
        if self._collection.count() == 0:
            return set()
        raw = self._collection.get(include=["metadatas"])
        assert raw["metadatas"] is not None  # requested via `include`
        return {_metadata_int(m["note_pk"]) for m in raw["metadatas"]}

    def get_stats(self) -> dict:
        """Return a dict with basic collection statistics."""
        return {
            "count": self._collection.count(),
            "note_count": len(self.indexed_note_pks()),
        }
