# Eval Results: RAG vs Keyword (LIKE) Retrieval

## Aggregate Metrics

| Metric | RAG | Keyword (LIKE) |
|--------|-----|----------------|
| Recall@5 | 0.92 | 0.76 |
| MRR | 0.90 | 0.76 |
| Groundedness | 0.86 | 0.80 |
| LLM-Judge Groundedness | 0.71 | 0.65 |

## By Query Type

| Query Type | Count | Recall RAG | Recall LIKE | MRR RAG | MRR LIKE |
|------------|-------|------------|-------------|---------|----------|
| exact_match | 5 | 1.00 | 1.00 | 1.00 | 1.00 |
| multi_concept | 5 | 0.83 | 0.73 | 0.84 | 0.90 |
| paraphrase | 5 | 1.00 | 0.60 | 0.77 | 0.44 |
| synonym | 5 | 0.83 | 0.70 | 1.00 | 0.70 |

## Side-by-Side Examples

### q7: What makes products easy to use without reading instructions?
*Type: paraphrase | Recall gap: +1.00*

**RAG returns:** App Idea: Recipe Ingredient Tracker, The Design of Everyday Things - Summary, Road Trip Planning Checklist, Atomic Habits - Key Takeaways, Thinking Fast and Slow - Reading Notes
**Keyword returns:** Atomic Habits - Key Takeaways, Code Review Checklist, Budget Backpacking Southeast Asia, Hiking the Pacific Crest Trail, Thinking Fast and Slow - Reading Notes

### q10: How should I write software interfaces that other developers will enjoy using?
*Type: paraphrase | Recall gap: +1.00*

**RAG returns:** The Pragmatic Programmer - Notes, Deploying Python Apps to Production, API Design Best Practices, Learning Rust - Week 3, Code Review Checklist
**Keyword returns:** The Design of Everyday Things - Summary, Atomic Habits - Key Takeaways, Thai Green Curry Recipe, Thinking Fast and Slow - Reading Notes, Deep Work - Reflections

### q12: How can I track my spending on food and groceries?
*Type: multi_concept | Recall gap: +0.67*

**RAG returns:** Weekly Reflection - January 15, App Idea: Recipe Ingredient Tracker, Meal Prep for Busy Weeks, Road Trip Planning Checklist, Deploying Python Apps to Production
**Keyword returns:** Weekly Reflection - January 15, Atomic Habits - Key Takeaways, Garden Project Planning, Fermented Foods Guide, Budget Backpacking Southeast Asia
