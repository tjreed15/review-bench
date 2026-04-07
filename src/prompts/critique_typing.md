You are an expert at analyzing peer reviews. Your task is to classify the type of critique each comment makes.

## Critique Types

- **validity** — Is the reasoning sound? Concerns about logical errors, flawed arguments, incorrect conclusions, or methodological mistakes that undermine the correctness of the work.
- **sufficiency** — Is the evidence enough? Concerns about missing experiments, insufficient baselines, inadequate sample sizes, or lack of ablations needed to support the claims.
- **contribution** — Does the work matter? Concerns about novelty, significance, incremental contribution, or positioning relative to prior work.
- **clarity** — Can I understand it? Concerns about writing quality, unclear notation, poor figures, confusing organization, or missing definitions.
- **transparency** — Can I verify it? Concerns about reproducibility, missing details, unavailable code/data, or insufficient description of methods to allow replication.

## Instructions

For EACH comment, determine:

1. **comment_index**: The 1-based index of the comment.
2. **critique_type**: One of `"validity"`, `"sufficiency"`, `"contribution"`, `"clarity"`, `"transparency"`. Pick the PRIMARY type if a comment spans multiple categories.

## Rules

- Classify EVERY comment.
- If a comment is purely positive (e.g. "great paper"), classify based on what aspect it praises (e.g. clarity for "well written", contribution for "important work").
- Each comment gets exactly one critique type.

## Output Format

Return a JSON array with one entry per comment:

```json
[
  {
    "comment_index": 1,
    "critique_type": "validity"
  }
]
```

Return ONLY valid JSON, no other text.
