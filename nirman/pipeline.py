"""
NIRMAN AI — End-to-End Generation Pipeline
Wires all 9 modules together into a single async orchestrator.

Flow:
  1. select_context_for_request()           ← Graph module
  2. build_failure_context()                ← Memory module
  3. select_strategy()                      ← Bandit
  4. for i in range(N):                     ← Best-of-N
       a. plan_building()                   ← VLM Planner
       b. validate_all()                    ← Validator
       c. correct_specification() (if bad)  ← VLM Planner
       d. generate_script()                 ← Code generator
       e. run_script()                      ← Blender runner
       f. verify()                          ← Verifier
       g. save/update attempt in MongoDB    ← Memory
  5. select_best()                          ← Selector
  6. update() bandit                        ← Bandit
  7. return GenerationPipelineResult
"""
from __future__ import annotations
import logging
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .config import Settings
from .graph.manager import GraphContextManager
from .graph.models import BuildingGraph
from .vlm.provider import VLMProviderFactory
from .vlm.planner import VLMPlanner
from .validation.validator import SpecificationValidator
from .kernel.codegen import BlenderCodeGenerator
from .execution.runner import BlenderRunnerFactory, ExecutionResult
from .verification.engine import VerificationEngine
from .memory.store import FailureMemoryStore, GenerationAttempt
from .selection.selector import BestOfNSelector, StrategyBandit

logger = logging.getLogger(__name__)


@dataclass
class GenerationPipelineResult:
    attempt_id:           str
    success:              bool
    gltf_path:            Optional[str]
    blend_path:           Optional[str]
    verification_report:  Optional[dict]
    verification_score:   float
    spec:                 Optional[dict]
    error:                Optional[str] = None


