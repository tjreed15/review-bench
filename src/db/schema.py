"""Database schema"""

from src.db.client import get_conn

SCHEMA_SQL = """
-- Raw venue data: full API responses dumped as-is
CREATE TABLE IF NOT EXISTS raw_venue_data (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  venue_id      TEXT NOT NULL,
  source_id     TEXT NOT NULL,
  raw_payload   JSONB NOT NULL,
  UNIQUE(venue_id, source_id)
);

-- Canonical papers
CREATE TABLE IF NOT EXISTS papers (
  id            TEXT PRIMARY KEY,
  venue_id      TEXT NOT NULL,
  source_id     TEXT NOT NULL,
  title         TEXT NOT NULL,
  abstract      TEXT,
  authors       TEXT[],
  pdf_url       TEXT,            -- venues with hosted PDFs (e.g. NHB)
  manuscript_text TEXT,          -- venues without PDFs that provide raw text (e.g. eLife)
  decision      TEXT CHECK (decision IN ('accepted', 'rejected', 'unknown')),
  year          INTEGER,
  metadata      JSONB,
  UNIQUE(venue_id, source_id)
);

-- Individual comments
CREATE TABLE IF NOT EXISTS comments (
  id            TEXT PRIMARY KEY,
  paper_id      TEXT NOT NULL REFERENCES papers(id),
  source        TEXT NOT NULL CHECK (source IN ('human', 'r3', 'gemini-3-pro', 'gpt-5.2')),
  reviewer_id   TEXT,
  content       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_comments_paper_source ON comments(paper_id, source);

-- Claims: major findings extracted from papers
CREATE TABLE IF NOT EXISTS claims (
  id              TEXT PRIMARY KEY,
  paper_id        TEXT NOT NULL REFERENCES papers(id),
  summary         TEXT NOT NULL,
  source_excerpt  TEXT
);
CREATE INDEX IF NOT EXISTS idx_claims_paper ON claims(paper_id);

-- Comment assessments
CREATE TABLE IF NOT EXISTS assessments (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  paper_id          TEXT NOT NULL REFERENCES papers(id),
  comment_id        TEXT NOT NULL REFERENCES comments(id),
  source            TEXT NOT NULL CHECK (source IN ('human', 'r3', 'gemini-3-pro', 'gpt-5.2')),
  claim_id          TEXT REFERENCES claims(id),
  stance            TEXT CHECK (stance IN ('SUPPORTIVE', 'CRITICAL', 'NEUTRAL')),
  is_consequential  BOOLEAN,
  anchor            TEXT,
  specification     TEXT,
  justification     TEXT,
  remedy            TEXT,
  critique_type     TEXT CHECK (critique_type IS NULL OR critique_type IN (
    'validity', 'sufficiency', 'contribution', 'clarity', 'transparency'
  ))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_assessments_comment_source ON assessments(comment_id, source);
CREATE INDEX IF NOT EXISTS idx_assessments_paper_source ON assessments(paper_id, source);
CREATE INDEX IF NOT EXISTS idx_assessments_claim ON assessments(claim_id);

"""


def migrate() -> None:
    """Create all tables."""
    with get_conn() as conn:
        conn.execute(SCHEMA_SQL)
    print("Database migration complete.")
