"""
NIRMAN AI — Persistent Failure Memory
MongoDB-backed store for generation attempts, verification results,
failure patterns, and user feedback.

Records are used to:
  1. Inject failure-aware corrections into the next generation prompt.
  2. Identify recurring failure categories (blocked_doorway, stair_incomplete, …).
  3. Track accepted vs. rejected attempts for strategy evaluation.
  4. Support best-of-N scoring across multiple candidates.
"""
from __future__ import annotations
import logging
import uuid
from datetime import datetime
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ── Attempt record ────────────────────────────────────────────────────────────

class GenerationAttempt(BaseModel):
    """Persisted record of one generation attempt."""
    id:            str  = Field(default_factory=lambda: str(uuid.uuid4()))
    building_id:   str
    timestamp:     datetime = Field(default_factory=datetime.utcnow)

    # Request context
    user_request:      str
    graph_cells_used:  list[str] = []
    tokens_estimated:  int = 0

    # Model / strategy
    model:           str
    provider:        str
    strategy:        str = "single"       # single | best_of_n | bandit
    candidate_index: Optional[int] = None

    # Outputs
    specification: Optional[dict] = None
    script_path:   Optional[str]  = None
    gltf_path:     Optional[str]  = None
    blend_path:    Optional[str]  = None

    # Execution
    execution_success:  bool  = False
    execution_time_s:   float = 0.0
    stdout_snippet:     str   = ""

    # Verification
    verification_overall: str   = "pending"
    verification_score:   float = 0.0
    failure_categories:   list[str] = []
    verification_report:  Optional[dict] = None

    # Token usage
    input_tokens:  int = 0
    output_tokens: int = 0

    # User feedback
    user_feedback:      Optional[str]      = None
    accepted:           bool               = False
    feedback_timestamp: Optional[datetime] = None


# ── Store ─────────────────────────────────────────────────────────────────────

class FailureMemoryStore:
    """
    Async MongoDB store for generation attempts.
    Provides failure-informed retrieval for prompt injection
    and pattern analysis across the generation history.
    """

    COLLECTION = "generation_attempts"

    # Known failure categories and their corrective hints
    CORRECTIONS: dict[str, str] = {
        "execution_error":    "Fix Python syntax or API usage in the generated Blender script.",
        "disconnected_rooms": (
            "Add doorways so every room is BFS-reachable from the entrance. "
            "Do NOT leave any room without a connecting doorway."
        ),
        "blocked_doorway":    (
            "Set every doorway to width ≥ 0.8 m and height ≥ 2.0 m. "
            "Use segment-based walls — do not place a wall segment across the opening."
        ),
        "stair_incomplete":   (
            "The staircase must span from_floor to to_floor completely. "
            "Include a stairwell opening (opening_width ≥ 1.0 m, opening_depth ≥ 2.0 m) "
            "in the destination floor slab."
        ),
        "mesh_invalid":       (
            "Avoid zero-length wall segments. Ensure all dimensions are positive. "
            "Do not place a doorway at position_along_wall = 0.0 or 1.0 exactly."
        ),
    }

    def __init__(self, mongo_uri: str, db_name: str = "nirman_ai") -> None:
        self.client = AsyncIOMotorClient(mongo_uri)
        self.db     = self.client[db_name]
        self.col    = self.db[self.COLLECTION]

    # ── Write ─────────────────────────────────────────────────────────

    async def save_attempt(self, attempt: GenerationAttempt) -> str:
        doc = attempt.model_dump(mode="json")
        await self.col.insert_one(doc)
        logger.info("Saved attempt %s for building %s", attempt.id, attempt.building_id)
        return attempt.id

    async def update_verification(
        self,
        attempt_id: str,
        report_dict: dict,
        overall: str,
        score: float,
        categories: list[str],
    ) -> None:
        await self.col.update_one(
            {"id": attempt_id},
            {"$set": {
                "verification_overall": overall,
                "verification_score":   score,
                "failure_categories":   categories,
                "verification_report":  report_dict,
            }},
        )

    async def update_user_feedback(
        self, attempt_id: str, feedback: str, accepted: bool
    ) -> None:
        await self.col.update_one(
            {"id": attempt_id},
            {"$set": {
                "user_feedback":      feedback,
                "accepted":           accepted,
                "feedback_timestamp": datetime.utcnow().isoformat(),
            }},
        )

    # ── Read ──────────────────────────────────────────────────────────

    async def get_relevant_failures(
        self,
        building_id: Optional[str] = None,
        failure_categories: Optional[list[str]] = None,
        limit: int = 5,
    ) -> list[dict]:
        """Recent failure records matching the given categories."""
        query: dict = {"accepted": False}
        if building_id:
            query["building_id"] = building_id
        if failure_categories:
            query["failure_categories"] = {"$in": failure_categories}
        cursor = self.col.find(query).sort("timestamp", -1).limit(limit)
        return [doc async for doc in cursor if not doc.pop("_id", None) or True]

    async def get_attempts_for_building(
        self, building_id: str, limit: int = 20
    ) -> list[dict]:
        """All attempts for a building, most recent first."""
        cursor = self.col.find({"building_id": building_id}).sort("timestamp", -1).limit(limit)
        results = []
        async for doc in cursor:
            doc.pop("_id", None)
            results.append(doc)
        return results

    async def get_failure_pattern_summary(
        self, building_id: Optional[str] = None
    ) -> dict[str, int]:
        """Aggregate failure_categories across rejected attempts → {category: count}."""
        match: dict = {"accepted": False}
        if building_id:
            match["building_id"] = building_id
        pipeline = [
            {"$match": match},
            {"$unwind": "$failure_categories"},
            {"$group": {"_id": "$failure_categories", "count": {"$sum": 1}}},
            {"$sort":  {"count": -1}},
        ]
        summary: dict[str, int] = {}
        async for doc in self.col.aggregate(pipeline):
            summary[doc["_id"]] = doc["count"]
        return summary

    async def build_failure_context(self, building_id: str) -> list[dict]:
        """
        Build a failure context list for prompt injection.
        Returns [{failure_category, occurrences, correction}] sorted by occurrence count.
        """
        pattern = await self.get_failure_pattern_summary(building_id)
        return [
            {
                "failure_category": cat,
                "occurrences":      count,
                "correction":       self.CORRECTIONS.get(cat, f"Avoid: {cat}"),
            }
            for cat, count in pattern.items()
        ]

    async def get_best_accepted_attempt(self, building_id: str) -> Optional[dict]:
        """Return the highest-scoring accepted attempt for a building."""
        doc = await self.col.find_one(
            {"building_id": building_id, "accepted": True},
            sort=[("verification_score", -1)],
        )
        if doc:
            doc.pop("_id", None)
        return doc

    async def get_attempt(self, attempt_id: str) -> Optional[dict]:
        doc = await self.col.find_one({"id": attempt_id})
        if doc:
            doc.pop("_id", None)
        return doc

    async def close(self) -> None:
        self.client.close()
