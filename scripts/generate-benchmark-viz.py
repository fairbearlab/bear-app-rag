"""Generate static SVG benchmark visualization from results.json.

Reads tests/eval/results.json and outputs docs/benchmarks/index.html
with inline SVG bar charts comparing RAG vs LIKE retrieval.
"""

import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_RESULTS = _ROOT / "tests" / "eval" / "results.json"
_OUTPUT = _ROOT / "docs" / "benchmarks" / "index.html"


def _bar_chart_svg(
    title: str,
    labels: list[str],
    rag_values: list[float],
    like_values: list[float],
    width: int = 600,
    bar_height: int = 28,
    gap: int = 12,
    group_gap: int = 24,
) -> str:
    """Generate a grouped horizontal bar chart as inline SVG."""
    chart_left = 140
    chart_width = width - chart_left - 60
    n = len(labels)
    group_height = 2 * bar_height + gap
    total_height = n * group_height + (n - 1) * group_gap + 60

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {total_height}" '
        f'width="{width}" height="{total_height}" role="img" aria-label="{title}">'
    ]
    lines.append(f'<title>{title}</title>')
    lines.append('<style>')
    lines.append('  text { font-family: system-ui, -apple-system, sans-serif; font-size: 13px; }')
    lines.append('  .title { font-size: 16px; font-weight: 600; }')
    lines.append('  .label { font-size: 13px; fill: #374151; }')
    lines.append('  .value { font-size: 12px; fill: #374151; font-weight: 500; }')
    lines.append('  .bar-rag { fill: #3b82f6; }')
    lines.append('  .bar-like { fill: #94a3b8; }')
    lines.append('  @media (prefers-color-scheme: dark) {')
    lines.append('    .label, .value, .title { fill: #e5e7eb; }')
    lines.append('    .bar-rag { fill: #60a5fa; }')
    lines.append('    .bar-like { fill: #64748b; }')
    lines.append('  }')
    lines.append('</style>')

    lines.append(f'<text x="{width // 2}" y="20" text-anchor="middle" class="title">{title}</text>')

    y_offset = 44
    for i, label in enumerate(labels):
        y = y_offset + i * (group_height + group_gap)
        label_y = y + bar_height + gap // 2

        lines.append(f'<text x="{chart_left - 8}" y="{label_y}" text-anchor="end" class="label">{label}</text>')

        rag_w = max(1, rag_values[i] * chart_width)
        like_w = max(1, like_values[i] * chart_width)

        lines.append(f'<rect x="{chart_left}" y="{y}" width="{rag_w:.1f}" height="{bar_height}" '
                      f'rx="3" class="bar-rag"/>')
        lines.append(f'<text x="{chart_left + rag_w + 6:.1f}" y="{y + bar_height - 8}" '
                      f'class="value">{rag_values[i]:.2f}</text>')

        like_y = y + bar_height + gap
        lines.append(f'<rect x="{chart_left}" y="{like_y}" width="{like_w:.1f}" height="{bar_height}" '
                      f'rx="3" class="bar-like"/>')
        lines.append(f'<text x="{chart_left + like_w + 6:.1f}" y="{like_y + bar_height - 8}" '
                      f'class="value">{like_values[i]:.2f}</text>')

    # Legend
    ly = total_height - 14
    lines.append(f'<rect x="{chart_left}" y="{ly - 10}" width="14" height="14" rx="2" class="bar-rag"/>')
    lines.append(f'<text x="{chart_left + 20}" y="{ly + 1}" class="label">RAG</text>')
    lines.append(f'<rect x="{chart_left + 70}" y="{ly - 10}" width="14" height="14" rx="2" class="bar-like"/>')
    lines.append(f'<text x="{chart_left + 90}" y="{ly + 1}" class="label">Keyword (LIKE)</text>')

    lines.append('</svg>')
    return '\n'.join(lines)


