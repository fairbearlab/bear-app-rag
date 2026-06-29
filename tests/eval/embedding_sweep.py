"""Embedding-model evaluation sweep (research harness for ADR-0008).

Benchmarks alternate *local, no-network-at-inference, license-clean* embedding
models against the current production model (all-MiniLM-L6-v2) on the exact same
eval corpus and metrics as the committed RAG-vs-keyword benchmark.

Why this is a separate harness, not part of the committed suite:
- It pulls in ``fastembed`` (Apache-2.0; ONNX Runtime, no PyTorch) only to *run*
  candidate models. fastembed is a research-only dependency, declared under the
  ``[research]`` optional extra, NOT a runtime dependency. The shipped pipeline
  still uses ChromaDB's bundled ONNX MiniLM (ADR-0002).
- Candidate model weights download once from HuggingFace, then run fully offline
  — the same one-time-download / offline-after property the production model has.

Candidate pool: small/base English retrieval models exportable to ONNX via
fastembed, MIT or Apache-2.0 licensed (keeps the dependency tree license-clean).
e5 / gte-small are intentionally absent: fastembed does not package them as ONNX,
so using them would require sentence-transformers + PyTorch (~2GB), which violates
the no-torch / clean-deps constraint that motivated ADR-0002 in the first place.

Usage:
    # one model -> JSON of metrics
    uv run --extra research python tests/eval/embedding_sweep.py \
        --model bge-small-en-v1.5 --out /tmp/bge-small.json

    # the production baseline (ChromaDB DefaultEmbeddingFunction, no fastembed)
    uv run python tests/eval/embedding_sweep.py --baseline --out /tmp/baseline.json

    # aggregate per-model JSONs into a comparison table
    uv run python tests/eval/embedding_sweep.py --report /tmp/*.json \
        --report-out tests/eval/embedding_comparison.md

The deterministic eval harness is the objective scorer; these numbers arbitrate
the keep/switch decision. No LLM judge is involved here.
"""

from __future__ import annotations

import argparse
import glob
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

# tests/eval is a package; allow running as a script too.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.eval.eval_harness import EvalCorpus, run_eval  # noqa: E402

_FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Candidate roster
# ---------------------------------------------------------------------------
# key -> (fastembed model id, dim, reported size GB, license, note)
# Curated for diversity across families (minilm / bge / snowflake-arctic / gte /
# nomic) and size tiers (384-dim drop-in vs 768-dim heavier). All MIT or
# Apache-2.0, all ONNX-via-fastembed, all no-network at inference.
ROSTER: dict[str, dict] = {
    "minilm-l6-v2": {
        "fastembed_id": "sentence-transformers/all-MiniLM-L6-v2",
        "dim": 384,
        "size_gb": 0.09,
        "license": "apache-2.0",
        "family": "minilm",
        "note": "Production model run via the fastembed path; the committed baseline "
        "row uses --baseline (ChromaDB DefaultEmbeddingFunction) instead.",
    },
    "bge-small-en-v1.5": {
        "fastembed_id": "BAAI/bge-small-en-v1.5",
        "dim": 384,
        "size_gb": 0.067,
        "license": "mit",
        "family": "bge",
        "note": "Direct 384-dim drop-in; strong MTEB for its size.",
    },
    "arctic-embed-s": {
        "fastembed_id": "snowflake/snowflake-arctic-embed-s",
        "dim": 384,
        "size_gb": 0.13,
        "license": "apache-2.0",
        "family": "arctic",
        "note": "2024-era retrieval-tuned small model, 384-dim drop-in.",
    },
    "bge-base-en-v1.5": {
        "fastembed_id": "BAAI/bge-base-en-v1.5",
        "dim": 768,
        "size_gb": 0.21,
        "license": "mit",
        "family": "bge",
        "note": "768-dim; re-index required (dim change).",
    },
    "gte-base": {
        "fastembed_id": "thenlper/gte-base",
        "dim": 768,
        "size_gb": 0.44,
        "license": "mit",
        "family": "gte",
        "note": "768-dim general text embeddings.",
    },
    "arctic-embed-m": {
        "fastembed_id": "snowflake/snowflake-arctic-embed-m",
        "dim": 768,
        "size_gb": 0.43,
        "license": "apache-2.0",
        "family": "arctic",
        "note": "768-dim retrieval-tuned mid model.",
    },
    "nomic-embed-v1.5": {
        "fastembed_id": "nomic-ai/nomic-embed-text-v1.5",
        "dim": 768,
        "size_gb": 0.52,
        "license": "apache-2.0",
        "family": "nomic",
        "note": "768-dim, long-context (2048) capable.",
    },
}


# ---------------------------------------------------------------------------
# fastembed -> ChromaDB embedding function adapter
# ---------------------------------------------------------------------------


