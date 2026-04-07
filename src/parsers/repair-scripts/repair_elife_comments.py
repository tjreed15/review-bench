"""One-time repair script: split long eLife comments that contain multiple
distinct reviews, editors' notes, or structural sections that the parser missed.

Run: python3 repair_elife_comments.py
"""

import re
from src.db.client import get_conn, fetch_all
from src.parsers.elife import _split_review_into_comments


# ---------------------------------------------------------------------------
# Splitting strategies
# ---------------------------------------------------------------------------

def split_on_editors_note(content: str) -> list[str]:
    """Split at [Editors' note: ...] boundaries."""
    parts = re.split(r"(\[Editors. note[^\]]*\])", content)
    sections = []
    current = ""
    for part in parts:
        if re.match(r"\[Editors. note", part):
            if current.strip():
                sections.append(current.strip())
            current = part
        else:
            current += part
    if current.strip():
        sections.append(current.strip())
    return sections


def split_on_reviewer_inline(content: str) -> list[str]:
    """Split on \\n\\nReviewer #N: or Reviewer N Comments: appearing inline."""
    pattern = re.compile(
        r"\n\n(Reviewer\s*#?\s*\d+\s*[^:\n]*:)",
        re.IGNORECASE,
    )
    matches = list(pattern.finditer(content))
    if not matches:
        return [content]

    sections = []
    pre = content[: matches[0].start()].strip()
    if pre:
        sections.append(pre)

    for i, m in enumerate(matches):
        start = m.start() + 2  # skip the \n\n
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        sections.append(content[start:end].strip())

    return sections


def split_on_star_claims(content: str) -> list[str]:
    """Split on * Claim N bullet items."""
    pattern = re.compile(r"^\* Claim \d+", re.MULTILINE)
    matches = list(pattern.finditer(content))
    if not matches:
        return [content]

    sections = []
    pre = content[: matches[0].start()].strip()
    if pre:
        sections.append(pre)

    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        sections.append(content[start:end].strip())

    return sections


def split_on_protocol(content: str) -> list[str]:
    """Split on Protocol N headers."""
    pattern = re.compile(r"^Protocol \d+", re.MULTILINE)
    matches = list(pattern.finditer(content))
    if not matches:
        return [content]

    sections = []
    pre = content[: matches[0].start()].strip()
    if pre:
        sections.append(pre)

    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        sections.append(content[start:end].strip())

    return sections


def split_on_lettered(content: str) -> list[str]:
    """Split on A) B) C) etc. after a preamble."""
    pattern = re.compile(r"^[A-G]\)", re.MULTILINE)
    matches = list(pattern.finditer(content))
    if len(matches) < 3:
        return [content]

    sections = []
    pre = content[: matches[0].start()].strip()
    if pre:
        sections.append(pre)

    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        sections.append(content[start:end].strip())

    return sections


def split_on_extracts(content: str) -> list[str]:
    """Split on 'Extracts from Reviewer #N:' headers."""
    pattern = re.compile(r"^Extracts from Reviewer", re.MULTILINE)
    matches = list(pattern.finditer(content))
    if not matches:
        return [content]

    sections = []
    pre = content[: matches[0].start()].strip()
    if pre:
        sections.append(pre)

    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        sections.append(content[start:end].strip())

    return sections


def split_on_text_marker(content: str, marker: str) -> list[str]:
    """Split at a specific text marker (e.g. 'Additional comments')."""
    idx = content.find(marker)
    if idx <= 0:
        return [content]
    before = content[:idx].strip()
    after = content[idx:].strip()
    sections = []
    if before:
        sections.append(before)
    if after:
        sections.append(after)
    return sections


# ---------------------------------------------------------------------------
# Repair plan: (comment_id, strategy)
# ---------------------------------------------------------------------------

