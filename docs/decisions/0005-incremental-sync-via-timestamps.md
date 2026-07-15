---
title: "ADR-0005: Incremental Sync via Core Data Timestamps"
---

# ADR-0005: Incremental Sync via Core Data Timestamps

Status: Accepted
Date: 2026-03-27
Context: Phase 2 (MCP server, cron sync), amended 2026-07 (stale-note reconciliation)

## Context

Bear's SQLite database uses Core Data, which stores timestamps as seconds since 2001-01-01 UTC (not the Unix epoch of 1970-01-01). The `ZMODIFICATIONDATE` column tells us when a note was last changed. We need incremental sync so that `bear-rag sync` only re-indexes notes that changed since the last run.

## Decision

Use Core Data's `ZMODIFICATIONDATE` to find changed content and reconcile the stored note set
against Bear's current active-note set. Record the sync timestamp and index schema version
in `~/.bear-rag/last_sync.json`. On each sync:

1. Read non-trashed notes with `ZMODIFICATIONDATE > last_sync_timestamp`, including archived
   rows so the cursor can advance past archive-only edits.
2. Re-chunk and upsert changed notes that are still active.
3. Read the complete set of non-trashed, non-archived primary keys from Bear.
4. Delete indexed primary keys absent from that active set. This catches archived, trashed,
   and deleted notes even when Bear does not update their modification timestamp.
5. Advance the cursor to the latest modified row and write the state file.

The epoch conversion happens once in `bear_reader.py:_core_data_to_datetime` and its inverse `_datetime_to_core_data`. All internal timestamps are UTC.

## Alternatives Considered

**Content hashing:** Detects changes without trusting timestamps, but requires reading every
note on each sync. Reconciliation already performs a cheap primary-key scan; hashing would
turn that into a full-content scan.

**File system watching (fsnotify):** Watch the Bear SQLite file for changes. Reacts in real-time but SQLite WAL mode means the file changes on reads too, causing false positives. Also requires a long-running daemon.

**Full re-index every time:** Simplest implementation. Acceptable for small vaults (<100 notes) but wasteful for larger collections. A 500-note vault takes ~30s to fully re-index.

## Consequences

### Positive
- Content reads and embedding work remain proportional to changed notes
- Cron-friendly: `bear-rag sync --quiet` runs every 15 minutes with minimal I/O
- Stale-note reconciliation does not depend on archive or trash timestamp behavior

### Negative
- Reconciliation reads all active primary keys and all indexed primary keys on each sync.
  That is O(notes + indexed chunks) metadata work even when no content changed.
- If Bear's timestamp granularity changes, content updates could be missed or repeated.
- Core Data timestamps and Bear's private schema remain implementation details this reader
  must track.

### Neutral
- `--dry-run` flag lets users preview what would change without modifying the index
