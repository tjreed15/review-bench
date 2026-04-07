"""Shared utilities for splitting review text into individual comments.

Handles numbered lists, bullet lists, and paragraph-based splitting.
"""

from __future__ import annotations

import re

MIN_COMMENT_LENGTH = 20


def extract_review_sections(markdown: str) -> list[str]:
    """Extract Strengths, Weaknesses, and Questions sections from review markdown."""
    lines = markdown.split("\n")
    sections: list[str] = []
    current: list[str] = []
    in_target = False

    for line in lines:
        header = re.match(r"^#{1,3}\s+(.+)", line) or re.match(
            r"^\*\*([A-Za-z\s]+)\*\*\s*$", line
        )
        if header:
            name = header.group(1).replace("**", "").strip().lower()
            is_target = (
                name.startswith("strength")
                or name.startswith("weakness")
                or name.startswith("question")
            )

            if in_target and current:
                sections.append("\n".join(current))
                current = []
            in_target = is_target
            continue

        if in_target:
            current.append(line)

    if in_target and current:
        sections.append("\n".join(current))

    return sections


def split_numbered_list(lines: list[str]) -> list[str]:
    """Split lines by top-level numbered items (1., (1), etc.)."""
    comments: list[str] = []
    current: list[str] = []

    def is_new_numbered(line: str) -> bool:
        t = line.strip()
        return bool(re.match(r"^\d+[.、)]\s", t) or re.match(r"^\(\d+\)\s", t))

    def flush():
        if current:
            comments.append("\n".join(current).strip())
            current.clear()

    for line in lines:
        t = line.strip()
        if not t:
            if current:
                current.append("")
            continue
        if is_new_numbered(t):
            flush()
            stripped = re.sub(r"^\(\d+\)\s*", "", t)
            stripped = re.sub(r"^\d+[.、)]\s*", "", stripped).strip()
            current.append(stripped)
        else:
            current.append(t)

    flush()
    return [c for c in comments if c]


def split_bullet_list(lines: list[str]) -> list[str]:
    """Split lines by top-level bullet items (-, +, *)."""
    comments: list[str] = []
    current: list[str] = []

    def is_top_level_bullet(line: str) -> bool:
        return bool(re.match(r"^[-+*]\s", line))

    def flush():
        if current:
            comments.append("\n".join(current).strip())
            current.clear()

    for line in lines:
        t = line.strip()
        if not t:
            if current:
                current.append("")
            continue
        if is_top_level_bullet(line):
            flush()
            stripped = re.sub(r"^[-+*]\s+", "", t).strip()
            current.append(stripped)
        else:
            current.append(t)

    flush()
    return [c for c in comments if c]


def split_paragraphs(lines: list[str]) -> list[str]:
    """Split lines by blank lines into paragraphs."""
    comments: list[str] = []
    current: list[str] = []

    def flush():
        if current:
            comments.append("\n".join(current).strip())
            current.clear()

    for line in lines:
        if not line.strip():
            flush()
        else:
            current.append(line.strip())

    flush()
    return [c for c in comments if c]


def split_section_into_comments(section_text: str) -> list[str]:
    """Split a section into individual comments. Auto-detects list format."""
    lines = section_text.split("\n")

    # Detect primary list format
    mode = "paragraph"
    for line in lines:
        t = line.strip()
        if not t:
            continue
        if re.match(r"^\d+[a-z]?[.、)]\s", t) or re.match(r"^\(\d+\)\s", t):
            mode = "numbered"
            break
        if re.match(r"^[-+*]\s", t):
            mode = "bullet"
            break

    if mode == "numbered":
        return split_numbered_list(lines)
    elif mode == "bullet":
        return split_bullet_list(lines)
    else:
        return split_paragraphs(lines)


def split_review_into_comments(markdown: str) -> list[str]:
    """Parse a review into individual strength/weakness/question comments."""
    sections = extract_review_sections(markdown)
    all_comments: list[str] = []

    for section in sections:
        cleaned = re.sub(r"^\s*(strengths?|weaknesses|questions)\s*:?\s*\n?", "", section, flags=re.I)
        all_comments.extend(split_section_into_comments(cleaned))

    return [c for c in all_comments if len(c) >= MIN_COMMENT_LENGTH]
