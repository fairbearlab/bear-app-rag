"""Eval test suite: RAG vs keyword (LIKE) retrieval benchmarks.

Run with: uv run pytest -m eval -v
LLM judge: EVAL_LLM_JUDGE=1 uv run pytest -m eval -v
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from tests.eval.eval_harness import (
    EvalCorpus,
    keyword_groundedness,
    mrr,
    recall_at_k,
    render_report,
    run_eval,
)

_FIXTURES_DIR = Path(__file__).parent / "fixtures"
_RESULTS_PATH = Path(__file__).parent / "results.json"
_BENCHMARK_PATH = Path(__file__).parent / "BENCHMARK.md"


# ------------------------------------------------------------------
# Unit tests for metric functions
# ------------------------------------------------------------------


class TestRecallAtK:
    @pytest.mark.eval
    def test_perfect_recall(self):
        assert recall_at_k([1, 2, 3], [1, 2, 3], k=5) == 1.0

    @pytest.mark.eval
    def test_zero_recall(self):
        assert recall_at_k([4, 5, 6], [1, 2, 3], k=5) == 0.0

    @pytest.mark.eval
    def test_partial_recall(self):
        assert recall_at_k([1, 4, 5], [1, 2, 3], k=5) == pytest.approx(1 / 3)

    @pytest.mark.eval
    def test_k_limits_retrieved(self):
        # pk=3 is in retrieved but beyond k=2
        assert recall_at_k([1, 2, 3], [3], k=2) == 0.0

    @pytest.mark.eval
    def test_empty_expected(self):
        assert recall_at_k([1, 2, 3], [], k=5) == 1.0

    @pytest.mark.eval
    def test_empty_retrieved(self):
        assert recall_at_k([], [1, 2], k=5) == 0.0


class TestMRR:
    @pytest.mark.eval
    def test_first_position(self):
        assert mrr([1, 2, 3], [1]) == 1.0

    @pytest.mark.eval
    def test_second_position(self):
        assert mrr([2, 1, 3], [1]) == 0.5

    @pytest.mark.eval
    def test_third_position(self):
        assert mrr([2, 3, 1], [1]) == pytest.approx(1 / 3)

    @pytest.mark.eval
    def test_not_found(self):
        assert mrr([2, 3, 4], [1]) == 0.0

    @pytest.mark.eval
    def test_multiple_expected_returns_first_hit(self):
        # First expected PK found at position 2 (0-indexed 1)
        assert mrr([4, 2, 1, 3], [1, 2]) == 0.5

    @pytest.mark.eval
    def test_empty_expected(self):
        assert mrr([1, 2], []) == 1.0

    @pytest.mark.eval
    def test_empty_retrieved(self):
        assert mrr([], [1]) == 0.0


class TestKeywordGroundedness:
    @pytest.mark.eval
    def test_all_found(self):
        text = "the quick brown fox jumps over the lazy dog"
        assert keyword_groundedness(text, ["quick", "fox", "dog"]) == 1.0

    @pytest.mark.eval
    def test_none_found(self):
        text = "the quick brown fox"
        assert keyword_groundedness(text, ["cat", "bird"]) == 0.0

    @pytest.mark.eval
    def test_partial(self):
        text = "the quick brown fox"
        assert keyword_groundedness(text, ["quick", "cat"]) == 0.5

    @pytest.mark.eval
    def test_empty_keywords(self):
        assert keyword_groundedness("some text", []) == 1.0

    @pytest.mark.eval
    def test_case_insensitive(self):
        text = "The Quick Brown Fox"
        assert keyword_groundedness(text, ["quick", "FOX"]) == 1.0

    @pytest.mark.eval
    def test_multi_word_keyword(self):
        text = "deep work is about sustained focus"
        assert keyword_groundedness(text, ["deep work", "focus"]) == 1.0


# ------------------------------------------------------------------
# Full eval suite
# ------------------------------------------------------------------


@pytest.fixture(scope="module")
def corpus(tmp_path_factory):
    """Create and index the eval corpus once per module."""
    tmp = tmp_path_factory.mktemp("eval")
    return EvalCorpus(tmp)


@pytest.fixture(scope="module")
def queries():
    """Load eval queries."""
    return json.loads((_FIXTURES_DIR / "queries.json").read_text())


@pytest.fixture(scope="module")
def eval_results(corpus, queries):
    """Run eval and return results. Also writes results.json and BENCHMARK.md."""
    results = run_eval(corpus, queries, k=5)

    # Write artifacts
    _RESULTS_PATH.write_text(json.dumps(results, indent=2))
    _BENCHMARK_PATH.write_text(render_report(_RESULTS_PATH))

    return results


@pytest.mark.eval
class TestEvalRetrieval:
    """Directional assertions: RAG should beat LIKE on adversarial queries."""

    def test_semantic_beats_like_recall_synonym(self, eval_results):
        by_type = eval_results["aggregates"]["by_type"]
        syn = by_type["synonym"]
        assert syn["recall_semantic"] > syn["recall_like"], (
            f"RAG recall ({syn['recall_semantic']}) should beat "
            f"LIKE recall ({syn['recall_like']}) on synonym queries"
        )

    def test_semantic_beats_like_recall_paraphrase(self, eval_results):
        by_type = eval_results["aggregates"]["by_type"]
        para = by_type["paraphrase"]
        assert para["recall_semantic"] > para["recall_like"], (
            f"RAG recall ({para['recall_semantic']}) should beat "
            f"LIKE recall ({para['recall_like']}) on paraphrase queries"
        )

    def test_semantic_beats_like_recall_multi_concept(self, eval_results):
        by_type = eval_results["aggregates"]["by_type"]
        mc = by_type["multi_concept"]
        assert mc["recall_semantic"] > mc["recall_like"], (
            f"RAG recall ({mc['recall_semantic']}) should beat "
            f"LIKE recall ({mc['recall_like']}) on multi-concept queries"
        )

    def test_overall_semantic_mrr_beats_like(self, eval_results):
        overall = eval_results["aggregates"]["overall"]
        assert overall["mrr_semantic"] > overall["mrr_like"], (
            f"RAG MRR ({overall['mrr_semantic']}) should beat "
            f"LIKE MRR ({overall['mrr_like']}) overall"
        )

    def test_results_artifact_written(self, eval_results):
        assert _RESULTS_PATH.exists()
        data = json.loads(_RESULTS_PATH.read_text())
        assert len(data["queries"]) == 20
        assert "aggregates" in data

    def test_benchmark_md_written(self, eval_results):
        assert _BENCHMARK_PATH.exists()
        content = _BENCHMARK_PATH.read_text()
        assert "Recall@5" in content
        assert "MRR" in content

    def test_exact_match_like_competitive(self, eval_results):
        """Exact match queries: keyword search should be competitive (sanity check)."""
        by_type = eval_results["aggregates"]["by_type"]
        em = by_type["exact_match"]
        # LIKE should get at least some recall on exact match queries
        assert em["recall_like"] > 0.0, (
            "LIKE recall should be non-zero on exact match queries"
        )


# ------------------------------------------------------------------
# LLM judge (opt-in)
# ------------------------------------------------------------------


@pytest.mark.eval
@pytest.mark.skipif(
    not os.environ.get("EVAL_LLM_JUDGE")
    or not os.environ.get("ANTHROPIC_API_KEY"),
    reason="Set EVAL_LLM_JUDGE=1 and ANTHROPIC_API_KEY to enable LLM judge",
)
class TestLLMJudge:
    def test_llm_judge_runs(self, corpus, queries):
        from tests.eval.eval_harness import llm_judge_groundedness

        q = queries[0]
        chunks = corpus.semantic_chunks(q["query"], k=5)
        score = llm_judge_groundedness(q["query"], chunks, q["answer_context"])
        assert 0.0 <= score <= 1.0
