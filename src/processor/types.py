"""Types and shared constants for the review-bench processor."""

from __future__ import annotations

from pathlib import Path

SOURCES = ["human", "r3", "gemini-3-pro", "gpt-5.2"]
SOURCE_PAIRS = [("human", "r3"), ("human", "gemini-3-pro"), ("human", "gpt-5.2"), ("r3", "gemini-3-pro"), ("r3", "gpt-5.2"), ("gemini-3-pro", "gpt-5.2")]
SOURCE_LABELS = ["Human", "R3", "Gemini 3 Pro", "GPT-5.2"]

STANCES = ["SUPPORTIVE", "CRITICAL", "NEUTRAL"]
VALID_STANCES = {"SUPPORTIVE", "CRITICAL", "NEUTRAL"}
VALID_CRITIQUE_TYPES = {"validity", "sufficiency", "contribution", "clarity", "transparency"}

OUT_DIR = Path("results")

VENUES = ["iclr-2025", "elife", "nhb"]
VENUE_LABELS = {"iclr-2025": "ICLR", "elife": "eLife", "nhb": "NHB"}
