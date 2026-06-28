#!/bin/bash
# Record a terminal demo of bear-rag.
# Self-contained: no Bear database or API key required.
# Usage: mkdir -p docs/assets && asciinema rec docs/assets/demo.cast --command="bash scripts/record-demo.sh"
set -euo pipefail

echo "$ bear-rag demo"
echo ""
uv run bear-rag demo
