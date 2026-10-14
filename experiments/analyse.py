"""
NIRMAN AI — Metrics & Analysis Utilities (Item 9 — Paper Support)
==================================================================
Loads experiment result JSON files and computes:
  - Per-condition mean ± std for all metrics
  - Token reduction vs. full-context baseline
  - Pass rate comparison table
  - LaTeX table string for the paper
  - Simple ASCII bar charts

Usage:
    python -m experiments.analyse --results experiments/results/results_<ts>.json
"""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path


def mean(vals: list[float]) -> float:
    return sum(vals) / len(vals) if vals else 0.0


def std(vals: list[float]) -> float:
    if len(vals) < 2:
        return 0.0
    m = mean(vals)
    return math.sqrt(sum((v - m) ** 2 for v in vals) / (len(vals) - 1))


def load_results(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def compute_stats(results: dict[str, list[dict]]) -> dict[str, dict]:
    """Compute mean ± std for every numeric metric per condition."""
    stats = {}
    for cname, runs in results.items():
        if not runs:
            continue
        keys = [k for k, v in runs[0].items() if isinstance(v, (int, float))]
        stats[cname] = {}
        for k in keys:
            vals = [r[k] for r in runs]
            stats[cname][k] = {"mean": round(mean(vals), 4), "std": round(std(vals), 4)}
        stats[cname]["pass_rate"] = {
            "mean": round(sum(1 for r in runs if r.get("overall") == "pass") / len(runs), 4),
            "std": 0.0,
        }
    return stats


def token_reduction_table(stats: dict[str, dict], baseline_key: str = "baseline_full_context") -> str:
    lines = ["Token Reduction vs. Full-Context Baseline", "=" * 48]
    baseline_tokens = stats.get(baseline_key, {}).get("tokens_used", {}).get("mean", 1)
    for cname, s in stats.items():
        tokens = s.get("tokens_used", {}).get("mean", 0)
        reduction = (1 - tokens / baseline_tokens) * 100 if baseline_tokens else 0
        lines.append(f"  {cname:<30} {reduction:+.1f}%  ({tokens:.0f} tokens avg)")
    return "\n".join(lines)


def latex_table(stats: dict[str, dict]) -> str:
    """Generate a LaTeX table suitable for the paper."""
    header = (
        r"\begin{table}[h]" "\n"
        r"\centering" "\n"
        r"\caption{NIRMAN AI Ablation Results (mean $\pm$ std)}" "\n"
        r"\begin{tabular}{lcccccc}" "\n"
        r"\hline" "\n"
        r"Condition & Overall & Traversal & Doors & Stairs & Tokens & Pass\% \\" "\n"
        r"\hline" "\n"
    )
    rows = ""
    condition_labels = {
        "baseline_full_context": "Baseline (full ctx)",
        "baseline_no_memory":    "No memory",
        "ablation_memory_only":  "Memory only",
        "ablation_graph_only":   "Graph only",
        "full_system":           "\\textbf{Full system}",
    }
    for cname, s in stats.items():
        def ms(key):
            d = s.get(key, {})
            return f"{d.get('mean', 0):.3f}$\\pm${d.get('std', 0):.3f}"
        label = condition_labels.get(cname, cname)
        rows += (
            f"{label} & {ms('overall_score')} & {ms('traversability_score')} & "
            f"{ms('doorway_clearance_score')} & {ms('staircase_score')} & "
            f"{s.get('tokens_used', {}).get('mean', 0):.0f} & "
            f"{s.get('pass_rate', {}).get('mean', 0):.1%} \\\\\n"
        )
    footer = r"\hline" "\n" r"\end{tabular}" "\n" r"\end{table}"
    return header + rows + footer


def ascii_bars(stats: dict[str, dict], metric: str = "overall_score") -> str:
    max_val   = max((s.get(metric, {}).get("mean", 0) for s in stats.values()), default=1)
    bar_width = 30
    lines     = [f"\n{metric} (bar chart)", "-" * 50]
    for cname, s in stats.items():
        val   = s.get(metric, {}).get("mean", 0)
        bar_n = int((val / max_val) * bar_width) if max_val > 0 else 0
        bar   = "#" * bar_n + "." * (bar_width - bar_n)
        lines.append(f"  {cname:<30} {bar} {val:.4f}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Analyse NIRMAN AI experiment results")
    parser.add_argument("--results", required=True, help="Path to results_<ts>.json")
    parser.add_argument("--latex",   action="store_true", help="Print LaTeX table")
    args = parser.parse_args()

    data    = load_results(args.results)
    results = data.get("results", {})
    stats   = compute_stats(results)

    print(f"\nExperiment: {data.get('timestamp')}  |  runs/condition: {data.get('runs_per_condition')}\n")

    # Summary table
    cols = [("Condition", 30), ("Overall", 10), ("Traversal", 10),
            ("Doors", 8), ("Stairs", 8), ("Tokens", 8), ("PassRate", 10)]
    header = "  ".join(f"{h:<{w}}" for h, w in cols)
    sep    = "-" * len(header)
    print(sep); print(header); print(sep)
    for cname, s in stats.items():
        def mv(k): return s.get(k, {}).get("mean", 0)
        row = [
            (cname[:30],                             30),
            (f"{mv('overall_score'):.4f}",           10),
            (f"{mv('traversability_score'):.4f}",    10),
            (f"{mv('doorway_clearance_score'):.4f}",  8),
            (f"{mv('staircase_score'):.4f}",          8),
            (f"{mv('tokens_used'):.0f}",              8),
            (f"{mv('pass_rate'):.1%}",               10),
        ]
        print("  ".join(f"{v:<{w}}" for v, w in row))
    print(sep)

    print("\n" + token_reduction_table(stats))
    print(ascii_bars(stats, "overall_score"))
    print(ascii_bars(stats, "pass_rate"))

    if args.latex:
        print("\n\n--- LaTeX Table ---\n")
        print(latex_table(stats))


if __name__ == "__main__":
    main()