class FastEmbedFunction:
    """Adapt a fastembed ``TextEmbedding`` to ChromaDB's embedding-function API.

    ChromaDB calls one function for both documents and queries, so this embeds
    both symmetrically — exactly the realistic "drop-in replacement" scenario.
    Prefix-tuned models (bge/gte/e5 want an asymmetric "query:"/"passage:" or
    instruction prefix for peak recall) are therefore evaluated *without* that
    asymmetry; this is the honest production deployment, and the caveat is noted
    in ADR-0008.
    """

    def __init__(self, fastembed_id: str, cache_dir: str | None = None) -> None:
        from fastembed import TextEmbedding

        self._fastembed_id = fastembed_id
        self._model = TextEmbedding(model_name=fastembed_id, cache_dir=cache_dir)

    def __call__(self, input):  # noqa: A002 — ChromaDB's parameter name is `input`
        return [vec.tolist() for vec in self._model.embed(list(input))]

    def embed_query(self, input):  # noqa: A002 — ChromaDB query path (1.5.x)
        # Symmetric: queries embed the same way as documents (see class docstring).
        return self(input)

    @staticmethod
    def name() -> str:
        return "fastembed-sweep"

    # ChromaDB persists collection config; these keep create_collection happy
    # without needing the function to be globally registered.
    def get_config(self) -> dict:
        return {"fastembed_id": self._fastembed_id}

    @staticmethod
    def build_from_config(config: dict) -> "FastEmbedFunction":
        return FastEmbedFunction(config["fastembed_id"])


def _fastembed_cache_size_bytes(cache_dir: Path) -> int:
    """On-disk size of the downloaded ONNX weights for this model."""
    if not cache_dir.exists():
        return 0
    return sum(p.stat().st_size for p in cache_dir.rglob("*") if p.is_file())


# ---------------------------------------------------------------------------
# Single-model evaluation
# ---------------------------------------------------------------------------


def evaluate_model(key: str, *, baseline: bool = False) -> dict:
    """Index the eval corpus with one model and score it on the eval harness."""
    queries = json.loads((_FIXTURES_DIR / "queries.json").read_text())

    tmp = Path(tempfile.mkdtemp(prefix=f"embsweep-{key}-"))
    cache_dir = tmp / "fastembed_cache"
    meta = {"key": key, "baseline": baseline}

    try:
        if baseline:
            # Production path: ChromaDB's bundled ONNX all-MiniLM-L6-v2.
            ef = None
            spec = {
                "fastembed_id": "chromadb/DefaultEmbeddingFunction",
                "dim": 384,
                "size_gb": 0.09,
                "license": "apache-2.0",
                "family": "minilm",
                "note": "Production baseline: ChromaDB DefaultEmbeddingFunction.",
            }
        else:
            spec = ROSTER[key]
            cache_dir.mkdir(parents=True, exist_ok=True)
            ef = FastEmbedFunction(spec["fastembed_id"], cache_dir=str(cache_dir))

        meta.update(
            {
                "model_id": spec["fastembed_id"],
                "reported_dim": spec["dim"],
                "reported_size_gb": spec["size_gb"],
                "license": spec["license"],
                "family": spec["family"],
                "note": spec["note"],
            }
        )

        # Index (download happens on first embed for fastembed models).
        t0 = time.perf_counter()
        corpus = EvalCorpus(tmp, embedding_function=ef)
        index_secs = time.perf_counter() - t0

        # Time the query path across all eval queries.
        t1 = time.perf_counter()
        results = run_eval(corpus, queries, k=5, judge=False)
        eval_secs = time.perf_counter() - t1

        disk_bytes = _fastembed_cache_size_bytes(cache_dir)

        overall = results["aggregates"]["overall"]
        by_type = results["aggregates"]["by_type"]
        meta.update(
            {
                "ok": True,
                "recall": overall["recall_semantic"],
                "mrr": overall["mrr_semantic"],
                "groundedness": overall["groundedness_semantic"],
                "by_type": {
                    t: {
                        "recall": by_type[t]["recall_semantic"],
                        "mrr": by_type[t]["mrr_semantic"],
                        "groundedness": by_type[t]["groundedness_semantic"],
                    }
                    for t in by_type
                },
                "index_secs": round(index_secs, 3),
                "eval_secs": round(eval_secs, 3),
                "n_queries": len(queries),
                "disk_mb": round(disk_bytes / 1e6, 1) if disk_bytes else None,
            }
        )
        return meta
    except Exception as e:  # feasibility failures are data, not crashes
        meta.update({"ok": False, "error": f"{type(e).__name__}: {e}"})
        return meta
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# Report aggregation
# ---------------------------------------------------------------------------


