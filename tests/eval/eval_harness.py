"""Eval harness for comparing RAG vs keyword (LIKE) retrieval.

Provides EvalCorpus (indexing + dual retrieval), per-query metrics
(recall@K, MRR, keyword groundedness), an optional LLM judge, and a
report renderer that produces markdown tables and side-by-side examples.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from bear_rag import config
from bear_rag.bear_reader import BearReader
from bear_rag.chunker import chunk_note
from bear_rag.models import BearNote, Chunk
from bear_rag.store import NoteStore

_FIXTURES_DIR = Path(__file__).parent / "fixtures"

_CORE_DATA_EPOCH = datetime(2001, 1, 1, tzinfo=timezone.utc)


def _datetime_to_core_data(dt: datetime) -> float:
    """Convert a datetime to a Core Data timestamp (seconds since 2001-01-01 UTC).

    Mirrors ``tests/conftest.py``'s helper of the same purpose -- duplicated
    (rather than importing bear_reader's underscore-prefixed private helper)
    so this module doesn't reach into another module's internals.
    """
    return (dt - _CORE_DATA_EPOCH).total_seconds()


def _build_bear_fixture_db(db_path: Path, raw_notes: list[dict]) -> None:
    """Build a Bear-schema SQLite database (ZSFNOTE/ZSFNOTETAG/Z_5TAGS) from
    *raw_notes* -- the same records loaded from fixtures/notes.json.

    Mirrors the minimal schema ``tests/conftest.py``'s ``bear_db`` fixture
    builds, generalized to the eval corpus's full note set (rather than a
    fixed set of five) so tag-filtered eval cases can run end-to-end through
    ``BearReader`` / ``mcp_server.search_notes`` instead of the
    ``store.query()`` path directly (D11) -- tag->pk resolution moves out of
    the store in T4, so exercising the store alone can't gate that.
    """
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE ZSFNOTE (
            Z_PK INTEGER PRIMARY KEY,
            ZTITLE TEXT,
            ZTEXT TEXT,
            ZMODIFICATIONDATE REAL,
            ZTRASHED INTEGER DEFAULT 0,
            ZARCHIVED INTEGER DEFAULT 0
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE ZSFNOTETAG (
            Z_PK INTEGER PRIMARY KEY,
            ZTITLE TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE Z_5TAGS (
            Z_5NOTES INTEGER,
            Z_13TAGS INTEGER
        )
        """
    )

    tag_pks: dict[str, int] = {}
    note_rows: list[tuple] = []
    tag_rows: list[tuple[int, str]] = []
    join_rows: list[tuple[int, int]] = []
    for n in raw_notes:
        modified_at = datetime.fromisoformat(n["modified_at"]).replace(tzinfo=timezone.utc)
        note_rows.append(
            (n["pk"], n["title"], n["text"], _datetime_to_core_data(modified_at), 0, 0)
        )
        for tag in n.get("tags", []):
            if tag not in tag_pks:
                tag_pks[tag] = len(tag_pks) + 1
                tag_rows.append((tag_pks[tag], tag))
            join_rows.append((n["pk"], tag_pks[tag]))

    cur.executemany(
        "INSERT INTO ZSFNOTE (Z_PK, ZTITLE, ZTEXT, ZMODIFICATIONDATE, ZTRASHED, ZARCHIVED) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        note_rows,
    )
    cur.executemany("INSERT INTO ZSFNOTETAG (Z_PK, ZTITLE) VALUES (?, ?)", tag_rows)
    cur.executemany("INSERT INTO Z_5TAGS (Z_5NOTES, Z_13TAGS) VALUES (?, ?)", join_rows)
    conn.commit()
    conn.close()


