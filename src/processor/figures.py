"""Figure generation for multi-venue comparison scoring.

All plotting code lives here.  The single public entry point is ``generate_figures(all_venue_data)``.
"""

from __future__ import annotations

import matplotlib
matplotlib.use("Agg")
matplotlib.rcParams.update({"font.size": 14})
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

sns.set_theme(style="white", font_scale=1.4, palette="muted")

from src.processor.types import (
    SOURCES, SOURCE_PAIRS, SOURCE_LABELS, STANCES,
    VENUES, VENUE_LABELS, OUT_DIR,
)

# ── Constants ────────────────────────────────────────────────────────────────

COLORS = ["#4C78A8", "#E45756", "#A0A0A0", "#D0D0D0"]
STANCE_COLORS = ["#59A14F", "#E45756", "#EDC948"]

PALETTE = dict(zip(SOURCE_LABELS, COLORS))

CRITIQUE_TYPE_ORDER = [
    "validity", "sufficiency", "contribution", "clarity", "transparency",
]
CRITIQUE_TYPE_LABELS = [
    "Validity", "Sufficiency", "Contribution", "Clarity", "Transparency",
]


# ── Helpers ──────────────────────────────────────────────────────────────────

def _save(fig, name: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT_DIR / name, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved {name}")


def _venues(all_venue_data: dict) -> list[str]:
    """Return venue IDs in canonical order."""
    return [v for v in VENUES if v in all_venue_data]


def _source_df(per_paper_vectors: dict, metric_key: str, scale: float = 100.0,
               sources: list[str] | None = None) -> pd.DataFrame:
    srcs = sources or SOURCES
    rows = []
    for s in srcs:
        lbl = SOURCE_LABELS[SOURCES.index(s)]
        for v in per_paper_vectors[metric_key][s]:
            if not np.isnan(v):
                rows.append({"source": lbl, "value": v * scale})
    return pd.DataFrame(rows)


def _p_to_stars(p: float) -> str:
    if p < 0.001:
        return "***"
    elif p < 0.01:
        return "**"
    elif p < 0.05:
        return "*"
    return "n.s."


def _annotate_all_pairs(
    ax,
    metric_key: str,
    ann_lookups: tuple[dict, dict],
    df: pd.DataFrame,
    sources: list[str] | None = None,
) -> None:
    from statannotations.Annotator import Annotator

    srcs = sources or SOURCES
    src_set = set(srcs)
    cohen_d_lookup, p_adj_lookup = ann_lookups
    order = [SOURCE_LABELS[SOURCES.index(s)] for s in srcs]
    pairs_and_p = []
    for a_src, b_src in SOURCE_PAIRS:
        if a_src not in src_set or b_src not in src_set:
            continue
        la = SOURCE_LABELS[SOURCES.index(a_src)]
        lb = SOURCE_LABELS[SOURCES.index(b_src)]
        d = cohen_d_lookup.get((metric_key, a_src, b_src))
        p = p_adj_lookup.get((metric_key, a_src, b_src))
        if d is not None and p is not None and p < 0.05:
            pairs_and_p.append(((la, lb), p))
    if not pairs_and_p:
        return
    valid_pairs, p_values = zip(*pairs_and_p)
    ann = Annotator(ax, list(valid_pairs), data=df, x="source", y="value", order=order)
    ann.configure(test=None, text_format="simple", loc="inside", verbose=0)
    ann.set_custom_annotations([_p_to_stars(p) for p in p_values])
    ann.annotate()


def _get_ann(vd: dict) -> tuple[dict, dict]:
    return (vd["cohen_d_lookup"], vd["p_adj_lookup"])


# ── Multi-venue bar metric ─────────────────────────────────────────────────

def _bar_metric(
    all_venue_data: dict,
    metric_key: str,
    ylabel: str,
    filename: str,
    label: str = "",
    scale: float = 100.0,
    sources: list[str] | None = None,
    bounded: bool = False,
    ymax: float | None = None,
) -> None:
    if label:
        print(label)
    venues = _venues(all_venue_data)
    n = len(venues)
    srcs = sources or SOURCES
    src_labels = [SOURCE_LABELS[SOURCES.index(s)] for s in srcs]
    palette = {SOURCE_LABELS[SOURCES.index(s)]: COLORS[SOURCES.index(s)] for s in srcs}

    fig, axes = plt.subplots(1, n, figsize=(7 * n, 5), sharey=False)
    if n == 1:
        axes = [axes]

    for i, venue_id in enumerate(venues):
        ax = axes[i]
        vd = all_venue_data[venue_id]
        df = _source_df(vd["per_paper_vectors"], metric_key, scale=scale, sources=srcs)
        sns.barplot(data=df, x="source", y="value", hue="source", palette=palette,
                    order=src_labels, errorbar="ci", capsize=0.1, legend=False, ax=ax)
        ax.set_xlabel("")
        ax.set_ylabel(ylabel if i == 0 else "")
        ax.set_title(VENUE_LABELS[venue_id], fontsize=16, fontweight="bold")
        _annotate_all_pairs(ax, metric_key, _get_ann(vd), df, sources=srcs)
        if bounded:
            ax.set_yticks(np.arange(0, 101, 20))
        elif ymax is not None:
            ax.set_yticks(np.arange(0, ymax + 1))

    fig.tight_layout()
    _save(fig, filename)


# ── KDE metric ───────────

def _kde_metric(
    all_venue_data: dict,
    metric_key: str,
    xlabel: str,
    filename: str,
    label: str = "",
    scale: float = 100.0,
) -> None:
    if label:
        print(label)
    venues = _venues(all_venue_data)
    n = len(venues)

    fig, axes = plt.subplots(1, n, figsize=(8 * n, 5), sharey=False)
    if n == 1:
        axes = [axes]

    bins = np.arange(0, 110, 10)
    midpoints = (bins[:-1] + bins[1:]) / 2

    for i, venue_id in enumerate(venues):
        ax = axes[i]
        vd = all_venue_data[venue_id]
        for si, s in enumerate(SOURCES):
            vals = vd["per_paper_vectors"][metric_key][s]
            rates = [v * scale for v in vals if not np.isnan(v)]
            if len(rates) >= 2:
                counts, _ = np.histogram(rates, bins=bins)
                ax.plot(midpoints, counts, color=COLORS[si], linewidth=2,
                        marker="o", markersize=5,
                        label=f"{SOURCE_LABELS[si]} (n={len(rates)})")
        ax.set_xlabel(xlabel)
        ax.set_ylabel("Count" if i == 0 else "")
        ax.set_title(VENUE_LABELS[venue_id], fontsize=16, fontweight="bold")
        ax.legend()

    fig.tight_layout()
    _save(fig, filename)


# ── Multi-venue ranking chart ──────────────────────────────────────────────

def _ranking_chart(
    all_venue_data: dict,
    metric_key: str,
    ylabel: str,
    filename: str,
    label: str = "",
) -> None:
    if label:
        print(label)
    venues = _venues(all_venue_data)
    n = len(venues)

    fig, axes = plt.subplots(1, n, figsize=(8 * n, 5), sharey=False)
    if n == 1:
        axes = [axes]

    rank_colors = ["#2ca02c", "#98df8a", "#ffbb78", "#d62728"]
    rank_labels = ["Rank 1 (best)", "Rank 2", "Rank 3", "Rank 4"]

    for vi, venue_id in enumerate(venues):
        ax = axes[vi]
        vd = all_venue_data[venue_id]
        data = vd["per_paper_vectors"][metric_key]
        n_papers = len(data[SOURCES[0]])

        rank_counts: dict[str, list[int]] = {s: [0, 0, 0, 0] for s in SOURCES}
        for i in range(n_papers):
            rates: dict[str, float] = {}
            for s in SOURCES:
                v = data[s][i]
                if not np.isnan(v):
                    rates[s] = v
            if len(rates) < 2:
                continue
            ranked = sorted(rates, key=rates.get, reverse=True)
            for rank, s in enumerate(ranked):
                rank_counts[s][rank] += 1

        x = np.arange(len(SOURCES))
        bottom = np.zeros(len(SOURCES))
        for rank_idx in range(4):
            vals = [rank_counts[s][rank_idx] for s in SOURCES]
            ax.bar(x, vals, 0.5, bottom=bottom, color=rank_colors[rank_idx],
                   label=rank_labels[rank_idx] if vi == 0 else "")
            for j, (v, b) in enumerate(zip(vals, bottom)):
                if v > 0:
                    ax.text(x[j], b + v / 2, str(v), ha="center", va="center",
                            fontsize=14, fontweight="bold", color="white")
            bottom += np.array(vals)

        ax.set_xticks(x)
        ax.set_xticklabels(SOURCE_LABELS)
        ax.set_ylabel(ylabel if vi == 0 else "")
        ax.set_title(VENUE_LABELS[venue_id], fontsize=16, fontweight="bold")

    axes[0].legend(fontsize=14)
    fig.tight_layout()
    _save(fig, filename)


# ── Section 1: Overview ─────────────────────────────────────────────────────

def _fig_1a(all_venue_data: dict) -> None:
    print("1a. Total comments...")
    venues = _venues(all_venue_data)
    n = len(venues)
    fig, axes = plt.subplots(1, n, figsize=(7 * n, 5), sharey=False)
    if n == 1:
        axes = [axes]

    for i, venue_id in enumerate(venues):
        ax = axes[i]
        vd = all_venue_data[venue_id]
        comments_by_source = vd["comments_by_source"]
        df = pd.DataFrame({
            "source": SOURCE_LABELS,
            "count": [len(comments_by_source.get(s, [])) for s in SOURCES],
        })
        sns.barplot(data=df, x="source", y="count", hue="source", palette=PALETTE,
                    order=SOURCE_LABELS, legend=False, ax=ax)
        for container in ax.containers:
            ax.bar_label(container, fmt="%d", padding=5)
        ax.set_xlabel("")
        ax.set_ylabel("Total Comments" if i == 0 else "")
        ax.set_title(VENUE_LABELS[venue_id], fontsize=16, fontweight="bold")
        ax.set_ylim(0, ax.get_ylim()[1] * 1.1)

    fig.tight_layout()
    _save(fig, "1a_total_comments.png")


# ── Section 4: Stance ───────────────────────────────────────────────────────

def _fig_4a_stance(all_venue_data: dict) -> None:
    print("4a. Stance distribution...")
    venues = _venues(all_venue_data)
    n = len(venues)
    fig, axes = plt.subplots(1, n, figsize=(8 * n, 5), sharey=True)
    if n == 1:
        axes = [axes]

    for i, venue_id in enumerate(venues):
        ax = axes[i]
        vd = all_venue_data[venue_id]
        rows = []
        for s in SOURCES:
            with_stance = [a for a in vd["all_assessments"][s] if a.get("stance")]
            total = len(with_stance)
            for st in STANCES:
                cnt = sum(1 for a in with_stance if a["stance"] == st)
                rows.append({
                    "source": SOURCE_LABELS[SOURCES.index(s)],
                    "stance": st,
                    "pct": cnt / total * 100 if total > 0 else 0,
                })
        df = pd.DataFrame(rows)
        sns.barplot(data=df, x="source", y="pct", hue="stance",
                    palette=dict(zip(STANCES, STANCE_COLORS)), order=SOURCE_LABELS,
                    hue_order=STANCES, ax=ax, legend=(i == 0))
        for container in ax.containers:
            ax.bar_label(container, fmt="%.1f%%", fontsize=12, padding=2)
        ax.set_xlabel("")
        ax.set_ylabel("Comment Stance Distribution (%)" if i == 0 else "")
        ax.set_title(VENUE_LABELS[venue_id], fontsize=16, fontweight="bold")
        ax.set_yticks(np.arange(0, 101, 20))
        if i == 0:
            ax.legend(fontsize=14)

    fig.tight_layout()
    _save(fig, "4a_stance_distribution.png")


def _fig_4b_stance_agree(all_venue_data: dict) -> None:
    print("4b. Stance agreement by human stance...")
    venues = _venues(all_venue_data)
    n = len(venues)
    ai_sources = [s for s in SOURCES if s != "human"]
    ai_labels = [SOURCE_LABELS[SOURCES.index(s)] for s in ai_sources]

    fig, axes = plt.subplots(1, n, figsize=(8 * n, 6), sharey=True)
    if n == 1:
        axes = [axes]

    for i, venue_id in enumerate(venues):
        ax = axes[i]
        vd = all_venue_data[venue_id]
        df = vd["stance_agree_df"]
        sig_pairs = vd["stance_agree_sig"]

        sns.barplot(data=df, x="AI Source", y="Agreement with Human Stance (%)", hue="Human Stance",
                    palette=dict(zip(STANCES, STANCE_COLORS)), hue_order=STANCES,
                    order=ai_labels, ax=ax, legend=(i == 0))
        for container in ax.containers:
            ax.bar_label(container, fmt="%.1f%%", fontsize=12, padding=2)

        significant = [(a, b, p) for a, b, d, p in sig_pairs if p < 0.05]
        if significant:
            crit_idx = STANCES.index("CRITICAL")
            crit_container = ax.containers[crit_idx]
            bar_xs = {ai_sources[j]: crit_container[j].get_x() + crit_container[j].get_width() / 2
                      for j in range(len(ai_sources))}
            ax.set_ylim(0, 130)
            ax.set_yticks(np.arange(0, 101, 20))
            base_y = 105
            y_step = 8
            for k, (a, b, p) in enumerate(significant):
                y = base_y + k * y_step
                x1, x2 = bar_xs[a], bar_xs[b]
                ax.plot([x1, x1, x2, x2], [y, y + 2, y + 2, y],
                        color="black", linewidth=0.8)
                ax.text((x1 + x2) / 2, y + 2.5, _p_to_stars(p),
                        ha="center", va="bottom", fontsize=14)

        ax.set_xlabel("")
        ax.set_ylabel("Agreement with Human Stance (%)" if i == 0 else "")
        ax.set_title(VENUE_LABELS[venue_id], fontsize=16, fontweight="bold")
        if i == 0:
            ax.legend(title="Human Stance", fontsize=14, loc="upper left")

    fig.tight_layout()
    _save(fig, "4b_stance_agreement.png")


# ── Section 5: Consequential Comment Rates ──────────────────────────────────

def _fig_6a_reviewer_hist(all_venue_data: dict) -> None:
    print("6a. Per-reviewer consequential rate distribution...")
    venues = _venues(all_venue_data)
    n = len(venues)

    fig, axes = plt.subplots(1, n, figsize=(8 * n, 5), sharey=False)
    if n == 1:
        axes = [axes]

    bins = np.arange(0, 110, 10)

    for i, venue_id in enumerate(venues):
        ax = axes[i]
        vd = all_venue_data[venue_id]
        human_rates = np.array(vd["reviewer_conseq_rates"] or [])

        if len(human_rates) < 2:
            ax.text(0.5, 0.5, "Insufficient data", ha="center", va="center",
                    transform=ax.transAxes, fontsize=14)
            ax.set_title(VENUE_LABELS[venue_id], fontsize=16, fontweight="bold")
            continue

        ax.hist(human_rates, bins=bins, color=COLORS[0], alpha=0.5, edgecolor="white",
                label=f"Human reviewers (n={len(human_rates)})")

        if "consequential_rate" in vd["per_paper_vectors"]:
            ai_sources = [s for s in SOURCES if s != "human"]
            for s in ai_sources:
                idx = SOURCES.index(s)
                vals = np.array(vd["per_paper_vectors"]["consequential_rate"][s])
                clean = vals[~np.isnan(vals)]
                if len(clean) > 0:
                    mean_val = float(np.mean(clean)) * 100
                    ax.axvline(mean_val, color=COLORS[idx], linestyle="--", linewidth=2,
                               label=f"{SOURCE_LABELS[idx]} mean ({mean_val:.1f}%)")

        ax.set_xlabel("Consequential Rate (%)")
        ax.set_ylabel("Count" if i == 0 else "")
        ax.set_title(VENUE_LABELS[venue_id], fontsize=16, fontweight="bold")
        ax.legend()

    fig.tight_layout()
    _save(fig, "6a_dist_consequential_per_reviewer.png")


# ── Section 6: Critique Type ────────────────────────────────────────────────

def _fig_7a_critique_type(all_venue_data: dict) -> None:
    print("6a. Critique type breakdown...")
    venues = _venues(all_venue_data)
    n = len(venues)

    fig, axes = plt.subplots(1, n, figsize=(8 * n, 8), sharey=True)
    if n == 1:
        axes = [axes]

    for i, venue_id in enumerate(venues):
        ax = axes[i]
        vd = all_venue_data[venue_id]
        rows = []
        for si, s in enumerate(SOURCES):
            total = len(vd["all_assessments"][s])
            for ct, ctl in zip(CRITIQUE_TYPE_ORDER, CRITIQUE_TYPE_LABELS):
                cnt = sum(1 for a in vd["all_assessments"][s] if a.get("critique_type") == ct)
                rows.append({"critique_type": ctl, "source": SOURCE_LABELS[si],
                             "pct": cnt / total * 100 if total > 0 else 0})
        df = pd.DataFrame(rows)
        sns.barplot(data=df, y="critique_type", x="pct", hue="source", orient="h",
                    palette=PALETTE, order=CRITIQUE_TYPE_LABELS, hue_order=SOURCE_LABELS,
                    ax=ax, legend=(i == 0))
        ax.set_ylabel("")
        ax.set_xlabel("Critique Type Distribution (%)")
        ax.set_title(VENUE_LABELS[venue_id], fontsize=16, fontweight="bold")
        if i == 0:
            ax.legend()

    fig.tight_layout()
    _save(fig, "7a_critique_type_breakdown.png")



# ── Public orchestrator ──────────────────────────────────────────────────────

def generate_figures(all_venue_data: dict[str, dict]) -> None:
    """Generate all multi-venue comparison figures."""
    print("\n=== Generating multi-venue figures ===")
    AI_SOURCES = [s for s in SOURCES if s != "human"]

    print("\n--- Section 1: Overview ---")
    _fig_1a(all_venue_data)
    _bar_metric(all_venue_data, "comments_per_paper",
                "Average Comments Per Paper",
                "1b_comments_per_paper.png", "1b. Comments per paper...", scale=1.0)
    _bar_metric(all_venue_data, "comment_length",
                "Average Comment Length (Words)",
                "1c_comment_length.png", "1c. Comment length...", scale=1.0)

    print("\n--- Section 2: Comment Makeup ---")
    _bar_metric(all_venue_data, "specification_rate",
                "Specification Rate (%) Per Paper",
                "2a_specification.png", "2a. Specification rate...", bounded=True)
    _bar_metric(all_venue_data, "justification_rate",
                "Justification Rate (%) Per Paper",
                "2b_justification.png", "2b. Justification rate...", bounded=True)
    _bar_metric(all_venue_data, "actionability_rate",
                "Actionability Rate (%) Per Paper",
                "2c_actionability.png", "2c. Actionability...", bounded=True)
    _bar_metric(all_venue_data, "anchored_rate",
                "Anchored Rate (%) Per Paper",
                "2d_anchored.png", "2d. Anchored rate...", bounded=True)

    print("\n--- Section 3: Claim Mappings ---")
    _bar_metric(all_venue_data, "mapped_rate",
                "Comments Mapped to Claim (%) Per Paper",
                "3a_mapped_vs_unmapped.png", "3a. Mapped rate...", bounded=True)
    _bar_metric(all_venue_data, "claim_coverage",
                "Claim Coverage (%) Per Paper",
                "3b_claim_coverage.png", "3b. Claim coverage...", bounded=True)
    _bar_metric(all_venue_data, "claim_overlap_fraction",
                "Claim Overlap (%) Per Paper",
                "3c_avg_claim_overlap.png", "3c. Avg claim overlap...",
                sources=AI_SOURCES, bounded=True)
    _ranking_chart(all_venue_data, "claim_overlap_fraction",
                   "Number of Papers",
                   "3d_ranking_claim_overlap.png",
                   "3d. Ranking claim overlap fraction...")

    print("\n--- Section 4: Stance ---")
    _fig_4a_stance(all_venue_data)
    _fig_4b_stance_agree(all_venue_data)
    _bar_metric(all_venue_data, "stance_matched_overlap_fraction",
                "Stance-Matched Overlap (%) Per Paper",
                "4c_avg_stance_matched_overlap.png", "4c. Avg stance-matched overlap...",
                sources=AI_SOURCES, bounded=True)
    _ranking_chart(all_venue_data, "stance_matched_overlap_fraction",
                   "Number of Papers",
                   "4d_ranking_stance_matched_overlap.png",
                   "4d. Ranking stance-matched overlap fraction...")

    print("\n--- Section 5: Consequential Rates ---")
    _bar_metric(all_venue_data, "consequential_rate",
                "Consequential Rate (%) Per Paper",
                "5a_consequential_rates.png",
                "5a. Consequential rate (mapped denominator)...", bounded=True)
    _kde_metric(all_venue_data, "consequential_rate",
                "Consequential Rate (%) Per Paper",
                "5b_dist_consequential_mapped_per_paper.png",
                "5b. Per-paper consequential comment rate distribution (mapped)...")
    _bar_metric(all_venue_data, "consequential_critical_rate",
                "Consequential Rate (Critical Only) (%)",
                "5c_consequential_critical_rates.png",
                "5c. Consequential rate (critical only)...", bounded=True)
    _kde_metric(all_venue_data, "consequential_critical_rate",
                "Consequential Rate (Critical Only) (%)",
                "5d_dist_consequential_critical_per_paper.png",
                "5d. Per-paper consequential rate (critical only) distribution...")
    print("\n--- Section 6: Human Reviewer Variability ---")
    _fig_6a_reviewer_hist(all_venue_data)
    _ranking_chart(all_venue_data, "consequential_rate",
                   "Number of Papers",
                   "6b_per_paper_ranking_mapped.png",
                   "6b. Per-paper ranking (consequential mapped rate)...")
    _ranking_chart(all_venue_data, "consequential_critical_rate",
                   "Number of Papers",
                   "6c_per_paper_ranking_critical.png",
                   "6c. Per-paper ranking (consequential rate, critical only)...")

    print("\n--- Section 7: Critique Type ---")
    _fig_7a_critique_type(all_venue_data)
    print(f"\nAll figures saved to {OUT_DIR}/")
