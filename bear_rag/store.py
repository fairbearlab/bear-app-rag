from pathlib import Path

import chromadb
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

from bear_rag import config
from bear_rag.models import Chunk, ChunkMetadata

_COLLECTION_NAME = "bear_notes"


class NoteStore:
    def __init__(
        self,
        persist_dir: Path = config.CHROMA_DIR,
        embedding_function=None,
    ) -> None:
        # Default to ChromaDB's local ONNX all-MiniLM-L6-v2 (see ADR-0002). The
        # injection point exists so the eval harness can benchmark alternate
        # local models (see tests/eval/embedding_sweep.py and ADR-0008); the
        # production path always uses the pinned default.
        self._embedding_function = embedding_function or DefaultEmbeddingFunction()
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
                metadatas=[dict(c.metadata) for c in batch],
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
        """Return up to n_results chunks most relevant to text, optionally filtered by a where clause.

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

        chunks: list[Chunk] = []
        for chunk_id, document, metadata in zip(
            raw["ids"][0], raw["documents"][0], raw["metadatas"][0]
        ):
            chunk_metadata = ChunkMetadata(
                note_pk=int(metadata["note_pk"]),
                title=str(metadata["title"]),
                tags=str(metadata["tags"]),
                chunk_index=int(metadata["chunk_index"]),
                heading_path=str(metadata["heading_path"]),
                modified_at=str(metadata["modified_at"]),
                source=str(metadata["source"]),
            )
            chunks.append(Chunk(id=chunk_id, text=document, metadata=chunk_metadata))
        return chunks

    def get_stats(self) -> dict:
        """Return a dict with basic collection statistics."""
        count = self._collection.count()
        note_count = 0
        if count > 0:
            result = self._collection.get(include=["metadatas"])
            note_pks = {m["note_pk"] for m in result["metadatas"]}
            note_count = len(note_pks)
        return {"count": count, "note_count": note_count}
