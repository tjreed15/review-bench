"""eLife parser: raw_venue_data → papers + comments.

Handles two peer-review formats:
1. Old format: Single editorial decision letter, sometimes
   with explicit "Reviewer #N:" sections, sometimes merged prose/numbered points.
2. New format: Sections separated by "---" dividers. First
   section is editor summary, subsequent sections are individual reviewer reviews.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from src.db.client import get_conn


def _extract_submission_id(submission: dict) -> str:
    return submission.get("id", "unknown")


def _parse_new_format_reviews(review_text: str) -> list[dict]:
    """Parse new-format reviews separated by --- dividers.

    Returns list of dicts with keys: reviewer_id, text, is_editor_summary.
    """
    sections = re.split(r"\n---\n", review_text)
    reviews = []
    reviewer_counter = 0

    for i, section in enumerate(sections):
        section = section.strip()
        if not section:
            continue

        # Treat first section as editor summary
        is_editor = i == 0

        # Extract reviewer info
        reviewer_id = None
        reviewer_match = re.search(
            r"Reviewers:\s*\n-\s*(.+)", section
        )
        if reviewer_match:
            reviewer_name = reviewer_match.group(1).strip()
            if "not individually listed" not in reviewer_name.lower():
                if "anonymous" in reviewer_name.lower():
                    reviewer_counter += 1
                    reviewer_id = f"reviewer-{reviewer_counter}"
                else:
                    reviewer_counter += 1
                    reviewer_id = reviewer_name

        # Extract the review text (everything after "## Review text" header)
        text_match = re.search(r"##\s*Review text\s*\n+", section)
        if text_match:
            body = section[text_match.end():].strip()
        else:
            # Fallback: skip header lines
            lines = section.split("\n")
            body_start = 0
            for j, line in enumerate(lines):
                if line.startswith("DOI:") or line.startswith("## Review"):
                    body_start = j + 1
            body = "\n".join(lines[body_start:]).strip()

        # Remove DOI line from body
        body = re.sub(r"^DOI:\s*\[.*?\]\(.*?\)\s*\n*", "", body).strip()

        if not body or len(body) < 50:
            continue

        reviews.append({
            "reviewer_id": reviewer_id if not is_editor else "editor",
            "text": body,
            "is_editor_summary": is_editor,
        })

    return reviews


def _parse_old_format_reviews(review_text: str) -> list[dict]:
    """Parse old-format editorial decision letter.

    Tries to split by "Reviewer #N:" markers. If none found, treats the
    whole letter as a single editorial review.
    """
    # Remove boilerplate header
    text = review_text

    # Remove the markdown header and metadata
    text = re.sub(r"^#\s*Peer review.*?\n", "", text)
    text = re.sub(r"^Editors:.*?\n(?:-.*?\n)*", "", text, flags=re.MULTILINE)
    text = re.sub(r"^Reviewers:.*?\n(?:-.*?\n)*", "", text, flags=re.MULTILINE)
    text = re.sub(r"^##\s*Review text\s*\n", "", text, flags=re.MULTILINE)
    text = re.sub(r"^DOI:\s*\[.*?\]\(.*?\)\s*\n*", "", text, flags=re.MULTILINE)

    # Remove the standard eLife boilerplate paragraphs
    boilerplate_patterns = [
        r"eLife posts the editorial decision letter.*?major concerns raised by the reviewers\.\s*\n*",
        r"In the interests of transparency.*?major concerns raised by the reviewers\.\s*\n*",
        r"In the interests of transparency.*?minor comments are not usually included\.\s*\n*",
    ]
    for pat in boilerplate_patterns:
        text = re.sub(pat, "", text, flags=re.DOTALL)

    text = text.strip()

    # Try to split by "Reviewer #N:" patterns (also matches variants like
    # "Reviewer #1 minor comments:", "Reviewer 1 comments:", etc.)
    reviewer_pattern = re.compile(
        r"^(?:Reviewer\s*#?\s*(\d+)\s*[^:\n]*:\s*)$",
        re.MULTILINE,
    )
    matches = list(reviewer_pattern.finditer(text))

    if len(matches) >= 2:
        reviews = []

        # Content before first reviewer marker is the editor's letter
        editor_text = text[: matches[0].start()].strip()
        if editor_text and len(editor_text) >= 50:
            reviews.append({
                "reviewer_id": "editor",
                "text": editor_text,
                "is_editor_summary": True,
            })

        # Each reviewer section
        for j, match in enumerate(matches):
            reviewer_num = match.group(1)
            start = match.end()
            end = matches[j + 1].start() if j + 1 < len(matches) else len(text)
            reviewer_text = text[start:end].strip()

            if reviewer_text and len(reviewer_text) >= 50:
                reviews.append({
                    "reviewer_id": f"reviewer-{reviewer_num}",
                    "text": reviewer_text,
                    "is_editor_summary": False,
                })

        return reviews

    # No reviewer markers found — treat as single editorial letter
    if text and len(text) >= 50:
        return [{
            "reviewer_id": "editor",
            "text": text,
            "is_editor_summary": True,
        }]

    return []


def _split_review_into_comments(text: str) -> list[str]:
    """Split a single review into individual comments.

    Handles numbered lists, structured sections (Strengths/Weaknesses/Summary),
    and paragraph-based splitting.
    """
    comments = []

    # Check for structured sections (Strengths, Weaknesses, etc.)
    section_pattern = re.compile(
        r"^(?:#{1,3}\s+)?(Strengths?|Weaknesses?|Major\s+(?:comments?|concerns?|issues?)|"
        r"Minor\s+(?:comments?|concerns?|issues?)|Questions?|"
        r"Comments?\s+on\s+revisions?|Summary|Specific\s+comments?|"
        r"General\s+comments?|Recommendations?|Suggestions?)"
        r"(?:\s+\w+)*\s*:?\s*$",
        re.MULTILINE | re.IGNORECASE,
    )
    section_matches = list(section_pattern.finditer(text))

    if section_matches:
        for j, smatch in enumerate(section_matches):
            start = smatch.end()
            end = (
                section_matches[j + 1].start()
                if j + 1 < len(section_matches)
                else len(text)
            )
            section_body = text[start:end].strip()
            if section_body:
                comments.extend(_split_body_into_comments(section_body))
    else:
        # No structured sections — split the whole text
        comments = _split_body_into_comments(text)

    return [c for c in comments if len(c.strip()) >= 20]


def _split_body_into_comments(text: str) -> list[str]:
    """Split a block of text into comments by numbered items, bullets, or paragraphs."""
    lines = text.split("\n")

    # Detect numbered items: "1.", "(1)", "1)", etc.
    numbered_pattern = re.compile(r"^\s*(?:\(?\d+[a-z]?\)\.?\s|\d+[a-z]?[.)\u3001]\s)")
    bullet_pattern = re.compile(r"^\s*[-+*]\s")

    # Count pattern occurrences
    num_count = sum(1 for l in lines if numbered_pattern.match(l))
    bullet_count = sum(1 for l in lines if bullet_pattern.match(l))

    if num_count >= 2:
        return _split_by_pattern(lines, numbered_pattern)
    elif bullet_count >= 2:
        return _split_by_pattern(lines, bullet_pattern)
    else:
        return _split_by_paragraphs(lines)


def _split_by_pattern(lines: list[str], pattern: re.Pattern) -> list[str]:
    """Split lines where a new item starts at each pattern match."""
    comments = []
    current: list[str] = []

    for line in lines:
        if pattern.match(line) and current:
            comments.append("\n".join(current).strip())
            current = []
        current.append(line)

    if current:
        comments.append("\n".join(current).strip())

    return [c for c in comments if c]


def _split_by_paragraphs(lines: list[str]) -> list[str]:
    """Split by blank lines into paragraphs."""
    comments = []
    current: list[str] = []

    for line in lines:
        if not line.strip():
            if current:
                comments.append("\n".join(current).strip())
                current = []
        else:
            current.append(line)

    if current:
        comments.append("\n".join(current).strip())

    return [c for c in comments if c]


WRITE_BATCH_SIZE = 20


class ELifeParser:
    venue = "elife"

    def parse(self, limit: int | None = None, manuscripts_dir: str | None = None) -> int:
        """Parse eLife manuscripts directly from local files into papers + comments.

        Reads from the local cloned repo instead of raw_venue_data to avoid
        slow JSONB round-trips through the remote DB.
        """
        manuscripts_dir = manuscripts_dir or os.environ.get("ELIFE_MANUSCRIPTS_DIR")
        if not manuscripts_dir:
            raise RuntimeError(
                "No manuscripts directory specified. "
                "Clone https://github.com/OpenEvalProject/evals/ and set "
                "ELIFE_MANUSCRIPTS_DIR to the manuscripts/ folder path."
            )
        mdir = Path(manuscripts_dir)
        if not mdir.exists():
            raise FileNotFoundError(
                f"Manuscripts directory not found: {manuscripts_dir}. "
                "Ensure the path correctly points to the manuscripts/ folder "
                "within the cloned https://github.com/OpenEvalProject/evals/ repo."
            )

        # Get source_ids already in raw_venue_data to know which ones were fetched
        from src.db.queries import get_raw_source_ids
        fetched_ids = get_raw_source_ids(self.venue)

        parsed_count = 0
        total_limit = limit or 100000

        # Collect a batch of parsed data, then write in one transaction
        paper_batch: list[tuple] = []
        comment_batch: list[tuple] = []

        for folder_name in sorted(fetched_ids):
            if parsed_count >= total_limit:
                break

            db_export = mdir / folder_name / "v1" / "db_export.json"
            if not db_export.exists():
                continue

            try:
                with open(db_export, "r") as f:
                    data = json.load(f)
            except (json.JSONDecodeError, OSError):
                continue

            submission = data.get("submission", {})
            content_items = data.get("content", [])

            submission_id = _extract_submission_id(submission)
            paper_id = f"elife-{folder_name}" if not folder_name.startswith("elife-") else folder_name

            manuscript_text = ""
            peer_review_text = ""
            for item in content_items:
                if item.get("content_type") == "manuscript":
                    manuscript_text = item.get("content_text", "")
                elif item.get("content_type") == "peer_review":
                    peer_review_text = item.get("content_text", "")

            if not manuscript_text or not peer_review_text:
                continue

            title = _extract_title(manuscript_text, folder_name)

            paper_batch.append((
                paper_id, self.venue, folder_name, title,
                _extract_abstract(manuscript_text),
                None, None, manuscript_text, "unknown", None,
                json.dumps({
                    "submission_id": submission_id,
                    "manuscript_length": len(manuscript_text),
                    "review_length": len(peer_review_text),
                }),
            ))

            # Parse peer reviews
            is_new_format = "\n---\n" in peer_review_text
            if is_new_format:
                reviews = _parse_new_format_reviews(peer_review_text)
            else:
                reviews = _parse_old_format_reviews(peer_review_text)

            comment_index = 0
            for review in reviews:
                reviewer_id = review["reviewer_id"]
                individual_comments = _split_review_into_comments(review["text"])
                for comment_text in individual_comments:
                    comment_index += 1
                    comment_batch.append((
                        f"{paper_id}:human-{comment_index}",
                        paper_id, "human", reviewer_id, comment_text,
                    ))

            parsed_count += 1

            # Flush batch to DB
            if len(paper_batch) >= WRITE_BATCH_SIZE:
                self._flush(paper_batch, comment_batch)
                print(f"[{parsed_count}] {paper_id}: {title[:60]}... ({comment_index} comments)", flush=True)
                paper_batch = []
                comment_batch = []

        # Flush remaining
        if paper_batch:
            self._flush(paper_batch, comment_batch)
            print(f"[{parsed_count}] done", flush=True)

        print(f"\nParsed {parsed_count} papers for {self.venue}")
        return parsed_count

    @staticmethod
    def _flush(paper_batch: list[tuple], comment_batch: list[tuple]) -> None:
        with get_conn() as conn:
            for p in paper_batch:
                conn.execute(
                    """INSERT INTO papers (id, venue_id, source_id, title, abstract, authors, pdf_url, manuscript_text, decision, year, metadata)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                       ON CONFLICT (venue_id, source_id) DO UPDATE SET
                         title = EXCLUDED.title, abstract = EXCLUDED.abstract,
                         manuscript_text = EXCLUDED.manuscript_text,
                         metadata = EXCLUDED.metadata""",
                    p,
                )
            for c in comment_batch:
                conn.execute(
                    """INSERT INTO comments (id, paper_id, source, reviewer_id, content)
                       VALUES (%s, %s, %s, %s, %s)
                       ON CONFLICT (id) DO NOTHING""",
                    c,
                )


def _extract_title(manuscript_text: str, fallback: str) -> str:
    """Try to extract the title from the manuscript markdown."""
    lines = manuscript_text.strip().split("\n")
    for line in lines[:10]:
        line = line.strip()
        # Skip empty lines
        if not line:
            continue
        # Markdown heading
        if line.startswith("#"):
            return re.sub(r"^#+\s*", "", line).strip()
        # First non-empty line that looks like a title (not too long, not a paragraph)
        if len(line) < 300 and not line.startswith("*") and not line.startswith("-"):
            return line
    return fallback


def _extract_abstract(manuscript_text: str) -> str | None:
    """Try to extract the abstract from the manuscript markdown."""
    # Look for ## Abstract section
    match = re.search(
        r"(?:^|\n)#{1,3}\s*Abstract\s*\n(.*?)(?:\n#{1,3}\s|\Z)",
        manuscript_text,
        re.DOTALL | re.IGNORECASE,
    )
    if match:
        abstract = match.group(1).strip()
        if len(abstract) > 50:
            return abstract[:5000]

    return None
