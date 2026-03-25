"""Command-line interface for bear-rag."""

import argparse
import os
import sys

from dotenv import load_dotenv

from bear_rag import config
from bear_rag.bear_reader import BearReader
from bear_rag.generator import generate_answer
from bear_rag.retriever import Retriever
from bear_rag.store import NoteStore
from bear_rag.sync import full_index, sync


def _print_sync_result(result, verb="Updated"):
    if result.notes_updated == 0 and result.notes_deleted == 0:
        print("No notes found.")
        return
    print(f"{verb} {result.notes_updated} notes ({result.chunks_added} chunks), deleted {result.notes_deleted}.")


def _cmd_index(args, store, reader):
    print("Running full index...")
    result = full_index(store=store, reader=reader)
    _print_sync_result(result, verb="Indexed")


def _cmd_sync(args, store, reader):
    dry_run = args.dry_run
    if dry_run:
        print("Dry run — no changes will be made.")
    try:
        result = sync(store=store, reader=reader, dry_run=dry_run)
    except Exception as exc:
        print(f"Error during sync: {exc}", file=sys.stderr)
        print("Try running 'bear-rag index' to rebuild the index.", file=sys.stderr)
        sys.exit(1)
    verb = "Would update" if dry_run else "Updated"
    _print_sync_result(result, verb=verb)


def _cmd_ask(args, store):
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY is not set.", file=sys.stderr)
        sys.exit(1)

    retriever = Retriever(store)

    if args.question:
        # One-shot mode
        chunks = retriever.retrieve(args.question)
        answer = generate_answer(args.question, chunks)
        print(answer)
    else:
        # REPL mode
        while True:
            try:
                line = input("bear-rag> ")
            except EOFError:
                break

            line = line.strip()
            if not line:
                continue
            if line.lower() in ("quit", "exit"):
                break

            chunks = retriever.retrieve(line)
            answer = generate_answer(line, chunks)
            print(answer)


def _cmd_status(args, store):
    stats = store.get_stats()
    print(f"Notes indexed: {stats['note_count']}")
    print(f"Chunks indexed: {stats['count']}")

    if config.SYNC_STATE_PATH.exists():
        import json
        state = json.loads(config.SYNC_STATE_PATH.read_text())
        print(f"Last synced: {state.get('synced_at', 'unknown')}")


def main():
    load_dotenv()

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

    # ask subcommand
    ask_parser = subparsers.add_parser("ask", help="Ask a question about your notes.")
    ask_parser.add_argument(
        "question",
        nargs="?",
        default=None,
        help="Question to answer. If omitted, enters interactive REPL mode.",
    )

    # status subcommand
    subparsers.add_parser("status", help="Show index statistics.")

    args = parser.parse_args()

    config.DATA_DIR.mkdir(parents=True, exist_ok=True)

    store = NoteStore()

    if args.command in ("index", "sync"):
        reader = BearReader()
        if args.command == "index":
            _cmd_index(args, store, reader)
        else:
            _cmd_sync(args, store, reader)
    elif args.command == "ask":
        _cmd_ask(args, store)
    elif args.command == "status":
        _cmd_status(args, store)
