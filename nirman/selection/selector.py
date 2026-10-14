"""
NIRMAN AI — Candidate Selection & Strategy Optimisation

Stage A — Best-of-N Selection
    Generate N candidates, score each with the verifier, return the best.
    Uses a deterministic weighted evaluation function (not arbitrary choice).

Stage B — Strategy Bandit (ε-greedy)
    Maintain per-strategy statistics (attempts, avg_reward, wins).
    With probability ε explore; otherwise exploit the best-known strategy.
    Reward = composite verifier score ∈ [0, 1].

NOTE: This is NOT full Reinforcement Learning.
Full RL (MDP with explicit state/action/reward/policy/transition) is a
future extension and would require dedicated baseline experiments.
"""
from __future__ import annotations
import copy
import logging
import math
import random
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


# ── Strategy definitions ──────────────────────────────────────────────────────

@dataclass
class Strategy:
    name:         str
    description:  str
    attempts:     int   = 0
    total_reward: float = 0.0
    wins:         int   = 0

    @property
    def avg_reward(self) -> float:
        return self.total_reward / self.attempts if self.attempts > 0 else 0.0

    def ucb1(self, total: int) -> float:
        """Upper Confidence Bound (UCB1) score for exploration."""
        if self.attempts == 0:
            return float("inf")
        return self.avg_reward + math.sqrt(2 * math.log(max(total, 1)) / self.attempts)


DEFAULT_STRATEGIES: list[Strategy] = [
    Strategy("standard",
             "Single-pass generation with failure-history injection"),
    Strategy("detailed_rooms",
             "Emphasise precise room dimensions and doorway positions"),
    Strategy("connectivity_first",
             "Prioritise BFS reachability over aesthetic detail"),
    Strategy("minimal_spec",
             "Minimal required rooms only — lower hallucination risk"),
]


# ── Stage A: Best-of-N ────────────────────────────────────────────────────────

class BestOfNSelector:
    """
    Score each candidate using a deterministic weighted evaluation function,
    then return the candidate with the highest composite score.

    Weights reflect project priorities:
        traversability > doorway_clearance > staircase > execution > mesh
    """
    W_EXECUTION      = 0.15
    W_TRAVERSABILITY = 0.35
    W_DOORWAY        = 0.25
    W_STAIRCASE      = 0.20
    W_MESH           = 0.05

    def _score_check(self, report: dict, key: str) -> float:
        chk = report.get(key, {})
        s   = chk.get("score")
        if s is not None:
            return float(s)
        st = chk.get("status", "fail")
        return 1.0 if st == "pass" else (0.5 if st == "warning" else 0.0)

    def compute_score(self, verification_report: dict) -> float:
        """Return a composite score ∈ [0, 1] from a VerificationReport dict."""
        vr = verification_report
        return round(
            self.W_EXECUTION      * self._score_check(vr, "execution")
            + self.W_TRAVERSABILITY * self._score_check(vr, "traversability")
            + self.W_DOORWAY        * self._score_check(vr, "doorway_clearance")
            + self.W_STAIRCASE      * self._score_check(vr, "staircase_accessibility")
            + self.W_MESH           * self._score_check(vr, "mesh_integrity"),
            4,
        )

    def select_best(
        self, candidates: list[dict]
    ) -> tuple[Optional[dict], float, int]:
        """
        Given [{spec, verification_report, …}, …] score each and return
        (best_candidate, best_score, best_index).
        """
        if not candidates:
            return None, 0.0, -1
        best_score = -1.0
        best_idx   = 0
        for i, c in enumerate(candidates):
            score = self.compute_score(c.get("verification_report", {}))
            c["computed_score"] = score
            logger.info("Candidate %d/%d score=%.4f", i + 1, len(candidates), score)
            if score > best_score:
                best_score = score
                best_idx   = i
        logger.info("Best candidate: index=%d score=%.4f", best_idx, best_score)
        return candidates[best_idx], best_score, best_idx


# ── Stage B: ε-greedy Strategy Bandit ────────────────────────────────────────

class StrategyBandit:
    """
    ε-greedy bandit over generation strategies.

    On each select_strategy() call:
      - With prob ε  → explore: pick a random (preferably untried) strategy.
      - Otherwise    → exploit: pick the strategy with highest avg_reward.

    After each attempt, call update(strategy_name, reward) to maintain stats.
    """

    def __init__(
        self,
        strategies: Optional[list[Strategy]] = None,
        epsilon: float = 0.15,
    ) -> None:
        # Deep-copy so each instance owns independent Strategy objects
        source = strategies if strategies is not None else DEFAULT_STRATEGIES
        self.strategies     = {s.name: copy.deepcopy(s) for s in source}
        self.epsilon        = epsilon
        self.total_attempts = 0

    def select_strategy(self) -> Strategy:
        self.total_attempts += 1
        if random.random() < self.epsilon:
            # Prefer untried strategies first
            untried = [s for s in self.strategies.values() if s.attempts == 0]
            chosen  = random.choice(untried) if untried else random.choice(
                list(self.strategies.values())
            )
            logger.info("Bandit EXPLORE → '%s'", chosen.name)
        else:
            chosen = max(self.strategies.values(), key=lambda s: s.avg_reward)
            logger.info(
                "Bandit EXPLOIT → '%s' (avg_reward=%.4f)", chosen.name, chosen.avg_reward
            )
        return chosen

    def update(self, strategy_name: str, reward: float) -> None:
        """Update statistics after an attempt. reward ∈ [0, 1]."""
        s = self.strategies.get(strategy_name)
        if s is None:
            logger.warning("Unknown strategy '%s' in bandit update.", strategy_name)
            return
        s.attempts     += 1
        s.total_reward += reward
        if reward >= 0.7:
            s.wins += 1
        logger.info(
            "Bandit updated '%s': attempts=%d avg_reward=%.4f wins=%d",
            strategy_name, s.attempts, s.avg_reward, s.wins,
        )

    def get_stats(self) -> dict:
        return {
            name: {
                "attempts":   s.attempts,
                "avg_reward": round(s.avg_reward, 4),
                "wins":       s.wins,
                "description": s.description,
            }
            for name, s in self.strategies.items()
        }
