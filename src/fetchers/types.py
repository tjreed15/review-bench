"""Protocol for venue fetchers."""

from __future__ import annotations

from typing import Protocol


class VenueFetcher(Protocol):
    """Fetches raw data from a venue and stores in raw_venue_data."""

    venue: str

    async def fetch(self, limit: int = 50, **kwargs) -> int:
        """Fetch raw data and store in raw_venue_data. Returns count fetched."""
        ...
