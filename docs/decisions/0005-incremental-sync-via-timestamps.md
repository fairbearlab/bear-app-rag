---
title: "ADR-0005: Incremental Sync via Core Data Timestamps"
---

# ADR-0005: Incremental Sync via Core Data Timestamps

Status: Accepted
Date: 2026-03-27
Context: Phase 2 (MCP server, cron sync)

## Context

Bear's SQLite database uses Core Data, which stores timestamps as seconds since 2001-01-01 UTC (not the Unix epoch of 1970-01-01). The `ZMODIFICATIONDATE` column tells us when a note was last changed. We need incremental sync so that `bear-rag sync` only re-indexes notes that changed since the last run.

## Decision

Use Core Data's `ZMODIFICATIONDATE` for change detection. Record the sync timestamp in `~/.bear-rag/last_sync.json`. On each sync:

1. Convert our stored UTC timestamp to Core Data epoch
2. Query Bear's database for notes with `ZMODIFICATIONDATE > last_sync_timestamp`
3. Upsert changed note chunks into ChromaDB
4. Delete chunks for notes that were trashed since last sync
5. Write the new sync timestamp

The epoch conversion happens once in `bear_reader.py:_core_data_to_datetime` and its inverse `_datetime_to_core_data`. All internal timestamps are UTC.

## Alternatives Considered

**Content hashing:** Hash each note's text and compare with stored hashes. Detects changes regardless of timestamps but requires reading every note on every sync. O(n) reads vs O(changed) with timestamp filtering.

**File system watching (fsnotify):** Watch the Bear SQLite file for changes. Reacts in real-time but SQLite WAL mode means the file changes on reads too, causing false positives. Also requires a long-running daemon.

**Full re-index every time:** Simplest implementation. Acceptable for small vaults (<100 notes) but wasteful for larger collections. A 500-note vault takes ~30s to fully re-index.

## Consequences

### Positive
- Sync is O(changed notes), not O(all notes)
- Cron-friendly: `bear-rag sync --quiet` runs every 15 minutes with minimal I/O
- Timestamp comparison is a single SQL WHERE clause, fast on any vault size

### Negative
- Trash detection requires querying all trashed PKs and comparing against indexed PKs. This is O(trashed) per sync, which we accept as a trade-off for simplicity.
- If Bear's timestamp granularity changes (unlikely), sync could miss or re-process notes
- Core Data epoch is an implementation detail we're coupling to. If Bear switched databases (very unlikely), the reader would need updating.

### Neutral
- `--dry-run` flag lets users preview what would change without modifying the index
