"""One-time repair script for NHB (Nature Human Behaviour) comments.

Fixes:
1. Deletes orphan section headers (short comments ending with ':')
2. Splits the 47k comment that has author responses mixed in
3. Deletes boilerplate short comments ("No further comments", etc.)

Run: python3 -m src.parsers.repair-scripts.repair_nhb_comments [--dry-run]
"""

import re
import sys
from src.db.client import get_conn, fetch_all


def main():
    dry_run = "--dry-run" in sys.argv

    print("=" * 60)
    print("NHB Comment Repair Script")
    print("=" * 60)

    # ── 1. Delete orphan section headers ──
    headers = fetch_all("""
        SELECT c.id, c.content, LENGTH(c.content) as len
        FROM comments c JOIN papers p ON c.paper_id = p.id
        WHERE c.source = 'human' AND p.venue_id = 'nhb'
          AND LENGTH(c.content) < 60 AND c.content LIKE '%%:'
    """)
    print(f"\n1. Orphan section headers to delete: {len(headers)}")
    for r in headers:
        print(f"   [{r['len']:3d}] {r['id']:55s} | {r['content']}")

    # ── 2. Delete the 47k author-response comment ──
    monster = fetch_all(
        "SELECT id, content, paper_id, reviewer_id FROM comments WHERE id = %s",
        ("nhb-s41562-025-02205-6:human-5",),
    )
    if monster:
        c = monster[0]["content"]
        print(f"\n4. Monster comment ({len(c)} chars): interleaved reviewer Q&A from revision round — will delete (paper has 4 other comments with actual reviews)")
    else:
        print("\n4. Monster comment not found (already fixed?)")

    # ── 5. Delete boilerplate short comments ──
    boilerplate_patterns = [
        "No further comments%",
        "I have no further%",
        "My concerns were addressed%",
        "My previous comments have been addressed%",
        "All my questions have been addressed%",
        "All my issues were resolved%",
        "All my comments have been%",
        "The authors addressed all%",
        "The authors have addressed%",
        "The revised version fulfilled%",
        "(Did not submit review)%",
        "to seeing it published.%",
        "I did not review the code.%",
    ]
    like_clauses = " OR ".join(f"c.content LIKE %s" for _ in boilerplate_patterns)
    boilerplate = fetch_all(f"""
        SELECT c.id, c.content, LENGTH(c.content) as len
        FROM comments c JOIN papers p ON c.paper_id = p.id
        WHERE c.source = 'human' AND p.venue_id = 'nhb'
          AND LENGTH(c.content) < 80
          AND ({like_clauses})
    """, tuple(boilerplate_patterns))
    print(f"\n5. Boilerplate short comments to delete: {len(boilerplate)}")
    for r in boilerplate:
        print(f"   [{r['len']:3d}] {r['id']:55s} | {r['content']}")

    # ── Summary ──
    print(f"\n{'=' * 60}")
    print(f"Summary:")
    print(f"  Delete {len(headers)} section headers")
    print(f"  Delete 1 monster comment (47k interleaved Q&A)")
    print(f"  Delete {len(boilerplate)} boilerplate comments")

    if dry_run:
        print(f"\nDry run — no changes made. Remove --dry-run to execute.")
        return

    # ── Execute ──
    with get_conn() as conn:
        # 1. Delete headers
        for r in headers:
            conn.execute("DELETE FROM assessments WHERE comment_id = %s", (r["id"],))
            conn.execute("DELETE FROM comments WHERE id = %s", (r["id"],))

        # 2. Delete monster comment (interleaved Q&A, not a real review)
        if monster:
            conn.execute("DELETE FROM assessments WHERE comment_id = %s", (monster[0]["id"],))
            conn.execute("DELETE FROM comments WHERE id = %s", (monster[0]["id"],))

        # 5. Delete boilerplate
        for r in boilerplate:
            conn.execute("DELETE FROM assessments WHERE comment_id = %s", (r["id"],))
            conn.execute("DELETE FROM comments WHERE id = %s", (r["id"],))

    print("\nDone.")


if __name__ == "__main__":
    main()
