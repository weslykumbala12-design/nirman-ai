# NIRMAN AI — Experiments

This directory contains scripts for checklist item 9:
**"Run baselines and ablations, analyze results and document limitations."**

## Experiment conditions

| Condition | Graph retrieval | Failure memory | Best-of-N |
|---|---|---|---|
| `baseline_full_context` | ✗ | ✗ | ✗ |
| `baseline_no_memory`    | ✓ | ✗ | ✗ |
| `ablation_memory_only`  | ✗ | ✓ | ✗ |
| `ablation_graph_only`   | ✓ | ✓ | ✗ |
| `full_system`           | ✓ | ✓ | ✓ |

## Usage

### Dry run (no Blender or VLM required — uses simulation)
```bash
cd nirman_ai
python -m experiments.run_experiments --dry_run --runs 10
```

### Live run (requires Blender + MongoDB + API key in .env)
```bash
python -m experiments.run_experiments --runs 5 --building_id my_building
```

### Analyse results
```bash
python -m experiments.analyse --results experiments/results/results_<timestamp>.json
python -m experiments.analyse --results experiments/results/results_<timestamp>.json --latex
```

## Metrics reported
- `overall_score` — weighted composite of all verification checks
- `traversability_score` — BFS room-connectivity pass rate
- `doorway_clearance_score` — fraction of doorways meeting min clearance
- `staircase_score` — staircase accessibility check score
- `tokens_used` — estimated tokens per generation request
- `generation_time_s` — wall-clock seconds per attempt
- `pass_rate` — fraction of runs that pass all critical checks

## Known limitations
- Visual fidelity (check E) is currently approximate — SSIM/CLIP comparison
  requires a rendered image from Blender, which needs a GPU environment.
- Full RL (Stage D) is not implemented — current Stage B bandit is clearly
  labelled as epsilon-greedy multi-armed bandit, not MDP-based RL.
- Experiments with real buildings require a running MongoDB instance and
  a valid VLM API key.
