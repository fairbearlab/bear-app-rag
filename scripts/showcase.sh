#!/bin/bash
# Regenerate all Phase 4 artifacts from source data.
# Prerequisites: uv, Python 3.11+
set -euo pipefail

# Check prerequisites
if ! command -v uv &> /dev/null; then
  echo "Error: uv is required. Install from https://docs.astral.sh/uv/"
  exit 1
fi

python_version=$(uv run python --version 2>&1)
echo "Using $python_version"

echo ""
echo "=== Running eval suite ==="
unset EVAL_LLM_JUDGE 2>/dev/null || true
uv run pytest -m eval -v

echo ""
echo "=== Generating benchmark visualization ==="
uv run python scripts/generate-benchmark-viz.py

echo ""
echo "=== Generating benchmark markdown ==="
uv run python -m tests.eval.eval_harness > tests/eval/BENCHMARK.md

echo ""
echo "=== Recording demo ==="
if command -v asciinema &> /dev/null; then
  mkdir -p docs/assets
  asciinema rec docs/assets/demo.cast --command="bash scripts/record-demo.sh" --overwrite
  echo "Convert to GIF: agg docs/assets/demo.cast docs/assets/demo.gif"
else
  echo "Skip recording (install asciinema to enable)"
fi

echo ""
echo "Done. Artifacts regenerated."
echo ""
echo "NOTE: If benchmark numbers changed, update README.md too."
