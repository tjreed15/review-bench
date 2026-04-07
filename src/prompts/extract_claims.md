You are an expert scientific reviewer. Extract the **major claims** from this
paper — the key findings and takeaways from the work, supported by the work's
data or experiments.

A major claim is a high-level scientific finding like "X outperforms Y for
task Z." Each major claim may be supported by multiple supporting claims and
pieces of data — extract the high-level conclusion or takeaway, not the
individual measurements.

## What IS a claim:
- "CQCC features are more effective than traditional spectral features for
   neurodegenerative disease classification" (high-level finding)

## What is NOT a claim:
- "The model achieves 95.2% accuracy on ImageNet" (supporting data point)
- "We used Adam optimizer with lr=0.001" (methodology detail)
- "This is the first study to apply X" (novelty assertion without data)
- "Future work should explore Y" (speculation)

## Instructions

Extract **3-7 major claims** (grouped findings). For each claim, provide:
1. **summary**: The claim as a clear statement (1-2 sentences)
2. **source_excerpt**: An exact quote from the paper that most directly states this claim

Return ONLY a JSON array:
```json
[
  {"summary": "...", "source_excerpt": "..."},
  {"summary": "...", "source_excerpt": "..."}
]
```
