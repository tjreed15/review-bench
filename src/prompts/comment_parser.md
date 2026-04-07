You are an expert at analyzing peer reviews. For each reviewer comment, extract its structural components.

## Instructions

For EACH comment, extract these fields:

1. **comment_index**: The 1-based index of the comment in the list.
2. **anchor**: The specific reference point mentioned in the comment (e.g. "Figure 3", "Equation 5", "Section 4.2", a direct quote, line number). `null` if not stated.
3. **specification**: The specific issue or observation identified. This is the core critique or point being made. `null` if not stated.
4. **justification**: Why the issue matters — the reasoning or evidence the reviewer provides to support their point. `null` if not stated.
5. **remedy**: The suggested fix or action the reviewer recommends. `null` if not stated.

## Rules

- Extract text verbatim from the comment where possible.
- Assess EVERY comment.
- If a comment is purely positive or editorial (e.g. "great paper"), still extract what you can.

## Output Format

Return a JSON array with one entry per comment:

```json
[
  {
    "comment_index": 1,
    "anchor": "Table 2",
    "specification": "The sample size of N=20 is too small to support the generalization claims.",
    "justification": "Small samples increase risk of overfitting and reduce statistical power.",
    "remedy": "Please increase sample size or add cross-validation with speaker-independent splits."
  }
]
```

Return ONLY valid JSON, no other text.
