"""Parser registry. Add new venue parsers here."""

from __future__ import annotations

from src.parsers.types import VenueParser
from src.parsers.openreview import OpenReviewParser
from src.parsers.elife import ELifeParser
from src.parsers.nature import NatureHumanBehaviourParser

_PARSERS: dict[str, type[VenueParser]] = {
    "iclr-2025": OpenReviewParser,
    "elife": ELifeParser,
    "nhb": NatureHumanBehaviourParser,
}


def get_parser(venue: str) -> VenueParser:
    """Get a parser instance for the given venue."""
    cls = _PARSERS.get(venue)
    if cls is None:
        available = ", ".join(sorted(_PARSERS.keys()))
        raise ValueError(f"Unknown venue '{venue}'. Available: {available}")
    return cls()
