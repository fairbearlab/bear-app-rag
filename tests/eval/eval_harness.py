"""Eval harness for comparing RAG vs keyword (LIKE) retrieval.

Provides EvalCorpus (indexing + dual retrieval), per-query metrics
(recall@K, MRR, keyword groundedness), an optional LLM judge, and a
report renderer that produces markdown tables and side-by-side examples.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import warnings
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from bear_rag.chunker import chunk_note
from bear_rag.models import BearNote, Chunk
from bear_rag.store import NoteStore

_FIXTURES_DIR = Path(__file__).parent / "fixtures"


class EvalCorpus:
    """Load synthetic notes, index into NoteStore + SQLite, expose dual retrieval."""

    def __init__(self, tmp_path: Path) -> None:
        notes_path = _FIXTURES_DIR / "notes.json"
        raw_notes = json.loads(notes_path.read_text())

        # Build BearNote objects and index into NoteStore
        self.store = NoteStore(persist_dir=tmp_path / "chroma")
        self._titles: dict[int, str] = {}
        self._note_texts: dict[int, str] = {}

        all_chunks: list[Chunk] = []
        for n in raw_notes:
            note = BearNote(
                pk=n["pk"],
                title=n["title"],
                text=n["text"],
                modified_at=datetime.fromisoformat(n["modified_at"]).replace(
                    tzinfo=timezone.utc
                ),
                tags=n.get("tags", []),
                is_trashed=False,
                is_archived=False,
            )
            self._titles[note.pk] = note.title
            self._note_texts[note.pk] = note.text
            all_chunks.extend(chunk_note(note))

        self.store.upsert_chunks(all_chunks)

        # Build in-memory SQLite for LIKE baseline
        self._db = sqlite3.connect(":memory:")
        self._db.execute(
            "CREATE TABLE notes (pk INTEGER PRIMARY KEY, title TEXT, text TEXT)"
        )
        self._db.executemany(
            "INSERT INTO notes (pk, title, text) VALUES (?, ?, ?)",
            [(n["pk"], n["title"], n["text"]) for n in raw_notes],
        )
        self._db.commit()

    def get_title(self, pk: int) -> str:
        return self._titles.get(pk, f"<unknown pk={pk}>")

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def semantic_retrieve(self, query: str, k: int = 5) -> list[int]:
        """Fetch k*3 chunks, deduplicate to k unique note PKs by first-occurrence."""
        results = self.store.query(query, n_results=k * 3)
        seen: set[int] = set()
        pks: list[int] = []
        for chunk in results:
            pk = int(chunk.metadata["note_pk"])
            if pk not in seen:
                seen.add(pk)
                pks.append(pk)
                if len(pks) == k:
                    break
        return pks

    def semantic_chunks(self, query: str, k: int = 5) -> list[Chunk]:
        """Return raw chunks from semantic search (for groundedness scoring)."""
        return self.store.query(query, n_results=k * 3)

    def like_retrieve(self, query: str, k: int = 5) -> list[int]:
        """Split query into words, LIKE-match each, rank PKs by hit count."""
        words = _tokenize_query(query)
        if not words:
            return []

        hit_counts: Counter[int] = Counter()
        for word in words:
            escaped = word.replace("%", r"\%").replace("_", r"\_")
            pattern = f"%{escaped}%"
            rows = self._db.execute(
                "SELECT DISTINCT pk FROM notes "
                "WHERE text LIKE ? ESCAPE '\\' OR title LIKE ? ESCAPE '\\'",
                (pattern, pattern),
            ).fetchall()
            for (pk,) in rows:
                hit_counts[pk] += 1

        # Rank by hit count descending, break ties by pk ascending
        ranked = sorted(hit_counts.keys(), key=lambda pk: (-hit_counts[pk], pk))
        return ranked[:k]

    def like_note_texts(self, pks: list[int]) -> str:
        """Return concatenated full note texts for LIKE groundedness scoring."""
        texts: list[str] = []
        for pk in pks:
            if pk in self._note_texts:
                texts.append(self._note_texts[pk])
        return " ".join(texts)


def _tokenize_query(query: str) -> list[str]:
    """Split query into lowercase words, filtering short/stop words."""
    stop_words = {
        "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "could",
        "should", "may", "might", "can", "shall", "to", "of", "in", "for",
        "on", "with", "at", "by", "from", "as", "into", "through", "during",
        "before", "after", "above", "below", "between", "out", "off", "over",
        "under", "again", "further", "then", "once", "here", "there", "when",
        "where", "why", "how", "all", "each", "every", "both", "few", "more",
        "most", "other", "some", "such", "no", "nor", "not", "only", "own",
        "same", "so", "than", "too", "very", "just", "because", "but", "and",
        "or", "if", "while", "about", "what", "which", "who", "whom", "this",
        "that", "these", "those", "am", "it", "its", "i", "me", "my", "we",
        "our", "you", "your", "he", "her", "him", "his", "she", "they", "them",
    }
    words = re.findall(r"\w+", query.lower())
    return [w for w in words if len(w) > 1 and w not in stop_words]


# ------------------------------------------------------------------
# Metrics
# ------------------------------------------------------------------


def recall_at_k(retrieved_pks: list[int], expected_pks: list[int], k: int) -> float:
    """Fraction of expected PKs found in the top-k retrieved PKs."""
    if not expected_pks:
        return 1.0
    top_k = set(retrieved_pks[:k])
    return len(top_k & set(expected_pks)) / len(expected_pks)


def mrr(retrieved_pks: list[int], expected_pks: list[int]) -> float:
    """Reciprocal rank of the first expected PK found in retrieved list."""
    if not expected_pks:
        return 1.0
    expected_set = set(expected_pks)
    for i, pk in enumerate(retrieved_pks):
        if pk in expected_set:
            return 1.0 / (i + 1)
    return 0.0


def keyword_groundedness(text: str, expected_keywords: list[str]) -> float:
    """Fraction of expected keywords found in the given text."""
    if not expected_keywords:
        return 1.0
    text_lower = text.lower()
    found = sum(1 for kw in expected_keywords if kw.lower() in text_lower)
    return found / len(expected_keywords)


def llm_judge_groundedness(
    query: str, chunks: list[Chunk], answer_context: str
) -> float:
    """Score (0.0-1.0) whether chunks contain enough info to answer the query.

    Requires ANTHROPIC_API_KEY. Returns 0.0 with a warning on API errors.
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise EnvironmentError("ANTHROPIC_API_KEY required for LLM judge")

    try:
        import anthropic

        client = anthropic.Anthropic()
        chunk_text = "\n\n---\n\n".join(c.text for c in chunks)
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=256,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "You are evaluating retrieval quality. Given the following "
                        "retrieved text chunks and a query, score how well the chunks "
                        "support answering the query.\n\n"
                        f"**Query:** {query}\n\n"
                        f"**Expected answer context:** {answer_context}\n\n"
                        f"**Retrieved chunks:**\n{chunk_text}\n\n"
                        "Respond with ONLY a decimal number between 0.0 and 1.0, "
                        "where 1.0 means the chunks fully support the answer and "
                        "0.0 means they contain nothing relevant."
                    ),
                }
            ],
        )
        score_text = response.content[0].text.strip()
        return max(0.0, min(1.0, float(score_text)))
    except Exception as e:
        warnings.warn(f"LLM judge failed: {e}")
        return 0.0


