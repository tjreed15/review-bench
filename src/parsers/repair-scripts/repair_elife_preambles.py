"""One-time repair script: delete editorial preamble comments from eLife papers.

These are editor summary letters ("Thank you for sending/submitting...") that
synthesize reviewer feedback but are not individual reviewer comments. The actual
reviewer critiques exist as separate comments on the same papers.

Run: python3 repair_elife_preambles.py [--dry-run]
"""

import sys
from src.db.client import get_conn, fetch_all


def main():
    dry_run = "--dry-run" in sys.argv

    # Find all editorial preamble comments for eLife
    rows = fetch_all("""
        SELECT c.id, c.paper_id, LENGTH(c.content) as len
        FROM comments c
        JOIN papers p ON c.paper_id = p.id
        WHERE c.source = 'human'
          AND p.venue_id = 'elife'
          AND (c.content LIKE 'Thank you for sending%'
               OR c.content LIKE 'Thank you for submitting%'
               OR c.content LIKE 'Thank you for choosing%')
    """)

    if not rows:
        print("No editorial preambles found.")
        return

    print(f"Found {len(rows)} editorial preamble comments to delete")
    print()

    for r in rows:
        # Count other human comments on this paper
        others = fetch_all(
            "SELECT COUNT(*) as cnt FROM comments WHERE paper_id = %s AND source = 'human' AND id != %s",
            (r["paper_id"], r["id"]),
        )
        other_count = others[0]["cnt"]
        print(f"  {r['id']:40s} [{r['len']:5d} chars]  ({other_count} other comments on paper)")

    if dry_run:
        print(f"\nDry run — no changes made. Remove --dry-run to execute.")
        return

    with get_conn() as conn:
        deleted = 0
        for r in rows:
            conn.execute("DELETE FROM assessments WHERE comment_id = %s", (r["id"],))
            conn.execute("DELETE FROM comments WHERE id = %s", (r["id"],))
            deleted += 1

    print(f"\nDeleted {deleted} editorial preamble comments (and their assessments).")


if __name__ == "__main__":
    main()
