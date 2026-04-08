from pathlib import Path

import chromadb
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

from bear_rag import config
from bear_rag.models import Chunk, ChunkMetadata

_COLLECTION_NAME = "bear_notes"


class NoteStore:
    def __init__(self, persist_dir: Path = config.CHROMA_DIR) -> None:
        persist_dir.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(persist_dir))
        self._collection = self._client.get_or_create_collection(
            name=_COLLECTION_NAME,
            embedding_function=DefaultEmbeddingFunction(),
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
            embedding_function=DefaultEmbeddingFunction(),
        )

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_contains_filters(
        where: dict,
    ) -> tuple[dict | None, list[tuple[str, str, str]], list[list[dict]]]:
        """Split a where dict into (chromadb_where, contains_filters, mixed_or_groups).

        ChromaDB's $contains operator does not work on metadata string fields.
        Any ``{"field": {"$contains": value}}`` clauses are extracted for
        post-filtering; the remainder is passed directly to ChromaDB.

        Returns (chroma_where, contains_filters, mixed_or_groups) where:
        - contains_filters is a list of (field, value, mode) tuples. mode is
          "all" for top-level conditions or "any" for all-$contains $or groups.
        - mixed_or_groups is a list of $or clause lists that mix $contains and
          non-$contains conditions. These cannot be split without changing OR
          semantics, so the entire group is evaluated in post-filtering.
        """
        contains_filters: list[tuple[str, str, str]] = []
        mixed_or_groups: list[list[dict]] = []
        chroma_where: dict = {}
        for field, condition in where.items():
            if isinstance(condition, dict) and list(condition.keys()) == ["$contains"]:
                contains_filters.append((field, condition["$contains"], "all"))
            elif field == "$or" and isinstance(condition, list):
                has_contains = False
                has_other = False
                for clause in condition:
                    if isinstance(clause, dict) and len(clause) == 1:
                        f, c = next(iter(clause.items()))
                        if isinstance(c, dict) and list(c.keys()) == ["$contains"]:
                            has_contains = True
                            continue
                    has_other = True

                if has_contains and has_other:
                    # Mixed $or: splitting would change OR into AND semantics.
                    # Evaluate the entire group in post-filtering.
                    mixed_or_groups.append(condition)
                elif has_contains:
                    # All $contains: extract for post-filtering.
                    for clause in condition:
                        f, c = next(iter(clause.items()))
                        contains_filters.append((f, c["$contains"], "any"))
                else:
                    # All non-$contains: pass to Chroma.
                    chroma_where["$or"] = condition
            else:
                chroma_where[field] = condition
        return (chroma_where if chroma_where else None), contains_filters, mixed_or_groups

    @staticmethod
    def _eval_condition(metadata: dict, field: str, condition) -> bool:
        """Evaluate a single field condition against metadata."""
        val = metadata.get(field, "")
        if isinstance(condition, dict):
            op, operand = next(iter(condition.items()))
            if op == "$contains":
                return operand in str(val)
            elif op == "$eq":
                return val == operand
            elif op == "$ne":
                return val != operand
            elif op == "$gt":
                return val > operand
            elif op == "$gte":
                return val >= operand
            elif op == "$lt":
                return val < operand
            elif op == "$lte":
                return val <= operand
            elif op == "$in":
                return val in operand
            elif op == "$nin":
                return val not in operand
            return False
        # Implicit equality
        return val == condition

    @staticmethod
    def _matches_or_group(metadata: dict, or_group: list[dict]) -> bool:
        """Check if metadata matches at least one branch of an $or group."""
        for clause in or_group:
            if all(
                NoteStore._eval_condition(metadata, f, c)
                for f, c in clause.items()
            ):
                return True
        return False

    @staticmethod
    def _matches_contains_filters(metadata: dict, filters: list[tuple[str, str, str]]) -> bool:
        """Check if metadata matches all extracted $contains filters.

        Each filter is (field, value, mode). "all" filters must all match.
        "any" filters (from $or) need at least one to match.
        """
        all_filters = [(f, v) for f, v, m in filters if m == "all"]
        any_filters = [(f, v) for f, v, m in filters if m == "any"]

        for field, value in all_filters:
            if value not in str(metadata.get(field, "")):
                return False

        if any_filters and not any(
            value in str(metadata.get(field, ""))
            for field, value in any_filters
        ):
            return False

        return True

    def query(self, text: str, n_results: int = 5, where: dict | None = None) -> list[Chunk]:
        """Return up to n_results chunks most relevant to text, optionally filtered by where clause."""
        count = self._collection.count()
        if count == 0:
            return []

        contains_filters: list[tuple[str, str, str]] = []
        mixed_or_groups: list[list[dict]] = []
        chroma_where: dict | None = where
        if where:
            chroma_where, contains_filters, mixed_or_groups = self._extract_contains_filters(where)

        # When post-filtering is needed, fetch more candidates so we can trim later.
        needs_post_filter = contains_filters or mixed_or_groups
        fetch_count = count if needs_post_filter else min(n_results, count)
        raw = self._collection.query(
            query_texts=[text], n_results=fetch_count, where=chroma_where
        )

        chunks: list[Chunk] = []
        for chunk_id, document, metadata in zip(
            raw["ids"][0], raw["documents"][0], raw["metadatas"][0]
        ):
            # Apply post-filters on metadata fields.
            if not self._matches_contains_filters(metadata, contains_filters):
                continue
            if not all(self._matches_or_group(metadata, g) for g in mixed_or_groups):
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
