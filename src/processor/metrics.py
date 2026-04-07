"""Metric computation for multi-source comparison scoring.

Fetches assessment, claim, and comment data, then computes per-paper
metrics for each source.  Expose one public entry point:
``compute_metrics(venue_id) -> MetricsResult``.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

import numpy as np

from src.db.client import fetch_all
from src.processor.types import SOURCES


# ── Helpers ──────────────────────────────────────────────────────────────────

def _dominant_stance(stances: list[str]) -> str | None:
    if not stances:
        return None
    counts: dict[str, int] = {}
    for s in stances:
        counts[s] = counts.get(s, 0) + 1
    severity = {"CRITICAL": 2, "SUPPORTIVE": 1}
    sorted_items = sorted(counts.items(), key=lambda x: (x[1], severity.get(x[0], 0)), reverse=True)
    return sorted_items[0][0]


def _dominant_stances_per_claim(assessments: list[dict]) -> dict[str, str]:
    """Return {claim_id: dominant_stance} for assessments that have both claim_id and stance."""
    claim_stances: dict[str, list[str]] = {}
    for a in assessments:
        cid = a.get("claim_id")
        stance = a.get("stance")
        if cid and stance:
            claim_stances.setdefault(cid, []).append(stance)
    return {cid: ds for cid, sl in claim_stances.items() if (ds := _dominant_stance(sl))}



# ── Result container ─────────────────────────────────────────────────────────

@dataclass
class MetricsResult:
    metrics_by_source: dict[str, dict[str, list[float]]]
    paper_by_source: dict[str, dict[str, list[dict]]]
    all_assessments: dict[str, list[dict]]
    comments_by_source: dict[str, list[dict]]
    paper_ids: list[str]
    reviewer_conseq_rates: list[float]  # per-reviewer consequential rates for 5e


# ── Public API ───────────────────────────────────────────────────────────────

def compute_metrics(venue_id: str) -> MetricsResult | None:
    """Compute all per-paper metrics. Returns *None* when there is no data."""

    # ── 1. Bulk fetch (scoped to venue) ─────────────────────────────────
    all_assessment_rows = fetch_all(
        """SELECT a.* FROM assessments a
           JOIN papers p ON a.paper_id = p.id
           WHERE p.venue_id = %s
           ORDER BY a.paper_id, a.comment_id""",
        (venue_id,),
    )
    if not all_assessment_rows:
        print("No assessments found — nothing to score.")
        return None

    all_claim_rows = fetch_all(
        """SELECT c.* FROM claims c
           JOIN papers p ON c.paper_id = p.id
           WHERE p.venue_id = %s
           ORDER BY c.paper_id""",
        (venue_id,),
    )
    all_comment_rows = fetch_all(
        """SELECT c.id, c.paper_id, c.source, c.content FROM comments c
           JOIN papers p ON c.paper_id = p.id
           WHERE p.venue_id = %s
           ORDER BY c.paper_id""",
        (venue_id,),
    )

    # ── 2. Index data ────────────────────────────────────────────────────
    assessments_by_paper: dict[str, list[dict]] = defaultdict(list)
    for row in all_assessment_rows:
        assessments_by_paper[row["paper_id"]].append(row)

    claims_by_paper: dict[str, list[dict]] = defaultdict(list)
    for row in all_claim_rows:
        claims_by_paper[row["paper_id"]].append(row)

    comments_by_paper_source: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for row in all_comment_rows:
        comments_by_paper_source[row["paper_id"]][row["source"]].append(row)

    comments_by_source: dict[str, list[dict]] = defaultdict(list)
    for row in all_comment_rows:
        comments_by_source[row["source"]].append(row)

    paper_ids = sorted(assessments_by_paper.keys())

    all_assessments: dict[str, list[dict]] = {s: [] for s in SOURCES}

    paper_by_source: dict[str, dict[str, list[dict]]] = {}

    metrics_by_source: dict[str, dict[str, list[float]]] = {
        s: {
            "mapped_rate": [], "consequential_rate": [],
            "consequential_critical_rate": [], "specification_rate": [],
            "actionability_rate": [], "anchored_rate": [],
            "justification_rate": [],
            "claim_coverage": [], "comments_per_paper": [],
            "comment_length": [],
            "claim_overlap_fraction": [], "stance_matched_overlap_fraction": [],
        }
        for s in SOURCES
    }

    non_human = [s for s in SOURCES if s != "human"]

    # ── 3. Per-paper loop ─────────────────────────────────────────────────
    for paper_id in paper_ids:
        assessments = assessments_by_paper[paper_id]
        total_claims = len(claims_by_paper.get(paper_id, []))

        by_source: dict[str, list[dict]] = {s: [] for s in SOURCES}
        for a in assessments:
            source = a["source"]
            if source in by_source:
                by_source[source].append(a)
                all_assessments[source].append(a)

        paper_by_source[paper_id] = by_source

        claim_sets: dict[str, set[str]] = {s: set() for s in SOURCES}
        dominant_stances: dict[str, dict[str, str]] = {}

        for s in SOURCES:
            src_assessments = by_source[s]
            comments = comments_by_paper_source.get(paper_id, {}).get(s, [])
            n_assess = len(src_assessments)

            n_mapped = n_conseq_mapped = 0
            n_mapped_critical = n_conseq_mapped_critical = 0
            n_specification = n_remedy = n_anchor = n_justification = 0
            unique_claims: set[str] = set()
            claim_stance_lists: dict[str, list[str]] = {}

            for a in src_assessments:
                is_conseq = bool(a.get("is_consequential"))
                cid = a.get("claim_id")
                stance = a.get("stance")
                if cid:
                    n_mapped += 1
                    if is_conseq:
                        n_conseq_mapped += 1
                if cid and stance:
                    claim_stance_lists.setdefault(cid, []).append(stance)
                    if stance == "CRITICAL":
                        n_mapped_critical += 1
                        if is_conseq:
                            n_conseq_mapped_critical += 1
                if a.get("specification"):
                    n_specification += 1
                if a.get("remedy"):
                    n_remedy += 1
                if a.get("anchor"):
                    n_anchor += 1
                if a.get("justification"):
                    n_justification += 1
                if cid:
                    unique_claims.add(cid)

            ds = {cid: st for cid, sl in claim_stance_lists.items()
                  if (st := _dominant_stance(sl))}
            dominant_stances[s] = ds
            claim_sets[s] = unique_claims


            m = metrics_by_source[s]
            m["mapped_rate"].append(n_mapped / n_assess if n_assess else np.nan)
            m["consequential_rate"].append(n_conseq_mapped / n_mapped if n_mapped else np.nan)
            m["consequential_critical_rate"].append(n_conseq_mapped_critical / n_mapped_critical if n_mapped_critical else np.nan)
            m["specification_rate"].append(n_specification / n_assess if n_assess else np.nan)
            m["actionability_rate"].append(n_remedy / n_assess if n_assess else np.nan)
            m["anchored_rate"].append(n_anchor / n_assess if n_assess else np.nan)
            m["justification_rate"].append(n_justification / n_assess if n_assess else np.nan)
            m["claim_coverage"].append(len(unique_claims) / total_claims if total_claims else np.nan)
            m["comments_per_paper"].append(float(len(comments)))
            word_counts = [len((c.get("content") or "").split()) for c in comments if c.get("content")]
            m["comment_length"].append(np.mean(word_counts) if word_counts else np.nan)


        human_claims = claim_sets.get("human", set())
        human_ds = dominant_stances.get("human", {})
        for ai_src in non_human:
            ai_claims = claim_sets.get(ai_src, set())
            ai_ds = dominant_stances.get(ai_src, {})
            if human_claims:
                metrics_by_source[ai_src]["claim_overlap_fraction"].append(
                    len(ai_claims & human_claims) / len(human_claims))
            else:
                metrics_by_source[ai_src]["claim_overlap_fraction"].append(np.nan)
            if human_ds:
                shared = set(human_ds.keys()) & set(ai_ds.keys())
                matched = sum(1 for cid in shared if human_ds[cid] == ai_ds[cid])
                metrics_by_source[ai_src]["stance_matched_overlap_fraction"].append(
                    matched / len(human_ds))
            else:
                metrics_by_source[ai_src]["stance_matched_overlap_fraction"].append(np.nan)
        metrics_by_source["human"]["claim_overlap_fraction"].append(np.nan)
        metrics_by_source["human"]["stance_matched_overlap_fraction"].append(np.nan)

    # ── 4. Reviewer consequential rates (for 5e) ─────────────────────────
    reviewer_rows = fetch_all("""
        SELECT a.paper_id, a.claim_id, a.is_consequential,
               c.reviewer_id
        FROM assessments a
        JOIN comments c ON a.comment_id = c.id
        JOIN papers p ON a.paper_id = p.id
        WHERE a.source = 'human'
          AND c.reviewer_id IS NOT NULL
          AND p.venue_id = %s
    """, (venue_id,))

    reviewer_conseq_rates: list[float] = []
    if reviewer_rows:
        import pandas as pd
        rdf = pd.DataFrame(reviewer_rows)
        for (_rid, _pid), grp in rdf.groupby(["reviewer_id", "paper_id"]):
            n_mapped = int(grp["claim_id"].notna().sum())
            if n_mapped == 0:
                continue
            n_conseq = int(((grp["claim_id"].notna()) & (grp["is_consequential"] == True)).sum())
            reviewer_conseq_rates.append(n_conseq / n_mapped * 100)

    return MetricsResult(
        metrics_by_source=metrics_by_source,
        paper_by_source=paper_by_source,
        all_assessments=all_assessments,
        comments_by_source=dict(comments_by_source),
        paper_ids=paper_ids,
        reviewer_conseq_rates=reviewer_conseq_rates,
    )
