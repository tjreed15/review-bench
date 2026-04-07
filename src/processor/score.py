"""Multi-source comparison scoring + visualization.

Thin orchestrator that delegates to:
- ``metrics`` for metric computation
- ``statistics`` for statistical tests
- ``figures`` for all plotting
"""

from __future__ import annotations

import numpy as np

from src.processor.types import SOURCES, VENUES


def score_all_venues() -> None:
    """Compute metrics for all venues and generate multi-venue figures."""
    from src.processor.metrics import compute_metrics
    from src.processor.statistics import (
        compute_statistics, compute_stance_agreement,
        compute_cohens_kappa, write_stats_csv,
    )
    from src.processor.figures import generate_figures

    all_venue_data: dict[str, dict] = {}

    for venue_id in VENUES:
        print(f"\n{'='*60}")
        print(f"Scoring venue: {venue_id}")
        print(f"{'='*60}")

        result = compute_metrics(venue_id)
        if result is None:
            print(f"  Skipping {venue_id} — no data")
            continue

        print("\n=== Computing statistical comparisons ===")
        stat_results = compute_statistics(result.metrics_by_source, venue_id=venue_id)
        print(f"  {len(stat_results)} pairwise tests computed")

        cohen_d_lookup: dict[tuple[str, str, str], float] = {
            (r["metric_key"], r["src_a"], r["src_b"]): r["cohen_d"]
            for r in stat_results
            if not np.isnan(r.get("cohen_d", float("nan")))
        }
        p_adj_lookup: dict[tuple[str, str, str], float] = {
            (r["metric_key"], r["src_a"], r["src_b"]): r["p_adj"]
            for r in stat_results
            if not np.isnan(r.get("p_adj", float("nan")))
        }

        all_metric_keys = list(result.metrics_by_source[SOURCES[0]].keys())
        per_paper_vectors: dict[str, dict[str, list[float]]] = {
            mk: {s: result.metrics_by_source[s][mk] for s in SOURCES}
            for mk in all_metric_keys
        }

        stance_agree_df, stance_agree_sig, stance_stat_results = compute_stance_agreement(
            result.paper_by_source, result.paper_ids,
        )
        stat_results.extend(stance_stat_results)
        write_stats_csv(stat_results, venue_id=venue_id)
        compute_cohens_kappa(result.paper_by_source, result.paper_ids, venue_id=venue_id)

        all_venue_data[venue_id] = dict(
            all_assessments=result.all_assessments,
            comments_by_source=result.comments_by_source,
            cohen_d_lookup=cohen_d_lookup,
            p_adj_lookup=p_adj_lookup,
            per_paper_vectors=per_paper_vectors,
            stance_agree_df=stance_agree_df,
            stance_agree_sig=stance_agree_sig,
            reviewer_conseq_rates=result.reviewer_conseq_rates,
        )

    if not all_venue_data:
        print("No venue data — nothing to plot.")
        return

    generate_figures(all_venue_data)