class EvalCorpus:
    """Load synthetic notes, index into NoteStore + SQLite, expose dual retrieval."""

    def __init__(self, tmp_path: Path, embedding_function=None) -> None:
        notes_path = _FIXTURES_DIR / "notes.json"
        raw_notes = json.loads(notes_path.read_text())

        # Build BearNote objects and index into NoteStore. ``embedding_function``
        # defaults to None -> NoteStore uses the pinned all-MiniLM-L6-v2 default;
        # the embedding-model sweep (embedding_sweep.py) passes alternates here.
        self.store = NoteStore(
            persist_dir=tmp_path / "chroma",
            embedding_function=embedding_function,
        )
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

        # Bear-schema fixture DB + reader, for tag-filtered eval cases that
        # must run end-to-end through mcp_server.search_notes (D11) rather
        # than the store.query() path directly.
        bear_db_path = tmp_path / "bear_fixture.sqlite"
        _build_bear_fixture_db(bear_db_path, raw_notes)
        self.reader = BearReader(bear_db_path)

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

    def search_via_mcp(
        self, query: str, tags: list[str] | None = None, limit: int = 10
    ) -> list[dict]:
        """Run *query* end-to-end through ``mcp_server.search_notes``.

        Injects this corpus's reader/store into the ``mcp_server`` module
        globals -- the same injection pattern ``tests/test_mcp_server.py``
        uses (see D11) -- so tag filtering is exercised exactly as a
        connected agent would see it, not via a direct ``store.query()``
        call. Restores whatever was previously injected afterward, in case
        this corpus shares a process with another test module.
        """
        from bear_rag import mcp_server

        prev_reader, prev_store = mcp_server._reader, mcp_server._store
        mcp_server._reader = self.reader
        mcp_server._store = self.store
        try:
            return mcp_server.search_notes(query, tags=tags, limit=limit)
        finally:
            mcp_server._reader, mcp_server._store = prev_reader, prev_store


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


class LLMJudgeError(RuntimeError):
    """Raised when the LLM judge cannot produce a valid score.

    The judge fails *closed*: an API error or an unparseable (non-numeric) model
    reply raises instead of silently returning 0.0. A committed benchmark number
    must reflect a real judgment, so a broken run aborts rather than writing a
    fake score into results.json / BENCHMARK.md.
    """


