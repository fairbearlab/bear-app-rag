from bear_rag.models import Chunk, ChunkMetadata
from bear_rag.retriever import Retriever
from bear_rag.store import NoteStore


def _make_chunk(note_pk: int, chunk_index: int, text: str) -> Chunk:
    return Chunk(
        id=f"note_{note_pk}_chunk_{chunk_index}",
        text=text,
        metadata=ChunkMetadata(
            note_pk=note_pk,
            title=f"Note {note_pk}",
            tags="",
            chunk_index=chunk_index,
            heading_path="",
            modified_at="2024-01-01T00:00:00+00:00",
            source="bear",
        ),
    )


def test_retrieve_returns_relevant_chunks(note_store: NoteStore) -> None:
    chunks = [
        _make_chunk(1, 0, "Python is a high-level programming language known for its clear syntax and readability."),
        _make_chunk(2, 0, "Chocolate cake recipe: mix flour, sugar, cocoa powder, eggs, butter, and bake at 350F."),
        _make_chunk(3, 0, "Machine learning is a subset of artificial intelligence that enables systems to learn from data."),
    ]
    note_store.upsert_chunks(chunks)

    retriever = Retriever(store=note_store)
    results = retriever.retrieve("Python programming language")

    assert len(results) > 0
    assert results[0].id == "note_1_chunk_0"


def test_retrieve_respects_n_results(note_store: NoteStore) -> None:
    chunks = [_make_chunk(i, 0, f"This is document number {i} about topic {i}.") for i in range(10)]
    note_store.upsert_chunks(chunks)

    retriever = Retriever(store=note_store)
    results = retriever.retrieve("document topic", n_results=3)

    assert len(results) == 3


def test_retrieve_empty_store(note_store: NoteStore) -> None:
    retriever = Retriever(store=note_store)
    results = retriever.retrieve("anything at all")

    assert results == []
