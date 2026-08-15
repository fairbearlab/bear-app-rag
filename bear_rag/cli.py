"""Command-line interface for bear-rag."""

import argparse
import sys

from bear_rag import config
from bear_rag.bear_reader import BearReader
from bear_rag.status import get_status
from bear_rag.store import NoteStore
from bear_rag.sync import full_index, sync


def _print_sync_result(result, verb="Updated"):
    if result.notes_updated == 0 and result.notes_deleted == 0:
        print("No notes found.")
        return
    print(
        f"{verb} {result.notes_updated} notes ({result.chunks_added} chunks), "
        f"deleted {result.notes_deleted}."
    )


def _cmd_index(args, store, reader):
    print("Running full index...")
    result = full_index(store=store, reader=reader)
    _print_sync_result(result, verb="Indexed")


def _cmd_sync(args, store, reader):
    dry_run = args.dry_run
    quiet = args.quiet
    if dry_run:
        print("Dry run — no changes will be made.")
    try:
        result = sync(store=store, reader=reader, dry_run=dry_run)
    except Exception as exc:
        print(f"Error during sync: {exc}", file=sys.stderr)
        print("Try running 'bear-rag index' to rebuild the index.", file=sys.stderr)
        sys.exit(1)
    if quiet and result.notes_updated == 0 and result.notes_deleted == 0:
        return
    verb = "Would update" if dry_run else "Updated"
    _print_sync_result(result, verb=verb)


def _cmd_status(args, store):
    result = get_status(store)
    print(f"Notes indexed: {result['note_count']}")
    print(f"Chunks indexed: {result['index_count']}")
    print(f"Last synced: {result['last_sync'] or 'never'}")


def main():
    parser = argparse.ArgumentParser(
        prog="bear-rag",
        description="RAG over your Bear notes.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # index subcommand
    subparsers.add_parser("index", help="Wipe and re-index all notes from scratch.")

    # sync subcommand
    sync_parser = subparsers.add_parser("sync", help="Incrementally sync changed notes.")
    sync_parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Show what would change without modifying the store.",
    )
    sync_parser.add_argument(
        "--quiet",
        action="store_true",
        default=False,
        help="Suppress output when there are no changes.",
    )

    # status subcommand
    subparsers.add_parser("status", help="Show index statistics.")

    # demo subcommand
    subparsers.add_parser(
        "demo", help="Run a self-contained benchmark demo (no Bear database required)."
    )

    args = parser.parse_args()

    # Demo creates its own temp store — handle before NoteStore/BearReader init.
    if args.command == "demo":
        from bear_rag.demo import run_demo

        run_demo()
        return

    config.DATA_DIR.mkdir(parents=True, exist_ok=True)

    store = NoteStore()

    if args.command in ("index", "sync"):
        reader = BearReader()
        if args.command == "index":
            _cmd_index(args, store, reader)
        else:
            _cmd_sync(args, store, reader)
    elif args.command == "status":
        _cmd_status(args, store)
