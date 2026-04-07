"""Export per-source, per-venue metric means to results/means.csv."""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.processor.metrics import compute_metrics
from src.processor.types import SOURCES, SOURCE_LABELS, VENUES, VENUE_LABELS, OUT_DIR


def export_means() -> None:
    rows = []

    for venue_id in VENUES:
        result = compute_metrics(venue_id)
        if result is None:
            continue

        # Metrics stored as ratios (0-1) that should be displayed as percentages
        pct_metrics = {
            "mapped_rate", "consequential_rate", "consequential_critical_rate",
            "specification_rate", "actionability_rate", "anchored_rate",
            "justification_rate", "claim_coverage", "claim_overlap_fraction",
            "stance_matched_overlap_fraction",
        }

        for s in SOURCES:
            label = SOURCE_LABELS[SOURCES.index(s)]
            for metric_key, values in result.metrics_by_source[s].items():
                arr = np.array(values)
                clean = arr[~np.isnan(arr)]
                if len(clean) == 0:
                    mean_val = None
                elif metric_key in pct_metrics:
                    mean_val = round(float(np.mean(clean)) * 100, 1)
                else:
                    mean_val = round(float(np.mean(clean)), 1)
                rows.append({
                    "venue": VENUE_LABELS[venue_id],
                    "source": label,
                    "metric": metric_key,
                    "mean": mean_val,
                    "n": len(clean),
                })

    df = pd.DataFrame(rows)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / "means.csv"
    df.to_csv(path, index=False)
    print(f"Saved {path}")


if __name__ == "__main__":
    export_means()