def generate() -> str:
    data = json.loads(_RESULTS.read_text())
    agg = data["aggregates"]
    overall = agg["overall"]
    by_type = agg["by_type"]
    query_count = len(data["queries"])
    type_count = len(by_type)

    # Chart 1: Recall@5 by query type
    types = sorted(by_type.keys())
    type_labels = [t.replace("_", " ").title() for t in types]
    recall_rag = [by_type[t]["recall_semantic"] for t in types]
    recall_like = [by_type[t]["recall_like"] for t in types]
    chart1 = _bar_chart_svg("Recall@5 by Query Type", type_labels, recall_rag, recall_like)

    # Chart 2: MRR by query type
    mrr_rag = [by_type[t]["mrr_semantic"] for t in types]
    mrr_like = [by_type[t]["mrr_like"] for t in types]
    chart2 = _bar_chart_svg("MRR by Query Type", type_labels, mrr_rag, mrr_like)

    # Chart 3: Overall metrics
    metric_labels = ["Recall@5", "MRR", "Groundedness"]
    overall_rag = [overall["recall_semantic"], overall["mrr_semantic"], overall["groundedness_semantic"]]
    overall_like = [overall["recall_like"], overall["mrr_like"], overall["groundedness_like"]]
    # LLM-judge groundedness is only present when the eval ran with EVAL_LLM_JUDGE=1.
    if "llm_judge_semantic" in overall:
        metric_labels.append("LLM-Judge")
        overall_rag.append(overall["llm_judge_semantic"])
        overall_like.append(overall["llm_judge_like"])
    chart3 = _bar_chart_svg("Overall Metrics", metric_labels, overall_rag, overall_like)

    html = f"""---
layout: null
---
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>bear-app-rag Benchmark Results</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400&display=swap">
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: system-ui, -apple-system, sans-serif;
    max-width: 760px;
    margin: 0 auto;
    padding: 2rem 1rem;
    color: #1f2937;
    background: #fff;
  }}
  @media (prefers-color-scheme: dark) {{
    body {{ color: #e5e7eb; background: #111827; }}
    a {{ color: #60a5fa; }}
    .summary {{ background: #1f2937; border-color: #374151; }}
  }}
  h1 {{ font-size: 1.5rem; margin-bottom: 0.5rem; }}
  p {{ line-height: 1.6; margin-bottom: 1rem; color: #4b5563; }}
  @media (prefers-color-scheme: dark) {{ p {{ color: #9ca3af; }} }}
  .chart {{ margin: 2rem 0; }}
  svg {{ max-width: 100%; height: auto; }}
  .summary {{
    background: #f9fafb;
    border: 1px solid #e5e7eb;
    border-radius: 8px;
    padding: 1rem 1.5rem;
    margin: 1.5rem 0;
  }}
  .summary p {{ margin-bottom: 0.5rem; }}
  a {{ color: #3b82f6; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  code {{
    font-family: "IBM Plex Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 0.875em;
    background: #f7f2ea;
    border-radius: 4px;
    padding: 1px 5px;
    overflow-wrap: anywhere;
  }}
  @media (prefers-color-scheme: dark) {{
    code {{ background: #1f2937; }}
  }}
</style>
</head>
<body>
<h1>bear-app-rag Benchmark Results</h1>
<p>
  Semantic vs keyword (SQLite LIKE) retrieval on a 25-note synthetic corpus
  with {query_count} eval queries across {type_count} query types.
</p>

<div class="summary">
  <p><strong>Key finding:</strong> Semantic search improves recall by
  0.40 on paraphrase queries and 0.13 on synonym queries.
  Exact-match recall ties at 1.00; the multi-concept group favors semantic
  recall and keyword first-hit rank.</p>
</div>

<div class="chart">
{chart1}
</div>

<div class="chart">
{chart2}
</div>

<div class="chart">
{chart3}
</div>

<p>
  Data source: <code>tests/eval/results.json</code>.
  Reproduce with <code>uv run pytest -m eval -v</code>.
</p>
<p>
  <a href="../BUILDING.html">Read the full story</a> |
  <a href="../ARCHITECTURE.html">Architecture tour</a> |
  <a href="https://github.com/fairbearlab/bear-app-rag">Source code</a>
</p>
</body>
</html>"""

    return html


if __name__ == "__main__":
    _OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    html = generate()
    _OUTPUT.write_text(html)
    print(f"Written to {_OUTPUT}")
