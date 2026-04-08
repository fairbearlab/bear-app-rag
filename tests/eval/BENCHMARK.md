# Eval Results: RAG vs Keyword (LIKE) Retrieval

## Aggregate Metrics

| Metric | RAG | Keyword (LIKE) |
|--------|-----|----------------|
| Recall@5 | 0.92 | 0.65 |
| MRR | 0.90 | 0.65 |
| Groundedness | 0.86 | 0.71 |

## By Query Type

| Query Type | Count | Recall RAG | Recall LIKE | MRR RAG | MRR LIKE |
|------------|-------|------------|-------------|---------|----------|
| exact_match | 5 | 1.00 | 1.00 | 1.00 | 1.00 |
| multi_concept | 5 | 0.83 | 0.50 | 0.84 | 0.70 |
| paraphrase | 5 | 1.00 | 0.40 | 0.77 | 0.30 |
| synonym | 5 | 0.83 | 0.70 | 1.00 | 0.60 |

## Side-by-Side Examples

### q6: How do our minds take shortcuts when making choices?
*Type: paraphrase | Recall gap: +1.00*

**RAG returns:** Thinking Fast and Slow - Reading Notes, Deep Work - Reflections, Atomic Habits - Key Takeaways, The Design of Everyday Things - Summary
**Keyword returns:** Sourdough Bread Baking, Meal Prep for Busy Weeks, Fermented Foods Guide, Digital Nomad Setup in Lisbon, Atomic Habits - Key Takeaways

### q7: What makes products easy to use without reading instructions?
*Type: paraphrase | Recall gap: +1.00*

**RAG returns:** App Idea: Recipe Ingredient Tracker, The Design of Everyday Things - Summary, Road Trip Planning Checklist, Atomic Habits - Key Takeaways, Thinking Fast and Slow - Reading Notes
**Keyword returns:** Atomic Habits - Key Takeaways, Code Review Checklist, Budget Backpacking Southeast Asia, Hiking the Pacific Crest Trail, Thinking Fast and Slow - Reading Notes

### q10: How should I write software interfaces that other developers will enjoy using?
*Type: paraphrase | Recall gap: +1.00*

**RAG returns:** The Pragmatic Programmer - Notes, Deploying Python Apps to Production, API Design Best Practices, Learning Rust - Week 3, Code Review Checklist
**Keyword returns:** Atomic Habits - Key Takeaways, Thinking Fast and Slow - Reading Notes, The Design of Everyday Things - Summary, Deep Work - Reflections, The Pragmatic Programmer - Notes
