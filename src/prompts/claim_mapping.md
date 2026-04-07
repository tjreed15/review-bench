You are an expert at analyzing peer reviews. Your task is to map each reviewer comment to the paper's claims.

## Instructions

For EACH comment, determine:

1. **comment_index**: The 1-based index of the comment.
2. **claim_id**: The ID of the single most relevant claim this comment addresses. For indirect references, use the PDF to resolve which claim is targeted. For example: "Figure 1 is wrong" → look up Figure 1 in the PDF, find which claim it provides evidence for, map to that claim.
   - `null` if the comment does not target a single specific claim (e.g. editorial comments like "there is a typo", or broad comments like "the paper is not novel").
3. **stance**: How does this comment evaluate the claim?
   - `"SUPPORTIVE"` — reviewer explicitly agrees with or endorses the claim
   - `"CRITICAL"` — reviewer critiques, questions, or expresses doubt about the claim
   - `"NEUTRAL"` — reviewer mentions the claim without expressing agreement or disagreement
   - `null` if claim_id is `null`
4. **is_consequential**: Does the issue raised have the potential to undermine the claim?
   - `true` — yes
   - `false` — no
   - `null` if claim_id is `null`

## Rules

- Assess EVERY comment.
- Be objective: assess what the reviewer is saying, not whether they are correct.
- Each field must have exactly one value. If a comment spans multiple claims, pick the primary one.

## Output Format

Return a JSON array with one entry per comment:

```json
[
  {
    "comment_index": 1,
    "claim_id": "paper-id:claim-1",
    "stance": "CRITICAL",
    "is_consequential": true
  }
]
```

Return ONLY valid JSON, no other text.