# ------------------------------------------------------------------
# Eval runner
# ------------------------------------------------------------------


def run_eval(corpus: EvalCorpus, queries: list[dict], k: int = 5) -> dict:
    """Run full eval: both retrievers, all metrics, per-query and aggregated."""
    query_results = []

    for q in queries:
        sem_pks = corpus.semantic_retrieve(q["query"], k)
        like_pks = corpus.like_retrieve(q["query"], k)

        # Groundedness: RAG uses chunk text, LIKE uses full note text
        sem_chunks = corpus.semantic_chunks(q["query"], k)
        sem_text = " ".join(c.text for c in sem_chunks)
        like_text = corpus.like_note_texts(like_pks)

        result = {
            "id": q["id"],
            "query": q["query"],
            "type": q["type"],
            "expected_note_pks": q["expected_note_pks"],
            "semantic_pks": sem_pks,
            "like_pks": like_pks,
            "semantic_titles": [corpus.get_title(pk) for pk in sem_pks],
            "like_titles": [corpus.get_title(pk) for pk in like_pks],
            "recall_semantic": recall_at_k(sem_pks, q["expected_note_pks"], k),
            "recall_like": recall_at_k(like_pks, q["expected_note_pks"], k),
            "mrr_semantic": mrr(sem_pks, q["expected_note_pks"]),
            "mrr_like": mrr(like_pks, q["expected_note_pks"]),
            "groundedness_semantic": keyword_groundedness(
                sem_text, q["expected_keywords"]
            ),
            "groundedness_like": keyword_groundedness(
                like_text, q["expected_keywords"]
            ),
        }
        query_results.append(result)

    # Aggregate metrics
    aggregates = _aggregate(query_results)

    return {"queries": query_results, "aggregates": aggregates}


