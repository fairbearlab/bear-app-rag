"""Self-contained demo comparing semantic (RAG) vs keyword (LIKE) retrieval.

Runs against an inline corpus — no Bear database or API key required.
"""

from __future__ import annotations

import re
import shutil
import sqlite3
import tempfile
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from bear_rag import config  # noqa: F401 — ensures ANONYMIZED_TELEMETRY is set
from bear_rag.chunker import chunk_note
from bear_rag.models import BearNote, Chunk
from bear_rag.store import NoteStore

# ---------------------------------------------------------------------------
# Inline corpus — 5 notes designed for maximum synonym contrast
# ---------------------------------------------------------------------------

DEMO_CORPUS: list[dict] = [
    {
        "pk": 1,
        "title": "Grandma's Sunday Pasta Sauce",
        "text": (
            "# Grandma's Sunday Pasta Sauce\n\n"
            "## Ingredients\n\n"
            "- 2 lbs San Marzano tomatoes\n"
            "- Fresh basil, garlic, olive oil\n"
            "- Parmigiano-Reggiano rind\n\n"
            "## Preparation\n\n"
            "The secret to rich flavor is patience. Let the sauce simmer on low "
            "heat for at least three hours. The ingredients meld together slowly, "
            "building layers of savory depth. Stir occasionally and taste as you go.\n\n"
            "## Serving Notes\n\n"
            "Pair with fresh rigatoni and a bold red wine. The preparation time is "
            "worth every minute when you see the family gather around the table."
        ),
        "tags": ["cooking", "recipes", "family"],
        "modified_at": "2025-12-01T10:00:00+00:00",
    },
    {
        "pk": 2,
        "title": "Southeast Asia on a Shoestring",
        "text": (
            "# Southeast Asia on a Shoestring\n\n"
            "## Planning the Journey\n\n"
            "After months of saving, I mapped out a three-week journey through "
            "Thailand, Vietnam, and Cambodia. The total budget came to roughly "
            "$2,000 including flights.\n\n"
            "## Managing Expenses\n\n"
            "Tracking every expense in a spreadsheet kept me honest. Street food "
            "averaged $2 per meal; hostels ran $8-15 per night. The biggest budget "
            "item was domestic flights between cities.\n\n"
            "## Highlights\n\n"
            "Watching the sunrise over Angkor Wat was the emotional peak of the "
            "entire journey. Sometimes the most affordable adventures leave the "
            "deepest impression."
        ),
        "tags": ["travel", "budget", "asia"],
        "modified_at": "2025-11-15T08:30:00+00:00",
    },
    {
        "pk": 3,
        "title": "Deep Work and Focus Strategies",
        "text": (
            "# Deep Work and Focus Strategies\n\n"
            "## The Case for Concentration\n\n"
            "Cal Newport argues that the ability to perform deep work is becoming "
            "increasingly rare and increasingly valuable. True concentration "
            "requires eliminating every source of distraction — notifications, "
            "social media, even background music.\n\n"
            "## Practical Techniques\n\n"
            "1. Time-block your calendar in 90-minute focus sessions\n"
            "2. Use a physical notebook to capture stray thoughts without "
            "switching context\n"
            "3. Set a clear shutdown ritual to separate work from rest\n\n"
            "## Measuring Progress\n\n"
            "Track hours of genuine deep focus per week. Most knowledge workers "
            "manage only 2-3 hours daily. The goal is to push that toward 4-5 "
            "hours through deliberate practice and distraction elimination."
        ),
        "tags": ["productivity", "books", "self-improvement"],
        "modified_at": "2025-10-20T14:00:00+00:00",
    },
    {
        "pk": 4,
        "title": "Deployment Best Practices",
        "text": (
            "# Deployment Best Practices\n\n"
            "## Release Pipeline\n\n"
            "Every deploy should follow the same pipeline: lint, test, build, "
            "stage, canary, then full rollout. Automating each step reduces human "
            "error and lets you ship with confidence.\n\n"
            "## Rollback Strategy\n\n"
            "Before you release anything, make sure you can roll back within "
            "seconds. Blue-green deployments or feature flags give you a safety "
            "net when a deploy goes sideways.\n\n"
            "## Monitoring After Ship\n\n"
            "The job isn't done when you ship the code. Watch error rates, "
            "latency percentiles, and user-facing metrics for at least 30 minutes "
            "after every release. Alerting should page on-call if key SLOs breach "
            "thresholds."
        ),
        "tags": ["engineering", "devops", "best-practices"],
        "modified_at": "2025-09-10T16:45:00+00:00",
    },
    {
        "pk": 5,
        "title": "Wednesday Reflections",
        "text": (
            "# Wednesday Reflections\n\n"
            "## Morning\n\n"
            "Woke up early and tried a new pour-over technique — the coffee had "
            "a much brighter flavor than my usual method. Need to write down the "
            "exact ratio before I forget.\n\n"
            "## Afternoon\n\n"
            "Spent two hours in deep focus finishing the quarterly report. Felt "
            "great to finally ship that deliverable after weeks of procrastination. "
            "The expense report for the team offsite is still pending though.\n\n"
            "## Evening\n\n"
            "Cooked a quick stir-fry for dinner — nothing fancy, but the "
            "preparation was relaxing after a long day. Reading a chapter of the "
            "new novel before bed. Grateful for quiet evenings like this."
        ),
        "tags": ["journal", "daily"],
        "modified_at": "2025-12-05T22:00:00+00:00",
    },
]

