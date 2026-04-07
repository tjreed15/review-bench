"""One-time repair script: re-split long NHB comments that have internal structure.

Targets NHB human comments over 5000 chars that can be split into multiple
comments using the existing comment splitter. Only replaces comments where
the splitter produces more than 1 result.

Run: python3 repair_nhb_long_comments.py [--dry-run]
"""

import re
import sys
from src.db.client import get_conn, fetch_all
from src.lib.comment_parser import split_section_into_comments, MIN_COMMENT_LENGTH


def get_max_human_index(paper_id: str) -> int:
    rows = fetch_all(
        "SELECT id FROM comments WHERE paper_id = %s AND source = 'human'",
        (paper_id,),
    )
    max_idx = 0
    for r in rows:
        m = re.search(r"human-(\d+)$", r["id"])
        if m:
            max_idx = max(max_idx, int(m.group(1)))
    return max_idx


def main():
    dry_run = "--dry-run" in sys.argv

    rows = fetch_all("""
        SELECT c.id, c.content, c.paper_id, c.reviewer_id, LENGTH(c.content) as len
        FROM comments c JOIN papers p ON c.paper_id = p.id
        WHERE c.source = 'human' AND p.venue_id = 'nhb' AND LENGTH(c.content) > 5000
        ORDER BY LENGTH(c.content) DESC
    """)

    print(f"Found {len(rows)} NHB comments over 5000 chars")
    print()

    to_fix = []
    for r in rows:
        comments = split_section_into_comments(r["content"])
        # Filter short fragments
        comments = [c for c in comments if len(c) >= MIN_COMMENT_LENGTH]

        if len(comments) > 1:
            to_fix.append((r, comments))
            print(f"  {r['id']:55s} [{r['len']:6d}] -> {len(comments)} comments")
            for i, cm in enumerate(comments[:3]):
                preview = cm[:80].replace("\n", " ")
                print(f"    [{len(cm):5d}] {preview}...")
            if len(comments) > 3:
                print(f"    ... and {len(comments) - 3} more")
            print()
        else:
            print(f"  {r['id']:55s} [{r['len']:6d}] -> no split (leaving as-is)")

    print(f"\n{len(to_fix)} comments to re-split")

    if dry_run:
        print("\nDry run — no changes made. Remove --dry-run to execute.")
        return

    with get_conn() as conn:
        for r, comments in to_fix:
            old_id = r["id"]
            paper_id = r["paper_id"]
            reviewer_id = r["reviewer_id"]

            conn.execute("DELETE FROM assessments WHERE comment_id = %s", (old_id,))
            conn.execute("DELETE FROM comments WHERE id = %s", (old_id,))

            max_idx = get_max_human_index(paper_id)
            inserted = 0
            for text in comments:
                if len(text.strip()) < MIN_COMMENT_LENGTH:
                    continue
                max_idx += 1
                new_id = f"{paper_id}:human-{max_idx}"
                conn.execute(
                    "INSERT INTO comments (id, paper_id, source, reviewer_id, content) "
                    "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (id) DO NOTHING",
                    (new_id, paper_id, "human", reviewer_id, text),
                )
                inserted += 1

            print(f"  {old_id}: 1 -> {inserted} comments")

    print("\nDone.")


if __name__ == "__main__":
    main()