class GenerationPipeline:
    """
    End-to-end NIRMAN AI generation pipeline.
    One instance per FastAPI app; shared across all requests.
    """

    def __init__(self, settings: Settings, memory: FailureMemoryStore) -> None:
        self.settings = settings
        self.memory   = memory

        api_key = (
            settings.gemini_api_key
            if settings.vlm_provider.value == "gemini"
            else settings.openai_api_key
        )
        provider        = VLMProviderFactory.create(settings.vlm_provider.value, api_key)
        self.planner    = VLMPlanner(provider)
        self.validator  = SpecificationValidator()
        self.codegen    = BlenderCodeGenerator(
            kernel_path=str(Path(__file__).parent.parent)
        )
        self.runner     = BlenderRunnerFactory.create(
            mode=settings.blender_execution_mode.value,
            blender_executable=settings.blender_executable,
            docker_image=settings.docker_image,
            timeout=settings.docker_timeout,
        )
        self.verifier   = VerificationEngine(
            min_door_width=settings.min_door_width,
            min_door_height=settings.min_door_height,
        )
        self.selector   = BestOfNSelector()
        self.bandit     = StrategyBandit()
        self.graph_mgr  = GraphContextManager()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(
        self,
        building_id:     str,
        graph:           BuildingGraph,
        user_request:    str,
        target_cell_ids: Optional[list[str]] = None,
        use_best_of_n:   bool = True,
    ) -> GenerationPipelineResult:
        """Full pipeline run — returns the best accepted candidate."""
        logger.info("Pipeline START | building=%s | %s", building_id, user_request[:60])

        # 1. Graph context selection
        ctx = self.graph_mgr.select_context_for_request(
            graph, user_request, target_cell_ids
        )

        # 2. Failure history from MongoDB
        failure_history = await self.memory.build_failure_context(building_id)

        # 3. Strategy selection
        strategy = self.bandit.select_strategy()

        # 4. Best-of-N generation loop
        n = self.settings.generation_candidates if use_best_of_n else 1
        candidates: list[dict] = []

        for i in range(n):
            candidate = await self._generate_candidate(
                building_id, ctx, user_request, failure_history, strategy.name, i
            )
            candidates.append(candidate)
            # Early exit on a passing candidate
            if candidate.get("verification_report", {}).get("overall") == "pass":
                logger.info("Candidate %d/%d passed — stopping early.", i + 1, n)
                break

        # 5. Select best
        best, best_score, best_idx = self.selector.select_best(candidates)

        # 6. Update bandit
        self.bandit.update(strategy.name, best_score)

        if best is None:
            return GenerationPipelineResult(
                attempt_id="none", success=False, gltf_path=None, blend_path=None,
                verification_report=None, verification_score=0.0,
                spec=None, error="All candidates failed.",
            )

        er = best.get("execution_result")
        return GenerationPipelineResult(
            attempt_id=best.get("attempt_id", "unknown"),
            success=best.get("execution_success", False),
            gltf_path=er.gltf_path  if er else None,
            blend_path=er.blend_path if er else None,
            verification_report=best.get("verification_report"),
            verification_score=best_score,
            spec=best.get("spec"),
        )

    async def submit_feedback(
        self, attempt_id: str, feedback: str, accepted: bool
    ) -> None:
        """Record user accept/reject feedback in MongoDB."""
        await self.memory.update_user_feedback(attempt_id, feedback, accepted)
        logger.info("Feedback recorded: attempt=%s accepted=%s", attempt_id, accepted)

    # ------------------------------------------------------------------
    # Internal — single candidate
    # ------------------------------------------------------------------

    async def _generate_candidate(
        self,
        building_id:     str,
        ctx,
        user_request:    str,
        failure_history: list[dict],
        strategy_name:   str,
        candidate_index: int,
    ) -> dict:
        attempt_id = str(uuid.uuid4())
        output_dir = str(Path(self.settings.output_dir) / building_id / attempt_id)

        # ── VLM planning ──────────────────────────────────────────────
        spec_dict, vlm_resp = self.planner.plan_building(ctx, user_request, failure_history)

        # Save pre-verification attempt
        attempt = GenerationAttempt(
            id=attempt_id, building_id=building_id,
            user_request=user_request,
            graph_cells_used=[c.id for c in ctx.selected_cells],
            tokens_estimated=ctx.total_tokens_estimated,
            model=vlm_resp.model, provider=vlm_resp.provider,
            strategy=strategy_name, candidate_index=candidate_index,
            specification=spec_dict,
            input_tokens=vlm_resp.input_tokens, output_tokens=vlm_resp.output_tokens,
        )
        await self.memory.save_attempt(attempt)

        if spec_dict is None:
            logger.warning("VLM produced no JSON for attempt %s", attempt_id)
            return self._failed_candidate(attempt_id, spec_dict)

        # ── Validation + optional correction ─────────────────────────
        val  = self.validator.validate_all(spec_dict)
        if not val.is_valid:
            all_errors = val.schema_errors + val.connectivity_errors + val.geometry_errors
            logger.info(
                "Spec invalid (%d errors) — attempting VLM correction.", len(all_errors)
            )
            corrected, _ = self.planner.correct_specification(spec_dict, all_errors)
            if corrected:
                val = self.validator.validate_all(corrected)
                spec_dict = corrected if val.is_valid else spec_dict

        if not val.is_valid:
            logger.warning("Spec still invalid after correction — skipping execution.")
            return self._failed_candidate(attempt_id, spec_dict)

        # ── Code generation ───────────────────────────────────────────
        gltf_p  = str(Path(output_dir) / "building.gltf")
        blend_p = str(Path(output_dir) / "building.blend")
        script  = self.codegen.generate_script(spec_dict, gltf_p, blend_p)

        # ── Blender execution ─────────────────────────────────────────
        er: ExecutionResult = self.runner.run_script(script, output_dir)
        logger.info(
            "Execution %s | success=%s | %.1fs", attempt_id, er.success, er.execution_time_s
        )

        # ── Verification ──────────────────────────────────────────────
        vreport      = self.verifier.verify(attempt_id, er, spec_dict)
        vreport_dict = vreport.model_dump(mode="json")

        await self.memory.update_verification(
            attempt_id, vreport_dict,
            vreport.overall, vreport.overall_score, vreport.failure_categories,
        )

        return {
            "attempt_id":         attempt_id,
            "spec":               spec_dict,
            "execution_result":   er,
            "execution_success":  er.success,
            "verification_report": vreport_dict,
        }

    @staticmethod
    def _failed_candidate(attempt_id: str, spec: Optional[dict]) -> dict:
        return {
            "attempt_id":          attempt_id,
            "spec":                spec,
            "execution_result":    None,
            "execution_success":   False,
            "verification_report": {"overall": "fail", "overall_score": 0.0},
        }
