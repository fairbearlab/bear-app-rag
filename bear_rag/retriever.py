from bear_rag.models import Chunk
from bear_rag.store import NoteStore


class Retriever:
    def __init__(self, store: NoteStore):
        self._store = store

    def retrieve(self, question: str, n_results: int = 5) -> list[Chunk]:
        return self._store.query(text=question, n_results=n_results)
