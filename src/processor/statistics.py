"""Statistical tests for multi-source comparison scoring.

Provides:
- ``compute_statistics`` — pairwise Wilcoxon tests with Holm-Bonferroni correction
- ``compute_stance_agreement`` — stance agreement data + Wilcoxon tests
- ``compute_cohens_kappa`` — Cohen's kappa for critical stance agreement
- ``write_stats_csv`` — write pairwise test results to CSV
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import shapiro, wilcoxon

from src.processor.types import SOURCES, SOURCE_PAIRS, SOURCE_LABELS, STANCES, OUT_DIR

from src.processor.metrics import _dominant_stances_per_claim


def write_stats_csv(stat_results: list[dict], venue_id: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{venue_id}_stats.csv"
    fields = ["metric", "pair", "mean_a", "mean_b", "diff", "ci_lo", "ci_hi", "p_raw", "p_adj", "cohen_d", "n"]
    pd.DataFrame([{k: r.get(k, "") for k in fields} for r in stat_results]).to_csv(path, index=False)
    print(f"  Stats written to {path}")


def compute_statistics(
    metrics_by_source: dict[str, dict[str, list[float]]],
    venue_id: str = "",
) -> list[dict]:
    """Run statistical tests on pre-built per-paper metric vectors."""
    rng = np.random.default_rng(42)

    # ── Shapiro-Wilk normality tests ─────────────────────────────────
    shapiro_rows: list[dict] = []
    for s in SOURCES:
        lbl = SOURCE_LABELS[SOURCES.index(s)]
        for metric_key in metrics_by_source[s]:
            vals = np.array(metrics_by_source[s][metric_key])
            clean = vals[~np.isnan(vals)]
            if len(clean) >= 20:
                stat, p = shapiro(clean)
                shapiro_rows.append({
                    "source": lbl, "metric": metric_key,
                    "W": stat, "p": p, "n": len(clean),
                    "rejected": p < 0.05,
                })
    n_rejected = sum(1 for r in shapiro_rows if r["rejected"])
    n_total = len(shapiro_rows)
    print(f"  Shapiro-Wilk normality: {n_rejected}/{n_total} distributions rejected at p < .05")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    shapiro_path = OUT_DIR / f"{venue_id}_shapiro_wilk.csv"
    pd.DataFrame(shapiro_rows, columns=["source", "metric", "W", "p", "n", "rejected"]).to_csv(shapiro_path, index=False)
    print(f"  Saved {shapiro_path}")

    # ── Pairwise tests ────────────────────────────────────────────────
    metric_labels = {
        "mapped_rate": "Mapped rate",
        "consequential_rate": "Consequential comment rate",
        "consequential_critical_rate": "Consequential rate (critical only)",
        "specification_rate": "Specification rate",
        "actionability_rate": "Actionability rate",
        "anchored_rate": "Anchored rate",
        "justification_rate": "Justification rate",
        "claim_coverage": "Claim coverage",
        "comments_per_paper": "Comments per paper",
        "comment_length": "Comment length (words)",

        "claim_overlap_fraction": "Claim overlap fraction with human",
        "stance_matched_overlap_fraction": "Stance-matched overlap fraction with human",
    }

    results: list[dict] = []

    for metric_key, metric_name in metric_labels.items():
        if metric_key not in metrics_by_source[SOURCES[0]]:
            continue
        pair_results: list[dict] = []

        for a_src, b_src in SOURCE_PAIRS:
            vals_a = np.array(metrics_by_source[a_src][metric_key])
            vals_b = np.array(metrics_by_source[b_src][metric_key])

            valid = ~np.isnan(vals_a) & ~np.isnan(vals_b)
            va = vals_a[valid]
            vb = vals_b[valid]
            n = len(va)

            if n < 2:
                pair_results.append({
                    "metric": metric_name, "metric_key": metric_key,
                    "src_a": a_src, "src_b": b_src,
                    "pair": f"{SOURCE_LABELS[SOURCES.index(a_src)]} vs {SOURCE_LABELS[SOURCES.index(b_src)]}",
                    "mean_a": np.nan, "mean_b": np.nan,
                    "diff": np.nan, "ci_lo": np.nan, "ci_hi": np.nan,
                    "p_raw": np.nan, "p_adj": np.nan, "cohen_d": np.nan, "n": n,
                })
                continue

            diff = va - vb
            mean_diff = float(np.mean(diff))
            mean_a = float(np.mean(va))
            mean_b = float(np.mean(vb))

            # Bootstrap 95% confidence interval
            boot_diffs = np.empty(10_000)
            for i in range(10_000):
                idx = rng.integers(0, n, size=n)
                boot_diffs[i] = np.mean(diff[idx])
            ci_lo = float(np.percentile(boot_diffs, 2.5))
            ci_hi = float(np.percentile(boot_diffs, 97.5))

            # Wilcoxon signed-rank test
            try:
                _, p_val = wilcoxon(va, vb)
            except ValueError:
                p_val = 1.0

            # Cohen's d (effect size)
            pooled_std = np.sqrt((np.std(va, ddof=1) ** 2 + np.std(vb, ddof=1) ** 2) / 2)
            cohen_d = float((mean_a - mean_b) / pooled_std) if pooled_std > 0 else 0.0

            pair_results.append({
                "metric": metric_name, "metric_key": metric_key,
                "src_a": a_src, "src_b": b_src,
                "pair": f"{SOURCE_LABELS[SOURCES.index(a_src)]} vs {SOURCE_LABELS[SOURCES.index(b_src)]}",
                "mean_a": mean_a, "mean_b": mean_b,
                "diff": mean_diff, "ci_lo": ci_lo, "ci_hi": ci_hi,
                "p_raw": p_val, "p_adj": p_val,
                "cohen_d": cohen_d,
                "n": n,
            })

        results.extend(pair_results)

    # Holm-Bonferroni correction
    valid = [r for r in results if not np.isnan(r["p_raw"])]
    if valid:
        sorted_by_p = sorted(valid, key=lambda r: r["p_raw"])
        m = len(sorted_by_p)
        for rank, r in enumerate(sorted_by_p):
            r["p_adj"] = min(r["p_raw"] * (m - rank), 1.0)
        for i in range(1, len(sorted_by_p)):
            if sorted_by_p[i]["p_adj"] < sorted_by_p[i - 1]["p_adj"]:
                sorted_by_p[i]["p_adj"] = sorted_by_p[i - 1]["p_adj"]

    return results


def compute_stance_agreement(
    paper_by_source: dict[str, dict[str, list[dict]]],
    paper_ids: list[str],
) -> tuple[pd.DataFrame, list[tuple[str, str, float, float]]]:
    """Compute stance agreement data and Wilcoxon tests for fig 4b."""
    ai_sources = [s for s in SOURCES if s != "human"]

    agg: dict[tuple[str, str], tuple[int, int]] = {}
    for ai_src in ai_sources:
        for st in STANCES:
            agg[(ai_src, st)] = (0, 0)

    crit_agree_per_paper: dict[str, dict[str, float]] = {s: {} for s in ai_sources}

    for pid in paper_ids:
        by_source = paper_by_source.get(pid, {})
        human_stances = _dominant_stances_per_claim(by_source.get("human", []))

        for ai_src in ai_sources:
            ai_stances = _dominant_stances_per_claim(by_source.get(ai_src, []))
            shared = set(human_stances.keys()) & set(ai_stances.keys())
            crit_agree = 0
            crit_total = 0
            for cid in shared:
                hs = human_stances[cid]
                ais = ai_stances[cid]
                old_agree, old_total = agg[(ai_src, hs)]
                agg[(ai_src, hs)] = (old_agree + (1 if ais == hs else 0), old_total + 1)
                if hs == "CRITICAL":
                    crit_total += 1
                    if ais == "CRITICAL":
                        crit_agree += 1

            if crit_total > 0:
                crit_agree_per_paper[ai_src][pid] = crit_agree / crit_total

    rows = []
    for ai_src in ai_sources:
        ai_label = SOURCE_LABELS[SOURCES.index(ai_src)]
        for st in STANCES:
            agree, total = agg[(ai_src, st)]
            rows.append({
                "AI Source": ai_label,
                "Human Stance": st,
                "Agreement with Human Stance (%)": agree / total * 100 if total > 0 else 0,
                "n": total,
            })
    df = pd.DataFrame(rows)

    ai_pairs = [(ai_sources[i], ai_sources[j])
                for i in range(len(ai_sources)) for j in range(i + 1, len(ai_sources))]
    test_results = []
    for a, b in ai_pairs:
        shared_pids = sorted(set(crit_agree_per_paper[a].keys()) & set(crit_agree_per_paper[b].keys()))
        va = np.array([crit_agree_per_paper[a][pid] for pid in shared_pids])
        vb = np.array([crit_agree_per_paper[b][pid] for pid in shared_pids])
        min_n = len(shared_pids)
        diff = va - vb
        if np.any(diff != 0) and min_n > 10:
            stat, p = wilcoxon(diff)
            pooled_sd = np.sqrt((np.var(va, ddof=1) + np.var(vb, ddof=1)) / 2)
            d = (np.mean(va) - np.mean(vb)) / pooled_sd if pooled_sd > 0 else 0.0
            test_results.append((a, b, d, p))

    sig_pairs: list[tuple[str, str, float, float]] = []
    if test_results:
        test_results.sort(key=lambda x: x[3])
        m = len(test_results)
        for i, (a, b, d, p) in enumerate(test_results):
            sig_pairs.append((a, b, d, min(p * (m - i), 1.0)))

    # Build stats-compatible results for CSV export
    stat_results: list[dict] = []
    for a, b, d, p_adj in sig_pairs:
        shared_pids = sorted(set(crit_agree_per_paper[a].keys()) & set(crit_agree_per_paper[b].keys()))
        va = np.array([crit_agree_per_paper[a][pid] for pid in shared_pids])
        vb = np.array([crit_agree_per_paper[b][pid] for pid in shared_pids])
        stat_results.append({
            "metric": "Stance agreement (critical)",
            "metric_key": "stance_agreement_critical",
            "src_a": a, "src_b": b,
            "pair": f"{SOURCE_LABELS[SOURCES.index(a)]} vs {SOURCE_LABELS[SOURCES.index(b)]}",
            "mean_a": float(np.mean(va)), "mean_b": float(np.mean(vb)),
            "diff": float(np.mean(va) - np.mean(vb)),
            "ci_lo": np.nan, "ci_hi": np.nan,
            "p_raw": np.nan, "p_adj": p_adj,
            "cohen_d": d, "n": len(shared_pids),
        })

    return df, sig_pairs, stat_results


def compute_cohens_kappa(
    paper_by_source: dict[str, dict[str, list[dict]]],
    paper_ids: list[str],
    venue_id: str = "",
) -> pd.DataFrame:
    """Compute Cohen's kappa for critical stance agreement: each AI source vs Human."""
    ai_sources = [s for s in SOURCES if s != "human"]
    rows = []

    for ai_src in ai_sources:
        a = b = c = d = 0

        for pid in paper_ids:
            by_source = paper_by_source.get(pid, {})
            human_stances = _dominant_stances_per_claim(by_source.get("human", []))
            ai_stances = _dominant_stances_per_claim(by_source.get(ai_src, []))
            shared = set(human_stances.keys()) & set(ai_stances.keys())

            for cid in shared:
                h_crit = human_stances[cid] == "CRITICAL"
                ai_crit = ai_stances[cid] == "CRITICAL"
                if h_crit and ai_crit:
                    a += 1
                elif h_crit and not ai_crit:
                    b += 1
                elif not h_crit and ai_crit:
                    c += 1
                else:
                    d += 1

        n = a + b + c + d
        if n == 0:
            rows.append({
                "source_pair": f"Human vs {SOURCE_LABELS[SOURCES.index(ai_src)]}",
                "kappa": float("nan"), "p_o": float("nan"),
                "p_e": float("nan"), "n": 0,
            })
            continue

        p_o = (a + d) / n
        p_h_crit = (a + b) / n
        p_ai_crit = (a + c) / n
        p_e = p_h_crit * p_ai_crit + (1 - p_h_crit) * (1 - p_ai_crit)

        kappa = (p_o - p_e) / (1 - p_e) if p_e < 1.0 else float("nan")

        rows.append({
            "source_pair": f"Human vs {SOURCE_LABELS[SOURCES.index(ai_src)]}",
            "kappa": round(kappa, 4),
            "p_o": round(p_o, 4),
            "p_e": round(p_e, 4),
            "n": n,
        })

    df = pd.DataFrame(rows, columns=["source_pair", "kappa", "p_o", "p_e", "n"])
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"{venue_id}_cohens_kappa.csv"
    df.to_csv(out_path, index=False)

    print("\n=== Cohen's Kappa (Critical Stance: Human vs AI) ===")
    for _, row in df.iterrows():
        print(f"  {row['source_pair']}: κ = {row['kappa']:.4f}  "
              f"(p_o={row['p_o']:.4f}, p_e={row['p_e']:.4f}, n={row['n']})")
    print(f"  Saved {out_path}")

    return df
