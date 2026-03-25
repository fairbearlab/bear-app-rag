from pathlib import Path

import chromadb

from bear_rag import config
from bear_rag.models import Chunk, ChunkMetadata

_COLLECTION_NAME = "bear_notes"


class NoteStore:
    def __init__(self, persist_dir: Path = config.CHROMA_DIR) -> None:
        persist_dir.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(persist_dir))
        self._collection = self._client.get_or_create_collection(name=_COLLECTION_NAME)

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def upsert_chunks(self, chunks: list[Chunk]) -> None:
        """Upsert a list of chunks into the collection."""
        if not chunks:
            return
        self._collection.upsert(
            ids=[c.id for c in chunks],
            documents=[c.text for c in chunks],
            metadatas=[dict(c.metadata) for c in chunks],
        )

    def delete_note(self, note_pk: int) -> None:
        """Delete all chunks belonging to the given note_pk."""
        self._collection.delete(where={"note_pk": note_pk})

    def reset(self) -> None:
        """Delete and recreate the collection, clearing all data."""
        self._client.delete_collection(name=_COLLECTION_NAME)
        self._collection = self._client.create_collection(name=_COLLECTION_NAME)

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def query(self, text: str, n_results: int = 5) -> list[Chunk]:
        """Return up to n_results chunks most relevant to text."""
        count = self._collection.count()
        if count == 0:
            return []
        n_results = min(n_results, count)
        raw = self._collection.query(query_texts=[text], n_results=n_results)

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
        return {"count": self._collection.count()}
