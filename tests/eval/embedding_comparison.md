# Embedding Model Comparison

Same eval corpus (25 notes, 20 queries) and metrics as the committed RAG benchmark. All models are local ONNX (no network at inference), MIT/Apache-2.0 licensed. Embeddings are symmetric (no query/passage prefix) — the realistic drop-in scenario. Higher is better for Recall@5 / MRR / Groundedness.

| Model | Dim | License | Recall@5 | MRR | Groundedness | Disk | Index s | Eval s |
|-------|-----|---------|----------|-----|--------------|------|---------|--------|
| `minilm-l6-v2` *(current)* | 384 | apache-2.0 | 0.92 | 0.90 | 0.86 | ~90MB | 1.0 | 1.9 |
| `nomic-embed-v1.5` | 768 | apache-2.0 | 0.97 | 0.88 | 0.88 | 1096MB | 3.3 | 0.4 |
| `bge-small-en-v1.5` | 384 | mit | 0.93 | 0.87 | 0.86 | 134MB | 1.2 | 0.2 |
| `bge-base-en-v1.5` | 768 | mit | 0.90 | 0.84 | 0.86 | 437MB | 2.9 | 0.3 |
| `arctic-embed-m` | 768 | apache-2.0 | 0.86 | 0.69 | 0.64 | 873MB | 2.7 | 0.3 |
| `arctic-embed-s` | 384 | apache-2.0 | 0.84 | 0.61 | 0.67 | 268MB | 1.1 | 0.2 |

> Latency is directional only. `Index s` (embed all corpus chunks) is comparable; `Eval s` is not — the baseline's ChromaDB `DefaultEmbeddingFunction` reloads the ONNX session per query batch, while the fastembed adapter keeps the model warm in-process, so the baseline's per-query time is inflated relative to the candidates.

## Recall@5 by query type

| Model | exact_match | multi_concept | paraphrase | synonym |
|-------|-----|-----|-----|-----|
| `minilm-l6-v2` *(current)* | 1.00 | 0.83 | 1.00 | 0.83 |
| `nomic-embed-v1.5` | 1.00 | 0.90 | 1.00 | 1.00 |
| `bge-small-en-v1.5` | 1.00 | 0.77 | 1.00 | 0.93 |
| `bge-base-en-v1.5` | 1.00 | 0.77 | 1.00 | 0.83 |
| `arctic-embed-m` | 1.00 | 0.60 | 1.00 | 0.83 |
| `arctic-embed-s` | 1.00 | 0.53 | 1.00 | 0.83 |

## Infeasible / failed

- `gte-base`: ValueError: setting an array element with a sequence. The requested array has an inhomogeneous shape after 1 dimensions. The detected shape was (100,) + inhomogeneous part. in upsert.