def render_comparison(records: list[dict]) -> str:
    """Render a markdown comparison table from per-model JSON records."""
    ok = [r for r in records if r.get("ok")]
    # Baseline first, then by recall desc.
    ok.sort(key=lambda r: (not r.get("baseline"), -(r.get("recall") or 0)))

    lines: list[str] = []
    lines.append("# Embedding Model Comparison\n")
    lines.append(
        "Same eval corpus (25 notes, 20 queries) and metrics as the committed "
        "RAG benchmark. All models are local ONNX (no network at inference), "
        "MIT/Apache-2.0 licensed. Embeddings are symmetric (no query/passage "
        "prefix) — the realistic drop-in scenario. Higher is better for "
        "Recall@5 / MRR / Groundedness.\n"
    )
    lines.append(
        "| Model | Dim | License | Recall@5 | MRR | Groundedness | Disk | Index s | Eval s |"
    )
    lines.append(
        "|-------|-----|---------|----------|-----|--------------|------|---------|--------|"
    )
    for r in ok:
        tag = " *(current)*" if r.get("baseline") else ""
        disk = f"{r['disk_mb']:.0f}MB" if r.get("disk_mb") else f"~{r['reported_size_gb']*1000:.0f}MB"
        lines.append(
            f"| `{r['key']}`{tag} | {r['reported_dim']} | {r['license']} "
            f"| {r['recall']:.2f} | {r['mrr']:.2f} | {r['groundedness']:.2f} "
            f"| {disk} | {r['index_secs']:.1f} | {r['eval_secs']:.1f} |"
        )
    lines.append("")
    lines.append(
        "> Latency is directional only. `Index s` (embed all corpus chunks) is "
        "comparable; `Eval s` is not — the baseline's ChromaDB "
        "`DefaultEmbeddingFunction` reloads the ONNX session per query batch, "
        "while the fastembed adapter keeps the model warm in-process, so the "
        "baseline's per-query time is inflated relative to the candidates.\n"
    )

    # Per-type recall/MRR breakdown (where the families actually differ).
    types = sorted({t for r in ok for t in (r.get("by_type") or {})})
    if types:
        lines.append("## Recall@5 by query type\n")
        header = "| Model | " + " | ".join(types) + " |"
        sep = "|-------|" + "|".join(["-----"] * len(types)) + "|"
        lines.append(header)
        lines.append(sep)
        for r in ok:
            tag = " *(current)*" if r.get("baseline") else ""
            cells = " | ".join(
                f"{r['by_type'][t]['recall']:.2f}" if t in r.get("by_type", {}) else "—"
                for t in types
            )
            lines.append(f"| `{r['key']}`{tag} | {cells} |")
        lines.append("")

    failed = [r for r in records if not r.get("ok")]
    if failed:
        lines.append("## Infeasible / failed\n")
        for r in failed:
            lines.append(f"- `{r['key']}`: {r.get('error', 'unknown error')}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser(description="Embedding model eval sweep")
    ap.add_argument("--model", help="roster key to evaluate (see ROSTER)")
    ap.add_argument("--baseline", action="store_true", help="evaluate production baseline")
    ap.add_argument("--out", help="write metrics JSON to this path")
    ap.add_argument("--list", action="store_true", help="list roster keys and exit")
    ap.add_argument("--report", nargs="+", help="glob(s) of per-model JSONs to aggregate")
    ap.add_argument("--report-out", help="write comparison markdown to this path")
    args = ap.parse_args()

    if args.list:
        for k, v in ROSTER.items():
            print(f"{k:20s} {v['fastembed_id']:48s} dim={v['dim']} {v['license']}")
        return

    if args.report:
        paths: list[str] = []
        for pattern in args.report:
            paths.extend(glob.glob(pattern))
        if not paths:
            ap.error(f"--report matched no files: {args.report}")
        records = []
        for p in sorted(set(paths)):
            loaded = json.loads(Path(p).read_text())
            # A path may hold a single record or a pre-assembled list of records.
            records.extend(loaded if isinstance(loaded, list) else [loaded])
        md = render_comparison(records)
        if args.report_out:
            Path(args.report_out).write_text(md)
            print(f"Wrote {args.report_out} ({len(records)} models)")
        else:
            print(md)
        return

    if not (args.model or args.baseline):
        ap.error("one of --model, --baseline, --list, or --report is required")

    if not args.baseline and args.model not in ROSTER:
        ap.error(f"unknown model {args.model!r}; choices: {', '.join(ROSTER)}")

    # Baseline always evaluates MiniLM via the production ChromaDB path.
    key = "minilm-l6-v2" if args.baseline else args.model
    record = evaluate_model(key, baseline=args.baseline)
    out = json.dumps(record, indent=2)
    if args.out:
        Path(args.out).write_text(out)
        status = "ok" if record.get("ok") else f"FAILED: {record.get('error')}"
        print(f"Wrote {args.out} [{status}]")
    else:
        print(out)


if __name__ == "__main__":
    main()
