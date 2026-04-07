"""eLife fetcher.

Loads manuscript and peer review content from db_export.json from each manuscript
folder in the cloned OpenEvalProject/evals repo. Stores the full payload as JSONB 
in raw_venue_data with venue_id='elife'.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from src.db.client import get_conn
from src.db.queries import get_raw_source_ids

BATCH_SIZE = 50


class ELifeFetcher:
    venue = "elife"

    async def fetch(self, limit: int = 1000, **kwargs) -> int:
        manuscripts_dir = kwargs.get("manuscripts_dir") or os.environ.get("ELIFE_MANUSCRIPTS_DIR")
        if not manuscripts_dir:
            raise RuntimeError(
                "No manuscripts directory specified. "
                "Clone https://github.com/OpenEvalProject/evals/ and set "
                "ELIFE_MANUSCRIPTS_DIR to the manuscripts/ folder path."
            )
        manuscripts_path = Path(manuscripts_dir)

        if not manuscripts_path.exists():
            raise FileNotFoundError(
                f"Manuscripts directory not found: {manuscripts_dir}. "
                "Ensure the path correctly points to the manuscripts/ folder "
                "within the cloned https://github.com/OpenEvalProject/evals/ repo."
            )

        existing_ids = get_raw_source_ids(self.venue)
        total_collected = 0
        batch: list[tuple[str, str, str]] = []  # (venue_id, source_id, payload_json)

        # Sort for deterministic ordering
        manuscript_dirs = sorted(manuscripts_path.iterdir())

        for mdir in manuscript_dirs:
            if total_collected >= limit:
                break

            db_export = mdir / "v1" / "db_export.json"
            if not db_export.exists():
                continue

            source_id = mdir.name

            if source_id in existing_ids:
                continue

            try:
                with open(db_export, "r") as f:
                    data = json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                print(f"  [skip] {source_id}: {e}")
                continue

            content_types = {
                item.get("content_type") for item in data.get("content", [])
            }
            if "manuscript" not in content_types or "peer_review" not in content_types:
                continue

            raw_payload = {
                "submission": data.get("submission", {}),
                "content": data.get("content", []),
                "folder_name": source_id,
            }

            batch.append((self.venue, source_id, json.dumps(raw_payload)))
            existing_ids.add(source_id)
            total_collected += 1

            if len(batch) >= BATCH_SIZE:
                self._flush_batch(batch)
                print(f"[{total_collected}] {source_id}")
                batch = []

        # Flush remaining
        if batch:
            self._flush_batch(batch)
            print(f"[{total_collected}] done")

        print(f"\nFetched {total_collected} manuscripts for {self.venue}")
        return total_collected

    @staticmethod
    def _flush_batch(batch: list[tuple[str, str, str]]) -> None:
        with get_conn() as conn:
            for venue_id, source_id, payload_json in batch:
                conn.execute(
                    """INSERT INTO raw_venue_data (venue_id, source_id, raw_payload)
                       VALUES (%s, %s, %s::jsonb)
                       ON CONFLICT (venue_id, source_id) DO UPDATE SET
                         raw_payload = EXCLUDED.raw_payload""",
                    (venue_id, source_id, payload_json),
                )
