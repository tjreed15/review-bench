"""Protocol for venue parsers."""

from __future__ import annotations

from typing import Protocol


class VenueParser(Protocol):
    """Parses raw venue data into canonical papers + comments tables."""

    venue: str

    def parse(self, limit: int | None = None) -> int:
        """Read raw_venue_data, write to papers + comments. Returns count parsed."""
        ...
