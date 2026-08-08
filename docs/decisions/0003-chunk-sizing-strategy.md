---
title: "ADR-0003: Chunk Sizing Strategy"
---

# ADR-0003: Chunk Sizing Strategy

Status: Accepted
Date: 2026-03-25
Context: Phase 1 (initial design)

## Context

Chunk size materially affects retrieval. Large chunks mix several subjects into one vector; small chunks may not contain enough context to be useful evidence.

Bear notes range from one-line todos to multi-page essays with nested headings. A single chunking strategy must handle both.

## Decision

Markdown-aware chunking with a 300-word target, 30-word minimum, and 40-word overlap:

- **Split on headings** (`#`, `##`, etc.) while respecting fenced code blocks. The heading hierarchy defines the document's semantic structure, so we split where the author indicated topic boundaries.
- **300-word max** (~390 tokens for all-MiniLM-L6-v2's tokenizer). Fits within the model's effective attention window while preserving enough context for coherent retrieval.
- **30-word minimum.** Sections shorter than this are merged upward into the previous chunk. Prevents fragment noise where a two-word heading like "## Notes" would become its own chunk with no semantic content.
- **40-word overlap.** When a section exceeds 300 words and must be split mid-text, the last 40 words of each sub-chunk are prepended to the next. Preserves continuity across hard splits.

Each chunk carries `heading_path` metadata (e.g., `"# Main > ## Sub-section"`) so the retriever knows where in the document structure the chunk came from.

## Alternatives Considered

**Fixed-size splitting (every N characters/tokens):** Simple but breaks mid-sentence, mid-paragraph, mid-thought. Loses the document structure entirely.

**Recursive character splitting (LangChain-style):** Tries paragraph → sentence → character boundaries. Better than fixed-size but still ignores the document's heading hierarchy, which is the strongest semantic signal in Markdown.

**Sentence-level splitting:** Precise, but it produces many fragments for note-length content and charges one embedding to sentences that often need their neighbors for context.

## Consequences

### Positive
- Heading-aware splits align with how people structure their notes
- `heading_path` metadata enables the MCP server to tell AI agents where a chunk came from
- The merge-up strategy eliminates degenerate single-word chunks
- Overlap prevents losing context at split boundaries

### Negative
- Notes without headings (e.g., flat journal entries) get chunked as one block up to the max, then split on word boundaries. Less elegant than heading-aware splits.
- The 300-word target is empirically chosen, not theoretically optimal. Different embedding models may have different sweet spots.

### Neutral
- All chunking constants are configurable in `config.py` if future tuning is needed
