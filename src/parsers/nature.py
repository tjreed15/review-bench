"""Nature Human Behaviour parser: raw_venue_data → papers + comments.

Parses the stored JSON-LD metadata, article body, and extracted peer
review PDF text into the papers and comments tables.
"""

from __future__ import annotations

import json
import re

from src.db.client import get_conn
from src.lib.comment_parser import split_section_into_comments, MIN_COMMENT_LENGTH


def _extract_first_round(pr_text: str) -> str:
    """Extract only the first round of review (Version 0) from the PDF text.

    Nature peer review PDFs are structured as:
        Version 0: Decision Letter … Reviewer remarks …
        Version 1: Decision Letter … (second round) …
        ...

    Keep everything from "Version 0:" up to (but not including) "Version 1:".
    If no version markers are found, return the full text.
    """
    version_pattern = re.compile(r"\nVersion\s+(\d+)\s*:\s*\n", re.IGNORECASE)
    matches = list(version_pattern.finditer(pr_text))

    if not matches:
        # If no Version markers, cut before author response/rebuttal section
        response_cut = re.search(
            r"(?:Response to Review|Authors?.{0,10}Response|Rebuttal)",
            pr_text,
            re.IGNORECASE,
        )
        if response_cut:
            return pr_text[:response_cut.start()].strip()
        return pr_text

    # Find Version 0 start and end
    v0_match = None
    next_version_start = None
    for m in matches:
        ver = int(m.group(1))
        if ver == 0:
            v0_match = m
        elif ver > 0 and v0_match is not None and next_version_start is None:
            next_version_start = m.start()

    if v0_match is None:
        # If no explicit Version 0 label, take everything before Version 1
        for m in matches:
            if int(m.group(1)) > 0:
                return pr_text[:m.start()].strip()
        return pr_text

    start = v0_match.end()
    end = next_version_start if next_version_start is not None else len(pr_text)
    first_round = pr_text[start:end].strip()

    # Cut before author response if present
    response_cut = re.search(
        r"(?:Response to Review|Authors?.{0,10}Response|Rebuttal)",
        first_round,
        re.IGNORECASE,
    )
    if response_cut:
        first_round = first_round[:response_cut.start()].strip()

    return first_round


def _strip_decision_letter(text: str) -> str:
    """Remove the editorial decision letter preamble, keeping only reviewer remarks.

    Looks for "Reviewer #N (Remarks …):" or "Reviewer #N:" at the start
    of a line, which signals the beginning of actual reviewer text.

    If no proper heading is found, returns empty string so the paper
    produces zero comments rather than editor boilerplate.
    """
    # Match line-initial reviewer headings:
    #   "Reviewer #1 (Remarks to the Author):"
    #   "Reviewer #2:"
    #   "Reviewer #1: interpersonal relationships, ..."
    reviewer_start = re.search(
        r"\n\s*Reviewer\s+#?\s*\d+\s*(?:\([^)]*\)\s*)?:",
        text,
        re.IGNORECASE,
    )
    if reviewer_start:
        return text[reviewer_start.start():].strip()
    return ""


def _split_into_reviewer_reports(pr_text: str) -> list[tuple[str, str]]:
    """Split peer review PDF text into individual reviewer reports.

    Only uses the first round of review.  Strips the decision letter
    preamble and splits on "Reviewer #N" / "Referee #N" headings.

    Returns list of (reviewer_id, report_text) tuples.
    """
    first_round = _extract_first_round(pr_text)
    first_round = _strip_decision_letter(first_round)

    # Split on reviewer headings
    pattern = re.compile(
        r"(?:^|\n)\s*"
        r"(?:Reviewer|Referee)\s*"
        r"#?\s*(\d+)"
        r"[^:\n]*:\s*\n",
        re.IGNORECASE,
    )

    splits = list(pattern.finditer(first_round))

    if not splits:
        if not first_round.strip():
            return []
        # Fallback: treat the whole first round as a single report
        return [("reviewer-1", first_round.strip())]

    reports = []
    for i, match in enumerate(splits):
        reviewer_num = match.group(1)
        start = match.end()
        end = splits[i + 1].start() if i + 1 < len(splits) else len(first_round)
        text = first_round[start:end].strip()
        if text:
            reports.append((f"reviewer-{reviewer_num}", text))

    return reports