def llm_judge_text(query: str, retrieved_text: str, answer_context: str) -> float:
    """Score (0.0-1.0) whether *retrieved_text* supports answering *query*.

    The retrieval-method-agnostic core of the LLM judge: it takes already-joined
    text, so it scores RAG chunk text and keyword note text on the same footing.
    Uses the same model as the rest of the project (``config.CLAUDE_MODEL``, an
    undated alias) so it keeps resolving after snapshot retirements.

    Requires ANTHROPIC_API_KEY. Fails closed: raises :class:`LLMJudgeError` on an
    API error or a non-numeric model reply (e.g. ``"0.72 because..."``) rather
    than masquerading the failure as a real 0.0 score.
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise EnvironmentError("ANTHROPIC_API_KEY required for LLM judge")

    try:
        import anthropic

        client = anthropic.Anthropic()
        response = client.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=256,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "You are evaluating retrieval quality. Given the following "
                        "retrieved text and a query, score how well the text "
                        "supports answering the query.\n\n"
                        f"**Query:** {query}\n\n"
                        f"**Expected answer context:** {answer_context}\n\n"
                        f"**Retrieved text:**\n{retrieved_text}\n\n"
                        "Respond with ONLY a decimal number between 0.0 and 1.0, "
                        "where 1.0 means the text fully supports the answer and "
                        "0.0 means it contains nothing relevant."
                    ),
                }
            ],
        )
    except Exception as e:  # network / auth / rate-limit / SDK error
        raise LLMJudgeError(f"LLM judge API call failed: {e}") from e

    try:
        score_text = response.content[0].text.strip()
    except (IndexError, AttributeError, TypeError) as e:
        raise LLMJudgeError(
            f"LLM judge returned an unexpected response shape: {e}"
        ) from e
    try:
        score = float(score_text)
    except ValueError as e:
        raise LLMJudgeError(
            f"LLM judge returned a non-numeric score: {score_text!r}"
        ) from e
    # float() accepts "nan"/"inf"; those would clamp to a fake 1.0 and quietly
    # defeat fail-closed, so reject any non-finite reply outright.
    if not math.isfinite(score):
        raise LLMJudgeError(
            f"LLM judge returned a non-finite score: {score_text!r}"
        )
    return max(0.0, min(1.0, score))


def llm_judge_groundedness(
    query: str, chunks: list[Chunk], answer_context: str
) -> float:
    """Convenience wrapper: judge a list of *chunks* by joining their text.

    ``run_eval`` scores the committed RAG/LIKE columns via ``llm_judge_text`` on
    space-joined text (symmetric across both retrieval paths); this helper exists
    for callers that hold ``Chunk`` objects rather than pre-joined text.
    """
    chunk_text = "\n\n---\n\n".join(c.text for c in chunks)
    return llm_judge_text(query, chunk_text, answer_context)


# ------------------------------------------------------------------
# Eval runner
# ------------------------------------------------------------------


def text_fingerprint(text: str) -> str:
    """Stable content hash of judged text, for carry-forward staleness checks.

    The LLM judge scores joined *text*, so the committed judge score is only
    valid while that text is unchanged. Fingerprinting the text (not just the
    retrieved PK list) catches re-chunking or note-body edits that leave the PKs
    identical but change what the judge actually saw.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def run_eval(
    corpus: EvalCorpus, queries: list[dict], k: int = 5, judge: bool = False
) -> dict:
    """Run full eval: both retrievers, all metrics, per-query and aggregated.

    When *judge* is True, also runs the (non-deterministic, API-backed) LLM judge
    on both retrieval paths and records ``llm_judge_semantic`` / ``llm_judge_like``
    per query. Requires ANTHROPIC_API_KEY.
    """
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
            # Content fingerprints of the exact text the judge scores, so
            # carry-forward can detect text drift even when PKs are unchanged.
            "semantic_text_sha": text_fingerprint(sem_text),
            "like_text_sha": text_fingerprint(like_text),
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
        if judge:
            # Judge both retrieval paths on the same footing so the column is
            # comparable to every other RAG-vs-keyword metric.
            result["llm_judge_semantic"] = llm_judge_text(
                q["query"], sem_text, q["answer_context"]
            )
            result["llm_judge_like"] = llm_judge_text(
                q["query"], like_text, q["answer_context"]
            )
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
        metrics = {
            "count": len(items),
            "recall_semantic": round(_avg(items, "recall_semantic"), 4),
            "recall_like": round(_avg(items, "recall_like"), 4),
            "mrr_semantic": round(_avg(items, "mrr_semantic"), 4),
            "mrr_like": round(_avg(items, "mrr_like"), 4),
            "groundedness_semantic": round(_avg(items, "groundedness_semantic"), 4),
            "groundedness_like": round(_avg(items, "groundedness_like"), 4),
        }
        # LLM-judge columns are present only when the eval ran with the judge.
        # Require *every* item to carry them (not just items[0]) so heterogeneous
        # judge data — e.g. a query added while EVAL_LLM_JUDGE was off — degrades
        # gracefully instead of raising KeyError inside _avg.
        if items and all(
            "llm_judge_semantic" in i and "llm_judge_like" in i for i in items
        ):
            metrics["llm_judge_semantic"] = round(_avg(items, "llm_judge_semantic"), 4)
            metrics["llm_judge_like"] = round(_avg(items, "llm_judge_like"), 4)
        return metrics

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
    if "llm_judge_semantic" in overall:
        lines.append(
            f"| LLM-Judge Groundedness | {overall['llm_judge_semantic']:.2f} "
            f"| {overall['llm_judge_like']:.2f} |"
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
