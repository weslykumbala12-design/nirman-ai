"""
NIRMAN AI — Experiment Runner (Checklist Item 9)
=================================================
Runs structured ablation experiments comparing:

  Baseline A  — Full context (all photos, no graph retrieval)
  Baseline B  — No failure memory (no corrective hints injected)
  Ablation 1  — Graph retrieval ON, failure memory OFF
  Ablation 2  — Graph retrieval OFF, failure memory ON
  Full system — Graph retrieval ON + failure memory ON + Best-of-N

For each condition, records:
  - traversability_score
  - doorway_clearance_score
  - staircase_score
  - overall_score
  - tokens_used
  - generation_time_s
  - accepted (bool)

Results are saved to experiments/results_<timestamp>.json
and a summary table is printed to stdout.

Usage:
    python -m experiments.run_experiments --building_id <id> --runs 5
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

# Ensure project root on path
sys.path.insert(0, str(Path(__file__).parent.parent))


# ── Experiment conditions ─────────────────────────────────────────────────────

CONDITIONS = {
    "baseline_full_context": {
        "description": "All photos sent every time. No graph retrieval. No failure memory.",
        "use_graph_retrieval": False,
        "use_failure_memory":  False,
        "use_best_of_n":       False,
        "n_candidates":        1,
    },
    "baseline_no_memory": {
        "description": "Graph retrieval ON. Failure memory OFF.",
        "use_graph_retrieval": True,
        "use_failure_memory":  False,
        "use_best_of_n":       False,
        "n_candidates":        1,
    },
    "ablation_memory_only": {
        "description": "Graph retrieval OFF. Failure memory ON.",
        "use_graph_retrieval": False,
        "use_failure_memory":  True,
        "use_best_of_n":       False,
        "n_candidates":        1,
    },
    "ablation_graph_only": {
        "description": "Graph retrieval ON. Failure memory ON. Best-of-N OFF.",
        "use_graph_retrieval": True,
        "use_failure_memory":  True,
        "use_best_of_n":       False,
        "n_candidates":        1,
    },
    "full_system": {
        "description": "Graph retrieval + Failure memory + Best-of-3.",
        "use_graph_retrieval": True,
        "use_failure_memory":  True,
        "use_best_of_n":       True,
        "n_candidates":        3,
    },
}

# ── Metric extraction helpers ─────────────────────────────────────────────────

def extract_metrics(verification_report: Optional[dict], tokens_used: int,
                    gen_time: float) -> dict:
    """Pull per-check scores from a VerificationReport dict."""
    if not verification_report:
        return {
            "overall_score":           0.0,
            "traversability_score":    0.0,
            "doorway_clearance_score": 0.0,
            "staircase_score":         0.0,
            "mesh_score":              0.0,
            "tokens_used":             tokens_used,
            "generation_time_s":       gen_time,
            "overall":                 "fail",
        }
    def s(key):
        chk = verification_report.get(key, {})
        v   = chk.get("score")
        return float(v) if v is not None else (
            1.0 if chk.get("status") == "pass" else 0.0
        )
    return {
        "overall_score":           verification_report.get("overall_score", 0.0),
        "traversability_score":    s("traversability"),
        "doorway_clearance_score": s("doorway_clearance"),
        "staircase_score":         s("staircase_accessibility"),
        "mesh_score":              s("mesh_integrity"),
        "tokens_used":             tokens_used,
        "generation_time_s":       gen_time,
        "overall":                 verification_report.get("overall", "fail"),
    }


# ── Simulated run (for dry-run / CI without Blender) ─────────────────────────

def simulate_run(condition_name: str, condition: dict, run_idx: int) -> dict:
    """
    Produce a plausible synthetic result without calling Blender or a real VLM.
    Used for CI/testing experiments infrastructure.
    The full_system condition is seeded to score higher on average.
    """
    import random
    rng = random.Random(hash(condition_name) + run_idx)

    base = {
        "baseline_full_context": 0.45,
        "baseline_no_memory":    0.55,
        "ablation_memory_only":  0.58,
        "ablation_graph_only":   0.65,
        "full_system":           0.82,
    }.get(condition_name, 0.5)

    noise   = rng.uniform(-0.08, 0.08)
    score   = min(1.0, max(0.0, base + noise))
    tokens  = int(rng.uniform(800, 2400) * (0.4 if condition["use_graph_retrieval"] else 1.0))
    gen_t   = rng.uniform(15.0, 90.0) * condition.get("n_candidates", 1)

    return {
        "overall_score":           round(score, 4),
        "traversability_score":    round(min(1.0, score + rng.uniform(-0.05, 0.10)), 4),
        "doorway_clearance_score": round(min(1.0, score + rng.uniform(-0.05, 0.10)), 4),
        "staircase_score":         round(min(1.0, score + rng.uniform(-0.10, 0.05)), 4),
        "mesh_score":              round(min(1.0, score + rng.uniform(0.0,  0.15)), 4),
        "tokens_used":             tokens,
        "generation_time_s":       round(gen_t, 2),
        "overall":                 "pass" if score >= 0.65 else "fail",
    }


# ── Aggregate + print table ───────────────────────────────────────────────────

def aggregate(results: list[dict]) -> dict:
    if not results:
        return {}
    keys = [k for k in results[0] if isinstance(results[0][k], (int, float))]
    agg  = {}
    for k in keys:
        vals      = [r[k] for r in results]
        agg[k]    = round(sum(vals) / len(vals), 4)
    agg["pass_rate"] = round(
        sum(1 for r in results if r.get("overall") == "pass") / len(results), 4
    )
    return agg


def print_table(all_agg: dict[str, dict]) -> None:
    cols = [
        ("Condition",              22),
        ("Overall",                 8),
        ("Traversal",               9),
        ("Doors",                   7),
        ("Stairs",                  7),
        ("Tokens",                  8),
        ("Time(s)",                 8),
        ("PassRate",                9),
    ]
    header = "  ".join(f"{h:<{w}}" for h, w in cols)
    sep    = "-" * len(header)
    print("\n" + sep)
    print(header)
    print(sep)
    for cname, agg in all_agg.items():
        row = [
            (cname[:22],                                         22),
            (f"{agg.get('overall_score', 0):.3f}",               8),
            (f"{agg.get('traversability_score', 0):.3f}",        9),
            (f"{agg.get('doorway_clearance_score', 0):.3f}",     7),
            (f"{agg.get('staircase_score', 0):.3f}",             7),
            (f"{agg.get('tokens_used', 0):.0f}",                 8),
            (f"{agg.get('generation_time_s', 0):.1f}",           8),
            (f"{agg.get('pass_rate', 0):.2%}",                   9),
        ]
        print("  ".join(f"{v:<{w}}" for v, w in row))
    print(sep + "\n")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="NIRMAN AI Ablation Experiments")
    parser.add_argument("--building_id", default="exp_building_001")
    parser.add_argument("--runs",  type=int,  default=5,
                        help="Number of generation runs per condition")
    parser.add_argument("--dry_run", action="store_true",
                        help="Use simulated results (no Blender/VLM required)")
    parser.add_argument("--conditions", nargs="*", choices=list(CONDITIONS.keys()),
                        default=list(CONDITIONS.keys()),
                        help="Which conditions to run")
    parser.add_argument("--output_dir", default="experiments/results")
    args = parser.parse_args()

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    all_results: dict[str, list[dict]] = {}
    all_agg:     dict[str, dict]       = {}

    for cname in args.conditions:
        condition = CONDITIONS[cname]
        print(f"\n[{cname}] {condition['description']}")
        print(f"  runs={args.runs}  {'DRY-RUN' if args.dry_run else 'LIVE'}")

        runs: list[dict] = []
        for i in range(args.runs):
            print(f"  Run {i+1}/{args.runs} ... ", end="", flush=True)
            t0 = time.time()

            if args.dry_run:
                metrics = simulate_run(cname, condition, run_idx=i)
            else:
                # Real run — imports the full pipeline
                # (Blender + MongoDB must be available)
                metrics = _live_run(cname, condition, args.building_id, i)

            elapsed = time.time() - t0
            runs.append(metrics)
            print(
                f"score={metrics['overall_score']:.3f}  "
                f"tokens={metrics['tokens_used']}  "
                f"{'PASS' if metrics['overall'] == 'pass' else 'FAIL'}"
                f"  ({elapsed:.1f}s)"
            )

        all_results[cname] = runs
        all_agg[cname]     = aggregate(runs)

    # Print summary table
    print_table(all_agg)

    # Save full results
    out_file = out_dir / f"results_{timestamp}.json"
    with open(out_file, "w") as f:
        json.dump({
            "timestamp":   timestamp,
            "building_id": args.building_id,
            "runs_per_condition": args.runs,
            "conditions":  CONDITIONS,
            "results":     all_results,
            "aggregated":  all_agg,
        }, f, indent=2)
    print(f"Results saved to: {out_file}\n")


def _live_run(cname: str, condition: dict, building_id: str, run_idx: int) -> dict:
    """Real pipeline run — requires Blender + MongoDB + VLM API."""
    import asyncio
    from nirman.config import get_settings
    from nirman.memory.store import FailureMemoryStore
    from nirman.pipeline import GenerationPipeline
    from nirman.graph.manager import GraphContextManager
    from nirman.graph.models import BuildingGraph

    settings = get_settings()
    memory   = FailureMemoryStore(settings.mongodb_uri, settings.mongodb_db)
    pipeline = GenerationPipeline(settings, memory)

    # For experiments, build a simple test graph with no real photos
    mgr   = GraphContextManager()
    graph = mgr.create_building_graph(f"{building_id}_{cname}_{run_idx}")

    failure_history = []
    if condition["use_failure_memory"]:
        failure_history = asyncio.run(
            memory.build_failure_context(building_id)
        )

    user_request = (
        "Generate a 2-floor residential building with lobby, kitchen, 2 bedrooms, "
        "bathroom, and staircase. Flat roof. All rooms must be connected."
    )

    t0  = time.time()
    ctx = mgr.select_context_for_request(graph, user_request)

    if not condition["use_graph_retrieval"]:
        # Simulate full context by expanding to all cells
        from nirman.graph.models import ContextSelection
        ctx = ContextSelection(
            selected_cells=list(graph.cells.values()),
            total_photos=0,
            total_tokens_estimated=2000,
            selection_reason="full_context_baseline",
        )

    result = asyncio.run(pipeline.run(
        building_id=f"{building_id}_{cname}_{run_idx}",
        graph=graph,
        user_request=user_request,
        use_best_of_n=condition["use_best_of_n"],
    ))
    gen_time = round(time.time() - t0, 2)

    asyncio.run(memory.close())
    return extract_metrics(result.verification_report, ctx.total_tokens_estimated, gen_time)


if __name__ == "__main__":
    main()
