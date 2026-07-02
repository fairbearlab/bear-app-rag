---
title: "ADR-0004: MCP as Primary Interface"
---

# ADR-0004: MCP as Primary Interface

Status: Accepted
Date: 2026-03-26
Context: Phase 2 (MCP server design)

## Context

bear-app-rag started as a CLI tool (`bear-rag ask "question"`). But the real value is letting AI agents search your notes during conversations, not running CLI commands yourself. The question: what interface should AI agents use?

## Decision

Build an MCP (Model Context Protocol) server as the primary interface. The CLI is admin-only (`index`, `sync`, `status`) and debugging — it does not generate answers.

**`ask` was retired (2026-07).** Once the MCP server existed, `bear-rag ask` was a second, worse implementation of the same loop: it re-queried the store, re-built a prompt, and called the Anthropic API directly from inside this codebase — the only repo-initiated cloud egress in the whole project. Any MCP-connected agent (Claude Code, Codex CLI, etc.) already does that job better, with structured tool results instead of a hand-rolled prompt, and without requiring a second API key. Removing `ask` deleted `generator.py`, the `anthropic` production dependency, `CLAUDE_MAX_TOKENS`, and `python-dotenv` (its only consumer) — see [ADR-0002](0002-local-onnx-embeddings.md) for the resulting privacy scope and [ADR-0001](0001-no-langchain.md) for the dependency-count effect. `anthropic` remains as a dev-only extra for the eval LLM judge (`tests/eval/eval_harness.py`), which is unrelated to this interface decision.

The MCP server exposes 6 tools: `search_notes`, `read_note`, `list_notes`, `list_tags`, `sync_notes`, and `status`. Each tool has carefully written descriptions that serve as UX copy for AI agents. The descriptions explain what the tool does, when to use it, and what the return format looks like.

The server runs over stdio (local-only, no network transport) and reads the Bear database in read-only mode (`?mode=ro`).

### Tag-filtered search: snapshot semantics

`search_notes(query, tags=[...])` resolves tag membership from **live** Bear SQL (`BearReader.note_pks_for_tags` over the `Z_5TAGS`/`ZSFNOTETAG` joins — uncapped, trashed- and archived-excluding, D14), then restricts the vector search to those note PKs via ChromaDB's native `{"note_pk": {"$in": [...]}}` filter. `NoteStore.query()` stays a pure vector layer with no knowledge of tags or the reader (D2). If tag resolution yields no PKs, the tool short-circuits to `[]` rather than passing an empty `$in` (which Chroma treats as a no-op, silently returning unfiltered results — D4).

This means the two halves of a tag-filtered result come from different sources: the *membership* (which notes match the tags) is live, while the *content* (the chunk excerpts) comes from the last-indexed snapshot. A tag added or removed in Bear since the last sync is honored by the filter immediately, but the chunk text still reflects the snapshot. The gap only matters for tag edits since the last sync and self-heals on the next `sync`.

## Alternatives Considered

**REST API:** Standard, well-understood. But requires a running server process, port management, and authentication. Adds operational complexity for what's fundamentally a local tool. AI agents like Claude Code can't natively call REST endpoints during conversation.

**GraphQL:** Flexible querying but heavyweight for 6 operations. Same server-process concerns as REST.

**CLI wrapping (agent calls `bear-rag ask` via subprocess):** Works but loses structured data. The agent gets a string back instead of typed results with metadata. No support for streaming or tool-specific error handling.

**Direct library import:** The agent imports `bear_rag` as a Python module. Tightest coupling, fastest, but requires the agent to run Python and manage dependencies. Not portable across agent runtimes.

## Consequences

### Positive
- Claude Code (and any MCP-compatible agent) can search notes natively during conversation
- stdio transport means zero network config, zero auth, zero port conflicts
- Tool descriptions guide agents to use the right tool for each task
- Structured JSON returns with citation metadata (note PK, title, tags, heading path)

### Negative
- MCP is a newer protocol with a smaller ecosystem than REST
- Agents that don't support MCP can't use the server directly
- stdio transport means one server per agent session (no shared service)

### Neutral
- The CLI still works for all operations, so MCP is additive, not a migration
