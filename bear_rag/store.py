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
        self._collection = self._client.create_collection(name=_COLLECTION_NAME)

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_contains_filters(where: dict) -> tuple[dict | None, dict]:
        """Split a where dict into (chromadb_where, contains_filters).

        ChromaDB's $contains operator does not work on metadata string fields.
        Any ``{"field": {"$contains": value}}`` clauses are extracted for
        post-filtering; the remainder is passed directly to ChromaDB.
        """
        contains_filters: dict = {}
        chroma_where: dict = {}
        for field, condition in where.items():
            if isinstance(condition, dict) and list(condition.keys()) == ["$contains"]:
                contains_filters[field] = condition["$contains"]
            else:
                chroma_where[field] = condition
        return (chroma_where if chroma_where else None), contains_filters

    def query(self, text: str, n_results: int = 5, where: dict | None = None) -> list[Chunk]:
        """Return up to n_results chunks most relevant to text, optionally filtered by where clause."""
        count = self._collection.count()
        if count == 0:
            return []

        contains_filters: dict = {}
        chroma_where: dict | None = where
        if where:
            chroma_where, contains_filters = self._extract_contains_filters(where)

        # When post-filtering is needed, fetch more candidates so we can trim later.
        fetch_count = count if contains_filters else min(n_results, count)
        raw = self._collection.query(
            query_texts=[text], n_results=fetch_count, where=chroma_where
        )

        chunks: list[Chunk] = []
        for chunk_id, document, metadata in zip(
            raw["ids"][0], raw["documents"][0], raw["metadatas"][0]
        ):
            # Apply $contains post-filters on metadata string fields.
            if any(value not in str(metadata.get(field, "")) for field, value in contains_filters.items()):
                continue
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
            if len(chunks) == n_results:
                break
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
