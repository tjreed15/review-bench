"""Typed query functions for all database operations."""

from __future__ import annotations

import json
from typing import Any

from src.db.client import get_conn, fetch_all, fetch_one


# ---------------------------------------------------------------------------
# raw_venue_data
# ---------------------------------------------------------------------------

def upsert_raw_venue_data(venue_id: str, source_id: str, raw_payload: dict) -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO raw_venue_data (venue_id, source_id, raw_payload)
               VALUES (%s, %s, %s::jsonb)
               ON CONFLICT (venue_id, source_id) DO UPDATE SET
                 raw_payload = EXCLUDED.raw_payload""",
            (venue_id, source_id, json.dumps(raw_payload)),
        )



def get_raw_source_ids(venue_id: str) -> set[str]:
    rows = fetch_all("SELECT source_id FROM raw_venue_data WHERE venue_id = %s", (venue_id,))
    return {r["source_id"] for r in rows}




# ---------------------------------------------------------------------------
# papers
# ---------------------------------------------------------------------------


def get_papers(venue_id: str | None = None, limit: int | None = None) -> list[dict]:
    sql = "SELECT * FROM papers"
    params: list[Any] = []
    if venue_id:
        sql += " WHERE venue_id = %s"
        params.append(venue_id)
    sql += " ORDER BY id"
    if limit:
        sql += " LIMIT %s"
        params.append(limit)
    return fetch_all(sql, tuple(params))


def get_paper(paper_id: str) -> dict | None:
    return fetch_one("SELECT * FROM papers WHERE id = %s", (paper_id,))



# ---------------------------------------------------------------------------
# comments
# ---------------------------------------------------------------------------


def insert_comments_batch(comments: list[dict]) -> None:
    """Insert multiple comments in a single transaction (all-or-nothing)."""
    if not comments:
        return
    with get_conn() as conn:
        for c in comments:
            conn.execute(
                """INSERT INTO comments (id, paper_id, source, reviewer_id, content)
                   VALUES (%s, %s, %s, %s, %s)
                   ON CONFLICT (id) DO NOTHING""",
                (c["id"], c["paper_id"], c["source"], c.get("reviewer_id"), c["content"]),
            )


def get_comments(paper_id: str, source: str | None = None) -> list[dict]:
    if source:
        return fetch_all(
            "SELECT * FROM comments WHERE paper_id = %s AND source = %s ORDER BY id",
            (paper_id, source),
        )
    return fetch_all("SELECT * FROM comments WHERE paper_id = %s ORDER BY id", (paper_id,))


def delete_comments(paper_id: str, source: str) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM comments WHERE paper_id = %s AND source = %s", (paper_id, source))


def count_comments(paper_id: str, source: str | None = None) -> int:
    if source:
        row = fetch_one(
            "SELECT COUNT(*) as cnt FROM comments WHERE paper_id = %s AND source = %s",
            (paper_id, source),
        )
    else:
        row = fetch_one("SELECT COUNT(*) as cnt FROM comments WHERE paper_id = %s", (paper_id,))
    return row["cnt"] if row else 0


# ---------------------------------------------------------------------------
# claims
# ---------------------------------------------------------------------------


def insert_claims_batch(claims: list[dict]) -> None:
    """Insert multiple claims in a single transaction (all-or-nothing)."""
    if not claims:
        return
    with get_conn() as conn:
        for c in claims:
            conn.execute(
                """INSERT INTO claims (id, paper_id, summary, source_excerpt) VALUES (%s, %s, %s, %s)
                   ON CONFLICT (id) DO NOTHING""",
                (c["id"], c["paper_id"], c["summary"], c.get("source_excerpt")),
            )


def get_claims(paper_id: str) -> list[dict]:
    return fetch_all("SELECT * FROM claims WHERE paper_id = %s ORDER BY id", (paper_id,))


def delete_claims(paper_id: str) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM claims WHERE paper_id = %s", (paper_id,))


def get_papers_with_claims() -> list[str]:
    """Get paper IDs that have claims extracted."""
    rows = fetch_all("SELECT DISTINCT paper_id FROM claims ORDER BY paper_id")
    return [r["paper_id"] for r in rows]


# ---------------------------------------------------------------------------
# assessments
# ---------------------------------------------------------------------------

def insert_assessment(
    paper_id: str,
    comment_id: str,
    source: str,
    claim_id: str | None = None,
    stance: str | None = None,
    is_consequential: bool | None = None,
    anchor: str | None = None,
    specification: str | None = None,
    justification: str | None = None,
    remedy: str | None = None,
    critique_type: str | None = None,
) -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO assessments
               (paper_id, comment_id, source, claim_id, stance,
                is_consequential, anchor, specification, justification, remedy, critique_type)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (comment_id, source) DO NOTHING""",
            (paper_id, comment_id, source, claim_id, stance,
             is_consequential, anchor, specification, justification, remedy, critique_type),
        )



def delete_assessments(paper_id: str, source: str | None = None) -> None:
    with get_conn() as conn:
        if source:
            conn.execute("DELETE FROM assessments WHERE paper_id = %s AND source = %s", (paper_id, source))
        else:
            conn.execute("DELETE FROM assessments WHERE paper_id = %s", (paper_id,))


def get_assessed_comment_ids(paper_id: str, source: str) -> set[str]:
    rows = fetch_all(
        "SELECT DISTINCT comment_id FROM assessments WHERE paper_id = %s AND source = %s",
        (paper_id, source),
    )
    return {r["comment_id"] for r in rows}


def get_fully_assessed_paper_ids(sources: list[str]) -> set[str]:
    """Return paper IDs where every comment (for the given sources) has been assessed."""
    if not sources:
        return set()
    placeholders = ",".join(["%s"] * len(sources))

    comment_counts = {
        r["paper_id"]: r["cnt"]
        for r in fetch_all(
            f"SELECT paper_id, COUNT(*) AS cnt FROM comments WHERE source IN ({placeholders}) GROUP BY paper_id",
            tuple(sources),
        )
    }
    assessed_counts = {
        r["paper_id"]: r["cnt"]
        for r in fetch_all(
            f"SELECT paper_id, COUNT(DISTINCT comment_id) AS cnt FROM assessments WHERE source IN ({placeholders}) GROUP BY paper_id",
            tuple(sources),
        )
    }

    return {
        pid for pid, total in comment_counts.items()
        if assessed_counts.get(pid, 0) >= total
    }
