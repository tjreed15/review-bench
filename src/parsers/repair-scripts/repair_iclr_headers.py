"""One-time repair script: delete orphan section headers from ICLR comments.

These are short comments (under 60 chars) that end with ':' — section labels
like "Main weaknesses:", "Clarifying questions:", lead-in sentences like
"The main strengths of the paper are:", or multi-line fragments with a
trailing label. None are actionable peer review comments.

Run: python3 repair_iclr_headers.py [--dry-run]
"""

import sys
from src.db.client import get_conn, fetch_all


def main():
    dry_run = "--dry-run" in sys.argv

    rows = fetch_all("""
        SELECT c.id, c.content, LENGTH(c.content) as len
        FROM comments c
        JOIN papers p ON c.paper_id = p.id
        WHERE c.source = 'human'
          AND p.venue_id = 'iclr-2025'
          AND LENGTH(c.content) < 60
          AND c.content LIKE '%%:'
        ORDER BY LENGTH(c.content) ASC
    """)

    if not rows:
        print("No orphan section headers found.")
        return

    print(f"Found {len(rows)} orphan section headers to delete")
    print()
    for r in rows:
        print(f"  [{r['len']:3d}] {r['id']:55s} | {r['content']}")

    if dry_run:
        print(f"\nDry run — no changes made. Remove --dry-run to execute.")
        return

    with get_conn() as conn:
        for r in rows:
            conn.execute("DELETE FROM assessments WHERE comment_id = %s", (r["id"],))
            conn.execute("DELETE FROM comments WHERE id = %s", (r["id"],))

    print(f"\nDeleted {len(rows)} orphan section headers (and their assessments).")


if __name__ == "__main__":
    main()
