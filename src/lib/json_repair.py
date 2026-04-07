"""Robustly parse JSON arrays from LLM output.

Handles markdown fences, trailing commas, truncated output, and other
common LLM JSON issues.
"""

from __future__ import annotations

import json
import re
from typing import Any


def parse_json_array(raw: str) -> list[Any]:
    """Parse a JSON array from potentially malformed LLM output.

    Fallback chain:
    1. Strip markdown fences, extract array portion, strict parse
    2. Fix common issues (trailing commas, smart quotes)
    3. Truncation repair (find last complete object)
    """
    text = raw.strip()

    # Strip markdown fences
    text = re.sub(r"```(?:json)?\s*", "", text)
    text = text.replace("```", "")

    # Extract the array portion
    match = re.search(r"\[[\s\S]*\]", text)
    if not match:
        raise ValueError(f"No JSON array found in response. First 300 chars: {text[:300]}")
    text = match.group(0)

    # Try strict parse
    try:
        result = json.loads(text)
        if isinstance(result, list):
            return result
    except json.JSONDecodeError:
        pass

    # Fix common issues
    fixed = _fix_common_issues(text)
    try:
        result = json.loads(fixed)
        if isinstance(result, list):
            print(f"  Warning: used JSON repair fallback, recovered {len(result)} items")
            return result
    except json.JSONDecodeError:
        pass

    # Truncation repair: find last complete object and close the array
    last_brace = text.rfind("}")
    if last_brace > 0:
        truncated = text[:last_brace + 1] + "]"
        try:
            result = json.loads(truncated)
            if isinstance(result, list):
                print(f"  Warning: recovered {len(result)} items from truncated JSON")
                return result
        except json.JSONDecodeError:
            pass

        # Try with fixes on truncated version
        fixed_truncated = _fix_common_issues(truncated)
        try:
            result = json.loads(fixed_truncated)
            if isinstance(result, list):
                print(f"  Warning: recovered {len(result)} items from repaired truncated JSON")
                return result
        except json.JSONDecodeError:
            pass

    # Last resort: use json_repair library
    try:
        from json_repair import repair_json
        repaired = repair_json(text, return_objects=True)
        if isinstance(repaired, list):
            print(f"  Warning: recovered {len(repaired)} items via json_repair library")
            return repaired
    except Exception:
        pass

    raise ValueError(f"Failed to parse JSON after repair. First 300 chars: {text[:300]}")


def _fix_common_issues(text: str) -> str:
    """Fix trailing commas, smart quotes, BOM, etc."""
    # Remove BOM
    text = text.lstrip("\ufeff")

    # Replace smart quotes
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    text = text.replace("\u2018", "'").replace("\u2019", "'")

    # Remove trailing commas before ] or }
    text = re.sub(r",\s*([}\]])", r"\1", text)

    return text
