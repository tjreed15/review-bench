"""Fetcher registry. Add new venue fetchers here."""

from __future__ import annotations

from src.fetchers.types import VenueFetcher
from src.fetchers.openreview import OpenReviewFetcher
from src.fetchers.elife import ELifeFetcher
from src.fetchers.nature import NatureHumanBehaviourFetcher

_FETCHERS: dict[str, type[VenueFetcher]] = {
    "iclr-2025": OpenReviewFetcher,
    "elife": ELifeFetcher,
    "nhb": NatureHumanBehaviourFetcher,
}


def get_fetcher(venue: str) -> VenueFetcher:
    """Get a fetcher instance for the given venue."""
    cls = _FETCHERS.get(venue)
    if cls is None:
        available = ", ".join(sorted(_FETCHERS.keys()))
        raise ValueError(f"Unknown venue '{venue}'. Available: {available}")
    return cls()