# ---------------------------------------------------------------------------
# Curated demo queries
# ---------------------------------------------------------------------------

DEMO_QUERIES: list[dict] = [
    {
        "query": "How do I avoid scattered attention while working?",
        "type": "synonym",
        "expected_note_pks": [3],
    },
    {
        "query": "How should I manage money while traveling abroad?",
        "type": "paraphrase",
        "expected_note_pks": [2],
    },
    {
        "query": "deployment rollback strategy",
        "type": "exact",
        "expected_note_pks": [4],
    },
]


# ---------------------------------------------------------------------------
# Simplified keyword search (duplicated from eval_harness.py by design)
# ---------------------------------------------------------------------------

_STOP_WORDS = {
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


def _tokenize_query(query: str) -> list[str]:
    words = re.findall(r"\w+", query.lower())
    return [w for w in words if len(w) > 1 and w not in _STOP_WORDS]


def _keyword_retrieve(db: sqlite3.Connection, query: str, k: int = 5) -> list[int]:
    """Split query into words, LIKE-match each, rank PKs by hit count."""
    words = _tokenize_query(query)
    if not words:
        return []

    hit_counts: Counter[int] = Counter()
    for word in words:
        escaped = word.replace("%", r"\%").replace("_", r"\_")
        pattern = f"%{escaped}%"
        rows = db.execute(
            "SELECT DISTINCT pk FROM notes "
            "WHERE text LIKE ? ESCAPE '\\' OR title LIKE ? ESCAPE '\\'",
            (pattern, pattern),
        ).fetchall()
        for (pk,) in rows:
            hit_counts[pk] += 1

    ranked = sorted(hit_counts.keys(), key=lambda pk: (-hit_counts[pk], pk))
    return ranked[:k]


def _reciprocal_rank(retrieved_pks: list[int], expected_pks: set[int]) -> float:
    """Reciprocal rank of the first expected pk in the retrieved list.

    Returns 1/rank (1-indexed) for the first hit, or 0.0 if no expected pk
    appears. This is the per-query component of MRR — the same metric the
    eval suite uses, so the demo's headline tracks the published numbers.
    """
    for rank, pk in enumerate(retrieved_pks, 1):
        if pk in expected_pks:
            return 1.0 / rank
    return 0.0


def _keyword_titles(db: sqlite3.Connection, pks: list[int]) -> list[str]:
    titles: list[str] = []
    for pk in pks:
        row = db.execute("SELECT title FROM notes WHERE pk = ?", (pk,)).fetchone()
        if row:
            titles.append(row[0])
    return titles


# ---------------------------------------------------------------------------
# Demo runner
# ---------------------------------------------------------------------------

def run_demo() -> None:
    """Run the self-contained RAG vs keyword demo and print results."""
    tmp_dir: str | None = None

    try:
        try:
            tmp_dir = tempfile.mkdtemp(prefix="bear_rag_demo_")
        except OSError:
            print("Could not create temporary directory for demo")
            return

        persist_dir = Path(tmp_dir) / "chroma"
        titles_by_pk: dict[int, str] = {}

        # -- Index corpus into NoteStore --
        try:
            store = NoteStore(persist_dir=persist_dir)
        except Exception as exc:
            print(
                "Embedding model not yet cached. "
                "Run with internet access first (~90MB download, one-time).\n"
                f"  (original error: {exc})"
            )
            return

        all_chunks: list[Chunk] = []
        for n in DEMO_CORPUS:
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
            titles_by_pk[note.pk] = note.title
            all_chunks.extend(chunk_note(note))

        store.upsert_chunks(all_chunks)

        # -- Build in-memory SQLite for keyword baseline --
        db = sqlite3.connect(":memory:")
        db.execute(
            "CREATE TABLE notes (pk INTEGER PRIMARY KEY, title TEXT, text TEXT)"
        )
        db.executemany(
            "INSERT INTO notes (pk, title, text) VALUES (?, ?, ?)",
            [(n["pk"], n["title"], n["text"]) for n in DEMO_CORPUS],
        )
        db.commit()

        # -- Run queries --
        print("bear-rag demo — RAG vs Keyword Search")
        print("=" * 38)
        print()

        semantic_wins = 0
        keyword_wins = 0
        ties = 0

        for i, q in enumerate(DEMO_QUERIES, 1):
            query = q["query"]
            expected_pks = set(q["expected_note_pks"])

            # Semantic retrieval with timing
            t0 = time.perf_counter()
            sem_chunks = store.query(query, n_results=5)
            sem_elapsed_ms = (time.perf_counter() - t0) * 1000

            # Deduplicate to unique note PKs
            seen: set[int] = set()
            sem_pks: list[int] = []
            for chunk in sem_chunks:
                pk = int(chunk.metadata["note_pk"])
                if pk not in seen:
                    seen.add(pk)
                    sem_pks.append(pk)
            sem_titles = [titles_by_pk[pk] for pk in sem_pks]

            # Keyword retrieval with timing
            t0 = time.perf_counter()
            kw_pks = _keyword_retrieve(db, query)
            kw_elapsed_ms = (time.perf_counter() - t0) * 1000
            kw_titles = _keyword_titles(db, kw_pks)

            # Score by MRR (Mean Reciprocal Rank): rank of the first expected
            # hit, 0 if not found. Matches the metric used in tests/eval/eval_harness.py.
            sem_mrr = _reciprocal_rank(sem_pks, expected_pks)
            kw_mrr = _reciprocal_rank(kw_pks, expected_pks)

            if sem_mrr > kw_mrr:
                winner = f"Semantic (MRR {sem_mrr:.2f} vs {kw_mrr:.2f})"
                semantic_wins += 1
            elif kw_mrr > sem_mrr:
                winner = f"Keyword (MRR {kw_mrr:.2f} vs {sem_mrr:.2f})"
                keyword_wins += 1
            else:
                winner = f"Tie (MRR {sem_mrr:.2f})"
                ties += 1

            # Format output
            sem_display = ", ".join(sem_titles) if sem_titles else "[no results]"
            kw_display = ", ".join(kw_titles) if kw_titles else "[no results]"

            print(f'Query {i}: "{query}"')
            print(f"  Semantic ({sem_elapsed_ms:.0f}ms): {sem_display}")
            print(f"  Keyword  ({kw_elapsed_ms:.0f}ms):  {kw_display}")
            print(f"  Winner: {winner}")
            print()

        total = len(DEMO_QUERIES)
        print(
            f"Summary: Semantic won {semantic_wins}/{total}, "
            f"Keyword won {keyword_wins}/{total}, "
            f"Tied {ties}/{total}"
        )

    finally:
        if tmp_dir is not None:
            shutil.rmtree(tmp_dir, ignore_errors=True)
