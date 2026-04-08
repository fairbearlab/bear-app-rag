# TODOS

Tracked items deferred from eng review (2026-04-05).

## Phase 1

* [ ] **Dependency privacy audit** — Audit chromadb and onnxruntime for telemetry/network calls. ChromaDB has opt-out telemetry via `ANONYMIZED_TELEMETRY` env var. Verify no data leaves the machine during indexing. Context: "local-first privacy" is the #1 differentiator; Codex flagged this as unverified. If telemetry found, disable in code and document.

## Phase 4

* [ ] **Document first-run model download** — ChromaDB downloads the ONNX all-MiniLM-L6-v2 model (\~90MB) on first use. Add a note in README quickstart: "First index takes \~30s extra to download the embedding model. Subsequent runs are instant. Requires internet for first run." Context: design doc promises 5-minute setup; offline users will hit this.

* [ ] **pyproject.toml PyPI metadata** — Add `description`, `authors`, `license`, `readme`, `repository`, `classifiers` fields. Blocked on license decision (MIT vs Apache 2.0). Once decided, \~10 lines. Required for `pip install bear-rag` from PyPI (secondary distribution channel).

* [ ] **Pin chromadb embedding function** — NoteStore uses chromadb's default embedding, which could change across chromadb major versions. Pin the model name (`all-MiniLM-L6-v2`) explicitly in `config.py` or `NoteStore.__init__` for reproducible eval results. Context: Phase 3 eval uses directional assertions as a workaround; pinning makes exact-value CI assertions possible. Depends on: Phase 3 eval completion.