def _aggregate(query_results: list[dict]) -> dict:
    """Compute overall and per-type aggregate metrics."""
    types = sorted({q["type"] for q in query_results})

    def _avg(items: list[dict], key: str) -> float:
        vals = [item[key] for item in items]
        return sum(vals) / len(vals) if vals else 0.0

    def _metrics_for(items: list[dict]) -> dict:
        return {
            "count": len(items),
            "recall_semantic": round(_avg(items, "recall_semantic"), 4),
            "recall_like": round(_avg(items, "recall_like"), 4),
            "mrr_semantic": round(_avg(items, "mrr_semantic"), 4),
            "mrr_like": round(_avg(items, "mrr_like"), 4),
            "groundedness_semantic": round(_avg(items, "groundedness_semantic"), 4),
            "groundedness_like": round(_avg(items, "groundedness_like"), 4),
        }

    overall = _metrics_for(query_results)
    by_type = {}
    for t in types:
        subset = [q for q in query_results if q["type"] == t]
        by_type[t] = _metrics_for(subset)

    return {"overall": overall, "by_type": by_type}


# ------------------------------------------------------------------
# Report renderer
# ------------------------------------------------------------------


def render_report(results_path: Path) -> str:
    """Read results.json and return a formatted markdown report."""
    data = json.loads(results_path.read_text())
    agg = data["aggregates"]
    overall = agg["overall"]
    by_type = agg["by_type"]
    queries = data["queries"]

    lines: list[str] = []
    lines.append("# Eval Results: RAG vs Keyword (LIKE) Retrieval\n")

    # Aggregate table
    lines.append("## Aggregate Metrics\n")
    lines.append("| Metric | RAG | Keyword (LIKE) |")
    lines.append("|--------|-----|----------------|")
    lines.append(
        f"| Recall@5 | {overall['recall_semantic']:.2f} "
        f"| {overall['recall_like']:.2f} |"
    )
    lines.append(
        f"| MRR | {overall['mrr_semantic']:.2f} | {overall['mrr_like']:.2f} |"
    )
    lines.append(
        f"| Groundedness | {overall['groundedness_semantic']:.2f} "
        f"| {overall['groundedness_like']:.2f} |"
    )
    lines.append("")

    # Per-type breakdown
    lines.append("## By Query Type\n")
    lines.append(
        "| Query Type | Count | Recall RAG | Recall LIKE | MRR RAG | MRR LIKE |"
    )
    lines.append(
        "|------------|-------|------------|-------------|---------|----------|"
    )
    for t in sorted(by_type.keys()):
        m = by_type[t]
        lines.append(
            f"| {t} | {m['count']} | {m['recall_semantic']:.2f} "
            f"| {m['recall_like']:.2f} | {m['mrr_semantic']:.2f} "
            f"| {m['mrr_like']:.2f} |"
        )
    lines.append("")

    # Side-by-side examples: pick top 3 by recall divergence
    scored = sorted(
        queries,
        key=lambda q: q["recall_semantic"] - q["recall_like"],
        reverse=True,
    )
    examples = scored[:3]

    lines.append("## Side-by-Side Examples\n")
    for ex in examples:
        gap = ex["recall_semantic"] - ex["recall_like"]
        lines.append(f"### {ex['id']}: {ex['query']}")
        lines.append(f"*Type: {ex['type']} | Recall gap: {gap:+.2f}*\n")
        lines.append(
            f"**RAG returns:** {', '.join(ex['semantic_titles'][:5])}"
        )
        lines.append(
            f"**Keyword returns:** "
            f"{', '.join(ex['like_titles'][:5]) if ex['like_titles'] else '[no results]'}"
        )
        lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    results_path = Path(__file__).parent / "results.json"
    if results_path.exists():
        print(render_report(results_path))
    else:
        print(f"No results.json found at {results_path}")
        print("Run: uv run pytest -m eval -v")