REPAIRS = [
    # Editors' note splits
    ("elife-03695:human-4", "editors_note"),
    ("elife-06063:human-4", "editors_note"),
    ("elife-01901:human-6", "editors_note"),
    ("elife-01085:human-14", "editors_note"),
    ("elife-06738:human-4", "editors_note"),
    ("elife-01861:human-6", "editors_note"),
    ("elife-07068:human-5", "editors_note"),
    ("elife-02812:human-5", "editors_note"),
    ("elife-04810:human-23", "editors_note"),
    ("elife-03522:human-5", "editors_note"),
    ("elife-08150:human-4", "editors_note"),
    ("elife-05949:human-5", "editors_note"),
    ("elife-00269:human-3", "editors_note"),
    ("elife-01102:human-3", "editors_note"),

    # Reviewer inline splits
    ("elife-02663:human-9", "reviewer_inline"),
    ("elife-03043:human-3", "reviewer_inline"),
    ("elife-05604:human-3", "reviewer_inline"),
    ("elife-02137:human-26", "reviewer_inline"),
    ("elife-01914:human-4", "reviewer_inline"),

    # Star claims
    ("elife-00523:human-5", "star_claims"),

    # Protocol sections
    ("elife-04034:human-4", "protocol"),

    # Lettered items
    ("elife-09976:human-3", "lettered"),

    # Extracts from Reviewer
    ("elife-04796:human-13", "extracts"),

    # Text marker splits
    ("elife-01998:human-3", "marker:Additional comments"),
    ("elife-07770:human-16", "marker:Specific important comments"),
]

STRATEGY_MAP = {
    "editors_note": split_on_editors_note,
    "reviewer_inline": split_on_reviewer_inline,
    "star_claims": split_on_star_claims,
    "protocol": split_on_protocol,
    "lettered": split_on_lettered,
    "extracts": split_on_extracts,
}


def apply_strategy(content: str, strategy: str) -> list[str]:
    if strategy.startswith("marker:"):
        marker = strategy[len("marker:"):]
        return split_on_text_marker(content, marker)
    fn = STRATEGY_MAP[strategy]
    return fn(content)


def further_split(sections: list[str]) -> list[str]:
    """Run each section through the existing eLife comment splitter."""
    all_comments = []
    for sec in sections:
        sub = _split_review_into_comments(sec)
        if sub:
            all_comments.extend(sub)
        elif len(sec.strip()) >= 20:
            all_comments.append(sec.strip())
    return all_comments


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
    repair_ids = [r[0] for r in REPAIRS]

    # Fetch all comments to repair
    rows = fetch_all(
        "SELECT c.id, c.content, c.paper_id, c.reviewer_id "
        "FROM comments c WHERE c.id = ANY(%s)",
        (repair_ids,),
    )
    row_map = {r["id"]: r for r in rows}

    total_old = 0
    total_new = 0

    with get_conn() as conn:
        for comment_id, strategy in REPAIRS:
            r = row_map.get(comment_id)
            if not r:
                print(f"  SKIP {comment_id}: not found in DB")
                continue

            content = r["content"]
            paper_id = r["paper_id"]
            reviewer_id = r["reviewer_id"]

            # Step 1: split into sections
            sections = apply_strategy(content, strategy)

            if len(sections) <= 1:
                print(f"  SKIP {comment_id}: strategy '{strategy}' produced no split")
                continue

            # Step 2: further split each section into atomic comments
            new_comments = further_split(sections)

            if len(new_comments) <= 1:
                print(f"  SKIP {comment_id}: further split produced no gain")
                continue

            # Step 3: delete assessments + old comment
            conn.execute(
                "DELETE FROM assessments WHERE comment_id = %s", (comment_id,)
            )
            conn.execute("DELETE FROM comments WHERE id = %s", (comment_id,))

            # Step 4: insert new comments
            max_idx = get_max_human_index(paper_id)
            inserted = 0
            for text in new_comments:
                if len(text.strip()) < 20:
                    continue
                max_idx += 1
                new_id = f"{paper_id}:human-{max_idx}"
                conn.execute(
                    "INSERT INTO comments (id, paper_id, source, reviewer_id, content) "
                    "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (id) DO NOTHING",
                    (new_id, paper_id, "human", reviewer_id, text),
                )
                inserted += 1

            total_old += 1
            total_new += inserted
            print(f"  {comment_id}: 1 -> {inserted} comments ({strategy})")

    print(f"\nDone. Replaced {total_old} comments with {total_new} total.")
    print("These papers need re-assessment for human source.")


if __name__ == "__main__":
    main()
