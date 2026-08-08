---
title: "ADR-0004: MCP as Primary Interface"
---

# ADR-0004: MCP as Primary Interface

Status: Accepted
Date: 2026-03-26
Context: Phase 2 (MCP server design)

## Context

bear-app-rag started with a CLI answer command, `bear-rag ask "question"`. Once retrieval needed to work inside an agent conversation, the project needed a structured interface for search and note access rather than a second answer generator.

## Decision

Build an MCP server as the primary retrieval interface. The CLI handles `index`, `sync`, `status`, and the self-contained `demo`; it does not generate answers.

**`ask` was retired (2026-07).** It queried the same store, built its own prompt, and called Anthropic from the installed application. MCP already returned structured chunks to an agent capable of generating the answer. Removing the duplicate path also removed `generator.py`, `CLAUDE_MAX_TOKENS`, `python-dotenv`, and the production `anthropic` dependency. `anthropic` remains in the development extra for the unrelated eval judge.

The MCP server exposes six tools: `search_notes`, `read_note`, `list_notes`, `list_tags`, `sync_notes`, and `status`. Their descriptions tell the caller when to use the tool and what the returned structure contains.

The server runs over stdio (local-only, no network transport) and reads the Bear database in read-only mode (`?mode=ro`).

### Tag-filtered search: snapshot semantics

`search_notes(query, tags=[...])` resolves tag membership from live Bear SQL through `BearReader.note_pks_for_tags()`. The resolver is uncapped and excludes trashed and archived notes. It then restricts the vector query with ChromaDB's native `{"note_pk": {"$in": [...]}}` filter. `NoteStore.query()` stays a vector-only layer. If no primary key matches, the tool returns `[]`; passing an empty `$in` can behave like no filter and expose unrelated results.

This means the two halves of a tag-filtered result come from different sources: the *membership* (which notes match the tags) is live, while the *content* (the chunk excerpts) comes from the last-indexed snapshot. A tag added or removed in Bear since the last sync is honored by the filter immediately, but the chunk text still reflects the snapshot. The gap only matters for tag edits since the last sync and self-heals on the next `sync`.

## Alternatives Considered

**REST API:** Standard, well-understood. But requires a running server process, port management, and authentication. Adds operational complexity for what's fundamentally a local tool. AI agents like Claude Code can't natively call REST endpoints during conversation.

**GraphQL:** Flexible querying but heavyweight for 6 operations. Same server-process concerns as REST.

**CLI wrapping:** A subprocess can return text, but it loses the structured metadata and tool-specific error contract MCP provides.

**Direct library import:** The agent imports `bear_rag` as a Python module. Tightest coupling, fastest, but requires the agent to run Python and manage dependencies. Not portable across agent runtimes.

## Consequences

### Positive
- MCP-compatible hosts can search notes during a conversation
- stdio transport means zero network config, zero auth, zero port conflicts
- Tool descriptions guide agents to use the right tool for each task
- Structured JSON returns with citation metadata (note PK, title, tags, heading path)

### Negative
- MCP is a newer protocol with a smaller ecosystem than REST
- Agents that don't support MCP can't use the server directly
- stdio transport means one server per agent session (no shared service)

### Neutral
- The CLI and MCP server share storage and sync logic but serve different workflows
