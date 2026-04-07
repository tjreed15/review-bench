"""OpenReview parser: raw_venue_data → papers + comments."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from src.db.client import get_conn
from src.lib.comment_parser import split_review_into_comments


def _val(content: dict, key: str):
    """Extract .value from an OpenReview content field."""
    entry = content.get(key)
    if isinstance(entry, dict):
        return entry.get("value")
    return None


def _clean_review_text(text: str) -> str:
    text = text.replace("\r\n", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _build_review_markdown(content: dict) -> str:
    """Build markdown from review content fields."""
    parts: list[str] = []
    if _val(content, "summary"):
        parts.append(f"## Summary\n{_val(content, 'summary')}")
    if _val(content, "strengths"):
        parts.append(f"## Strengths\n{_val(content, 'strengths')}")
    if _val(content, "weaknesses"):
        parts.append(f"## Weaknesses\n{_val(content, 'weaknesses')}")
    if _val(content, "questions"):
        parts.append(f"## Questions\n{_val(content, 'questions')}")
    if _val(content, "review"):
        parts.append(_val(content, "review"))

    return "\n\n".join(parts) if parts else ""


class OpenReviewParser:
    venue = "iclr-2025"

    def parse(self, limit: int | None = None) -> int:
        """Parse raw OpenReview data into papers + comments.

        Uses a single connection with server-side cursor to avoid
        loading all JSONB payloads into memory at once.
        """
        parsed_count = 0

        with get_conn() as conn:
            # Use a named cursor for server-side iteration
            sql = "SELECT source_id, raw_payload FROM raw_venue_data WHERE venue_id = %s ORDER BY source_id"
            params = (self.venue,)
            if limit:
                sql += " LIMIT %s"
                params = (self.venue, limit)

            cur = conn.execute(sql, params)

            for row in cur:
                source_id, payload = row[0], row[1]
                if isinstance(payload, str):
                    payload = json.loads(payload)

                submission = payload.get("submission", {})
                reviews = payload.get("reviews", [])
                decision = payload.get("decision", "unknown")

                content = submission.get("content", {})
                sid = submission.get("id", source_id)
                title = _val(content, "title")
                if not title:
                    continue

                paper_id = f"iclr-2025-{sid}"

                # Extract PDF URL
                pdf_val = _val(content, "pdf")
                pdf_url = None
                if pdf_val:
                    pdf_url = pdf_val if pdf_val.startswith("http") else f"https://openreview.net{pdf_val}"

                # Extract year
                year = None
                cdate = submission.get("cdate")
                if cdate:
                    year = datetime.fromtimestamp(cdate / 1000, tz=timezone.utc).year

                # Extract rating and confidence for metadata
                review_ratings = []
                review_confidences = []
                for review in reviews:
                    rc = review.get("content", {})
                    rating_raw = _val(rc, "rating")
                    if rating_raw:
                        m = re.search(r"(\d+)", str(rating_raw))
                        if m:
                            review_ratings.append(int(m.group(1)))
                    conf_raw = _val(rc, "confidence")
                    if conf_raw:
                        m = re.search(r"(\d+)", str(conf_raw))
                        if m:
                            review_confidences.append(int(m.group(1)))

                metadata = {
                    "primary_area": _val(content, "primary_area"),
                    "keywords": _val(content, "keywords"),
                    "review_count": len(reviews),
                }
                if review_ratings:
                    metadata["avg_rating"] = sum(review_ratings) / len(review_ratings)
                    metadata["ratings"] = review_ratings
                if review_confidences:
                    metadata["avg_confidence"] = sum(review_confidences) / len(review_confidences)

                # Upsert paper
                conn.execute(
                    """INSERT INTO papers (id, venue_id, source_id, title, abstract, authors, pdf_url, decision, year, metadata)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                       ON CONFLICT (venue_id, source_id) DO UPDATE SET
                         title = EXCLUDED.title, abstract = EXCLUDED.abstract,
                         authors = EXCLUDED.authors, pdf_url = EXCLUDED.pdf_url,
                         decision = EXCLUDED.decision, year = EXCLUDED.year,
                         metadata = EXCLUDED.metadata""",
                    (paper_id, self.venue, sid, title, _val(content, "abstract"),
                     _val(content, "authors"), pdf_url, decision, year,
                     json.dumps(metadata)),
                )

                # Parse reviews into individual comments
                comment_index = 0
                for ri, review in enumerate(reviews):
                    rc = review.get("content", {})
                    review_text = _build_review_markdown(rc)
                    if not review_text:
                        continue

                    cleaned = _clean_review_text(review_text)

                    comments = split_review_into_comments(cleaned)

                    for text in comments:
                        comment_index += 1
                        conn.execute(
                            """INSERT INTO comments (id, paper_id, source, reviewer_id, content)
                               VALUES (%s, %s, %s, %s, %s)
                               ON CONFLICT (id) DO NOTHING""",
                            (f"{paper_id}:human-{comment_index}", paper_id, "human",
                             f"reviewer-{ri + 1}", text),
                        )

                parsed_count += 1
                title_preview = title[:60] if title else "Unknown"
                print(f"[{parsed_count}] {paper_id}: {title_preview}... ({comment_index} comments)", flush=True)

        print(f"\nParsed {parsed_count} papers for {self.venue}")
        return parsed_count
