---
title: Architecture Decision Records
---

# Architecture Decision Records

Key design decisions in bear-app-rag, documented as they were made.

| ADR | Decision | Phase |
|-----|----------|-------|
| [ADR-0001](0001-no-langchain.md) | No LangChain: 4 direct dependencies, not a framework | Phase 1 |
| [ADR-0002](0002-local-onnx-embeddings.md) | Local ONNX embeddings: no note data leaves the machine | Phase 1 |
| [ADR-0003](0003-chunk-sizing-strategy.md) | Markdown-aware chunking at 300 words with heading hierarchy | Phase 1 |
| [ADR-0004](0004-mcp-as-primary-interface.md) | MCP server as primary interface, CLI for admin | Phase 2 |
| [ADR-0005](0005-incremental-sync-via-timestamps.md) | Core Data timestamps for incremental sync | Phase 2 |
| [ADR-0006](0006-hand-rolled-eval-framework.md) | Hand-rolled eval with pytest, no eval framework | Phase 3 |
| [ADR-0007](0007-mit-license.md) | MIT license for maximum adoption | Phase 4 |
