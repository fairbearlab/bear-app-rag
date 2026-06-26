# TODOS

Tracked items deferred from eng review.

## Phase 1 (resolved in Phase 4)

* [x] **Dependency privacy audit** — ChromaDB telemetry disabled via `os.environ.setdefault('ANONYMIZED_TELEMETRY', 'False')` in `config.py` at import time. ONNX runtime makes no network calls during inference. Documented in ADR-002.

## Phase 4 (resolved)

* [x] **Document first-run model download** — Added to README quickstart: "First index takes ~30s extra to download the embedding model (~90MB). Subsequent runs are instant."

* [x] **pyproject.toml PyPI metadata** — Added description, authors, license (MIT), readme, repository, classifiers. License decision documented in ADR-007.

* [x] **Pin chromadb embedding function** — `DefaultEmbeddingFunction()` explicitly passed in `store.py`. `EMBEDDING_MODEL` constant added to `config.py` for documentation.

## Future

* [ ] **Expand eval corpus** — Scale to 50+ notes and 40+ queries for stronger statistical signal. Current 25-note corpus is sufficient for directional proof but honest about its limits.

* [ ] **Machine fingerprint in results.json** — Record platform, Python version, and onnxruntime version in results.json to track cross-platform embedding determinism.