def _extract_authors(jsonld: dict) -> list[str]:
    """Extract author names from JSON-LD."""
    authors_raw = jsonld.get("author", [])
    names = []
    for a in authors_raw:
        if isinstance(a, dict):
            name = a.get("name", "")
            if not name:
                parts = []
                if a.get("givenName"):
                    parts.append(a["givenName"])
                if a.get("familyName"):
                    parts.append(a["familyName"])
                name = " ".join(parts)
            if name:
                names.append(name)
        elif isinstance(a, str):
            names.append(a)
    return names


def _extract_year(jsonld: dict) -> int | None:
    """Extract publication year from JSON-LD."""
    for field in ("datePublished", "dateModified"):
        val = jsonld.get(field, "")
        if val:
            m = re.match(r"(\d{4})", str(val))
            if m:
                return int(m.group(1))
    return None


def _extract_doi(jsonld: dict) -> str | None:
    """Extract DOI from JSON-LD sameAs or @id fields."""
    for field in ("sameAs", "@id", "url"):
        val = jsonld.get(field, "")
        if isinstance(val, str) and "doi.org" in val:
            return val
    return None


class NatureHumanBehaviourParser:
    venue = "nhb"

    def parse(self, limit: int | None = None) -> int:
        parsed_count = 0

        with get_conn() as conn:
            sql = "SELECT source_id, raw_payload FROM raw_venue_data WHERE venue_id = %s ORDER BY source_id"
            params: tuple = (self.venue,)
            if limit:
                sql += " LIMIT %s"
                params = (self.venue, limit)

            cur = conn.execute(sql, params)

            for row in cur:
                source_id, payload = row[0], row[1]
                if isinstance(payload, str):
                    payload = json.loads(payload)

                jsonld = payload.get("jsonld", {})
                pr_text = payload.get("peer_review_text", "")
                article_url = payload.get("article_url", "")
                pdf_url = f"{article_url}.pdf" if article_url else None

                title = jsonld.get("headline", "")
                if not title:
                    continue

                paper_id = f"nhb-{source_id}"
                abstract = jsonld.get("description", "")
                authors = _extract_authors(jsonld)
                year = _extract_year(jsonld)
                doi = _extract_doi(jsonld)

                # All articles we fetched are published, thus accepted
                decision = "accepted"

                metadata = {
                    "doi": doi,
                    "article_url": article_url,
                    "peer_review_url": payload.get("peer_review_url"),
                    "is_open_access": True,
                }

                # Upsert paper
                conn.execute(
                    """INSERT INTO papers (id, venue_id, source_id, title, abstract, authors, pdf_url, decision, year, metadata)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                       ON CONFLICT (venue_id, source_id) DO UPDATE SET
                         title = EXCLUDED.title, abstract = EXCLUDED.abstract,
                         authors = EXCLUDED.authors, pdf_url = EXCLUDED.pdf_url,
                         decision = EXCLUDED.decision, year = EXCLUDED.year,
                         metadata = EXCLUDED.metadata""",
                    (paper_id, self.venue, source_id, title, abstract,
                     authors, pdf_url, decision, year,
                     json.dumps(metadata)),
                )

                # Split peer review text into individual reviewer reports,
                # then split each report into atomic comments
                comment_index = 0
                reports = _split_into_reviewer_reports(pr_text)

                if not reports:
                    # Skip papers with zero comments
                    print(f"  [skip] {paper_id}: no reviewer remarks found")
                    continue

                for reviewer_id, report_text in reports:
                    comments = split_section_into_comments(report_text)

                    for text in comments:
                        if len(text) < MIN_COMMENT_LENGTH:
                            continue
                        comment_index += 1
                        conn.execute(
                            """INSERT INTO comments (id, paper_id, source, reviewer_id, content)
                               VALUES (%s, %s, %s, %s, %s)
                               ON CONFLICT (id) DO NOTHING""",
                            (f"{paper_id}:human-{comment_index}", paper_id, "human",
                             reviewer_id, text),
                        )

                parsed_count += 1
                title_preview = title[:60]
                print(f"[{parsed_count}] {paper_id}: {title_preview}... ({comment_index} comments)", flush=True)

        print(f"\nParsed {parsed_count} papers for {self.venue}")
        return parsed_count
