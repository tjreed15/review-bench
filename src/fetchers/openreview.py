"""OpenReview fetcher.

Uses the OpenReview REST API to fetch papers and reviews from ICLR 2025.
Dumps full API responses into raw_venue_data as JSONB.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from urllib.parse import urlencode

from src.db.queries import upsert_raw_venue_data, get_raw_source_ids
from src.lib.rate_limit import rate_limited_fetch

API_BASE = "https://api2.openreview.net"

# Venue registry for OpenReview
VENUES = {
    "iclr-2025": "ICLR.cc/2025/Conference",
}


def _val(content: dict, key: str):
    """Extract .value from an OpenReview content field."""
    entry = content.get(key)
    if isinstance(entry, dict):
        return entry.get("value")
    return None


class OpenReviewFetcher:
    venue = "iclr-2025"

    async def fetch(self, limit: int = 50, **kwargs) -> int:
        """Fetch papers + reviews from OpenReview and store as raw JSONB."""
        venue_api_id = VENUES.get(self.venue)
        if not venue_api_id:
            raise ValueError(f"No OpenReview venue ID for {self.venue}")

        existing_ids = get_raw_source_ids(self.venue)
        total_collected = 0
        offset = 0
        batch_size = 50

        while total_collected < limit:
            notes = self._search_papers(venue_api_id, batch_size, offset)
            if not notes:
                break

            print(f"Processing {len(notes)} papers from offset {offset}...")

            for note in notes:
                if total_collected >= limit:
                    break

                source_id = note.get("id", "")
                if source_id in existing_ids:
                    continue

                content = note.get("content", {})
                title = _val(content, "title")
                if not title:
                    continue

                # Fetch reviews and decision for this paper
                forum_id = note.get("forum") or source_id
                reviews = self._get_reviews(forum_id)
                time.sleep(0.5)
                decision = self._get_decision(forum_id)
                time.sleep(0.5)

                if len(reviews) < 2:
                    title_preview = (title or "Unknown")[:40]
                    print(f"  [skip] {title_preview}... - only {len(reviews)} reviews")
                    continue

                # Build the complete raw payload
                raw_payload = {
                    "submission": note,
                    "reviews": reviews,
                    "decision": decision,
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                }

                upsert_raw_venue_data(self.venue, source_id, raw_payload)
                existing_ids.add(source_id)
                total_collected += 1

                title_preview = title[:60] if title else "Unknown"
                print(f"[{total_collected}] {title_preview}... ({len(reviews)} reviews, {decision})")

            offset += len(notes)
            time.sleep(0.5)

        print(f"\nFetched {total_collected} papers for {self.venue}")
        return total_collected

    def _search_papers(self, venue: str, limit: int, offset: int) -> list[dict]:
        """Search for papers using the OpenReview API."""
        invitation_patterns = [
            f"{venue}/-/Submission",
            f"{venue}/-/Blind_Submission",
        ]

        for invitation in invitation_patterns:
            params = {
                "invitation": invitation,
                "limit": str(limit),
                "offset": str(offset),
                "details": "replyCount,invitation",
            }
            url = f"{API_BASE}/notes?{urlencode(params)}"

            if offset == 0:
                print(f"Trying invitation: {invitation}")

            resp = rate_limited_fetch(url)
            if resp.status_code != 200:
                continue

            result = resp.json()
            notes = result.get("notes", [])
            if notes:
                print(f"Fetching papers from {venue} (offset={offset}, limit={limit})...")
                return notes

        # Fallback: content.venueid query
        params = {
            "content.venueid": venue,
            "limit": str(limit),
            "offset": str(offset),
        }
        url = f"{API_BASE}/notes?{urlencode(params)}"
        print(f"Fetching papers from {venue} using venueid (offset={offset}, limit={limit})...")

        resp = rate_limited_fetch(url)
        if resp.status_code != 200:
            raise RuntimeError(f"Failed to fetch papers: {resp.status_code}")

        return resp.json().get("notes", [])

    def _get_reviews(self, forum_id: str) -> list[dict]:
        """Get all review notes for a paper forum."""
        params = {"forum": forum_id}
        url = f"{API_BASE}/notes?{urlencode(params)}"
        resp = rate_limited_fetch(url)

        if resp.status_code != 200:
            print(f"Failed to fetch reviews for {forum_id}: {resp.status_code}")
            return []

        all_notes = resp.json().get("notes", [])
        reviews = []

        for note in all_notes:
            invitations = note.get("invitations", [])
            content = note.get("content", {})

            is_review_by_invitation = any(
                "Official_Review" in inv
                or "Paper_Review" in inv
                or ("/Review" in inv and "Meta" not in inv)
                for inv in invitations
            )

            has_review_content = bool(
                _val(content, "summary")
                or _val(content, "strengths")
                or _val(content, "weaknesses")
                or _val(content, "review")
                or _val(content, "rating")
            )

            is_not_submission = not any(
                "Submission" in inv and "Review" not in inv
                for inv in invitations
            )

            if (is_review_by_invitation or has_review_content) and is_not_submission:
                reviews.append(note)

        return reviews

    def _get_decision(self, forum_id: str) -> str:
        """Get the accept/reject decision for a paper."""
        params = {"forum": forum_id}
        url = f"{API_BASE}/notes?{urlencode(params)}"
        resp = rate_limited_fetch(url)

        if resp.status_code != 200:
            return "unknown"

        for note in resp.json().get("notes", []):
            invitations = note.get("invitations", [])
            is_decision = any(
                "Decision" in inv or "Acceptance" in inv
                for inv in invitations
            )

            if is_decision:
                decision_val = _val(note.get("content", {}), "decision")
                if decision_val:
                    lower = decision_val.lower()
                    if "accept" in lower:
                        return "accepted"
                    if "reject" in lower:
                        return "rejected"

            venue_val = _val(note.get("content", {}), "venue")
            if venue_val:
                lower = venue_val.lower()
                if any(w in lower for w in ("poster", "oral", "spotlight")):
                    return "accepted"
                if any(w in lower for w in ("reject", "withdrawn")):
                    return "rejected"

        return "unknown"