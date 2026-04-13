# ReviewBench: An Extensible Framework for Benchmarking Human and AI Manuscript Review

## Benchmark Design

```
  VenueRawDataFetchers       Canonicalization        InputGenerators       Core Benchmark Logic
 ┌─────────────────┐       ┌───────────────┐       ┌───────────────┐       ┌─────────────────┐
 │                 │       │               │       │               │       │                 │
 │    Venue 1      │──┐    │               │──────▶│ R3 Generator  │──┐    │                 │
 │  (e.g. ICLR)    │  │    │               │       │               │  │    │                 │
 └─────────────────┘  │    │   Parsers     │       └───────────────┘  │    │   Processor     │
                      ├───▶│               │                          ├───▶│                 │
       ...            │    │  raw_venue    │       ┌───────────────┐  │    │ extract_claims  │
                      │    │  ──▶ papers   │──────▶│    Control    │──┘    │ assess_comments │
 ┌─────────────────┐  │    │  ──▶ comments │       │   Generators  │       │  score          │
 │                 │  │    │               │       └───────────────┘       │                 │
 │    Venue n      │──┘    │               │                               │                 │
 │  (e.g. eLife)   │       │               │──── Human reviews ──────-────▶│                 │
 └─────────────────┘       └───────────────┘  (parsed into comments)       └─────────────────┘
```

### Pipeline Architecture

All data flows through Cloud SQL (PostgreSQL) via `src/db/queries.py` → `src/db/client.py` (psycopg, connected via `DATABASE_URL`).

| Step | File | Reads | Writes |
|------|------|-------|--------|
| **Fetch** | `src/fetchers/<venue>.py` | Venue API or local files | `raw_venue_data` |
| **Parse** | `src/parsers/<venue>.py` | `raw_venue_data` | `papers` + `comments` |
| **Extract claims** | `src/processor/extract_claims.py` | `papers` PDFs via Gemini | `claims` |
| **Assess comments** | `src/processor/assess_comments.py` | `comments` + `claims` + PDFs via Gemini context caching | `assessments` |
| **Score** | `src/processor/score.py` | `assessments` + `claims` | `results/` (stats CSV + figures) |

### Assessment Pipeline

Comment assessment uses three separate LLM calls per source per paper, each with a dedicated prompt. Claim extraction runs once per paper before assessment.

| Step | Prompt | Model | Temp | Input |
|------|--------|-------|------|-------|
| **Extract claims** | `src/prompts/extract_claims.md` | Gemini 3 Pro | 0 | Paper |
| **Comment parsing** | `src/prompts/comment_parser.md` | Gemini 3 Pro | 0 | Paper + comments |
| **Claim mapping** | `src/prompts/claim_mapping.md` | Gemini 3 Pro | 0 | Paper + comments + extracted claims |
| **Critique typing** | `src/prompts/critique_typing.md` | Gemini 3 Pro | 0 | Paper + comments |

### Scoring and Output

The `score` step orchestrates four modules that run after assessment:

| Module | File | Description |
|--------|------|--------------|
| **Metrics** | `src/processor/metrics.py` | Computes per-paper rates (mapped, consequential, specification, justification, etc.) and cross-source comparisons (claim overlap, stance-matched overlap) |
| **Statistics** | `src/processor/statistics.py` | Pairwise Wilcoxon signed-rank tests with Holm-Bonferroni correction, Shapiro-Wilk normality tests, bootstrap 95% CIs, Cohen's d, and Cohen's kappa |
| **Figures** | `src/processor/figures.py` | Generates all `.png` figures, organized by paper section (1-7) |
| **Score** | `src/processor/score.py` | Orchestrator that runs metrics, statistics, and figures for each venue |

All output is written to `results/` (figures and per-venue stats CSVs).

#### Data Accessibility

The benchmark database is hosted on Cloud SQL (PostgreSQL) and is publicly accessible with read-only credentials:

```
Host:     34.28.98.243
Port:     5432
Database: reviewbench
User:     user
Password: public
```

Connect with any PostgreSQL client (e.g. `psql`, DBeaver, TablePlus):

```bash
psql postgresql://user:public@34.28.98.243:5432/reviewbench
```

### Extensibility

The system is designed for multi-venue evaluation. Adding a new venue requires only writing a fetcher (to dump raw API data) and a parser (to extract papers and comments into canonical tables). The generators, processor, and scoring pipeline operate on the canonical schema and require no modification.

## Contributing

Contributions are welcome! Please see [`CONTRIBUTING.md`](CONTRIBUTING.md) for setup instructions, guidelines, and the pull request workflow.
