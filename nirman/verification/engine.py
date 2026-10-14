"""
NIRMAN AI — Automated Verification Engine
Evaluates every generated building with deterministic checks:

  A. Execution correctness  — did the Blender script complete?
  B. Traversability         — BFS from entrance; every room reachable?
  C. Doorway clearance      — all openings ≥ 0.8 m × 2.0 m?
  D. Staircase accessibility — spans correct floors, adequate opening?
  E. Visual fidelity        — approximate layout comparison
  F. Mesh integrity         — error patterns in execution logs

The verifier returns a VerificationReport with per-check results and
actionable suggested_corrections for the next generation attempt.
"""
from __future__ import annotations
import logging
from collections import deque
from typing import Optional

from pydantic import BaseModel

logger = logging.getLogger(__name__)


# ── Per-check result ──────────────────────────────────────────────────────────

class CheckResult(BaseModel):
    status:       str            # 'pass' | 'fail' | 'warning' | 'skip'
    detail:       str = ""
    affected_ids: list[str] = []
    score:        Optional[float] = None   # 0.0–1.0 where defined
    suggestions:  list[str] = []


# ── Full report ───────────────────────────────────────────────────────────────

class VerificationReport(BaseModel):
    overall:         str    # 'pass' | 'fail'
    overall_score:   float  # 0.0–1.0 composite
    attempt_id:      str
    execution:            CheckResult
    traversability:       CheckResult
    doorway_clearance:    CheckResult
    staircase_accessibility: CheckResult
    visual_fidelity:      CheckResult
    mesh_integrity:       CheckResult
    failure_categories:   list[str] = []
    suggested_corrections: list[str] = []

    def to_failure_categories(self) -> list[str]:
        cats = []
        if self.execution.status            == "fail": cats.append("execution_error")
        if self.traversability.status       == "fail": cats.append("disconnected_rooms")
        if self.doorway_clearance.status    == "fail": cats.append("blocked_doorway")
        if self.staircase_accessibility.status == "fail": cats.append("stair_incomplete")
        if self.mesh_integrity.status       == "fail": cats.append("mesh_invalid")
        return cats


# ── Engine ────────────────────────────────────────────────────────────────────

class VerificationEngine:
    """
    Runs all verification checks on a generated building.
    Takes an ExecutionResult dataclass and an optional BuildingSpec dict.
    """

    def __init__(
        self, min_door_width: float = 0.8, min_door_height: float = 2.0
    ) -> None:
        self.min_door_width  = min_door_width
        self.min_door_height = min_door_height

    # ── Entry point ───────────────────────────────────────────────────

    def verify(
        self,
        attempt_id:            str,
        execution_result,                       # ExecutionResult dataclass
        spec:                  Optional[dict] = None,
        rendered_image_path:   Optional[str]  = None,
        reference_image_paths: Optional[list[str]] = None,
    ) -> VerificationReport:
        """Run all checks and return a structured VerificationReport."""
        exec_chk = self._check_execution(execution_result)

        skip = CheckResult(status="skip", detail="Skipped due to execution failure.")

        if not execution_result.success or spec is None:
            report = VerificationReport(
                overall="fail", overall_score=0.0, attempt_id=attempt_id,
                execution=exec_chk, traversability=skip, doorway_clearance=skip,
                staircase_accessibility=skip, visual_fidelity=skip, mesh_integrity=skip,
            )
            report.failure_categories = report.to_failure_categories()
            return report

        trav_chk  = self._check_traversability(spec)
        door_chk  = self._check_doorway_clearance(spec)
        stair_chk = self._check_staircase_accessibility(spec)
        fid_chk   = self._check_visual_fidelity(spec, rendered_image_path, reference_image_paths)
        mesh_chk  = self._check_mesh_integrity(execution_result)

        scores = [c.score for c in [exec_chk, trav_chk, door_chk, stair_chk, mesh_chk]
                  if c.score is not None]
        overall_score = sum(scores) / len(scores) if scores else 0.0

        # Critical checks: execution + traversability + doorway
        critical_ok = (
            exec_chk.status == "pass"
            and trav_chk.status  in ("pass", "warning")
            and door_chk.status  in ("pass", "warning")
        )

        all_suggestions: list[str] = []
        for chk in [exec_chk, trav_chk, door_chk, stair_chk, fid_chk, mesh_chk]:
            all_suggestions.extend(chk.suggestions)

        report = VerificationReport(
            overall="pass" if critical_ok else "fail",
            overall_score=round(overall_score, 3),
            attempt_id=attempt_id,
            execution=exec_chk,
            traversability=trav_chk,
            doorway_clearance=door_chk,
            staircase_accessibility=stair_chk,
            visual_fidelity=fid_chk,
            mesh_integrity=mesh_chk,
            suggested_corrections=all_suggestions,
        )
        report.failure_categories = report.to_failure_categories()
        logger.info(
            "Verification %s | overall=%s | score=%.3f | failures=%s",
            attempt_id, report.overall, report.overall_score, report.failure_categories,
        )
        return report

    # ── A. Execution ──────────────────────────────────────────────────

    def _check_execution(self, er) -> CheckResult:
        if er.success:
            return CheckResult(status="pass",
                               detail="Blender script completed successfully.", score=1.0)
        return CheckResult(
            status="fail",
            detail=f"Execution failed (exit={er.exit_code}): {er.error_message}",
            score=0.0,
            suggestions=[
                "Check the geometry kernel for Python syntax errors.",
                "Verify the Blender executable path and version (≥ 4.0 recommended).",
                f"Error detail: {er.error_detail}",
            ],
        )

    # ── B. Traversability — BFS ───────────────────────────────────────

    def _check_traversability(self, spec: dict) -> CheckResult:
        """
        Build adjacency from doorways (bidirectional usable passages).
        BFS from entrance_room_id.  Every room must be visited.
        Also checks floor-to-floor connectivity via staircases.
        """
        rooms       = spec.get("rooms", [])
        entrance_id = spec.get("entrance_room_id", "")
        num_floors  = spec.get("num_floors", 1)

        if not rooms:
            return CheckResult(status="fail", detail="No rooms in spec.", score=0.0,
                               suggestions=["Add at least one room to the spec."])

        adj: dict[str, set[str]] = {r["id"]: set() for r in rooms}
        for room in rooms:
            for dw in room.get("doorways", []):
                tgt = dw.get("to_room_id", "")
                if tgt in adj:
                    adj[room["id"]].add(tgt)
                    adj[tgt].add(room["id"])

        if entrance_id not in adj:
            return CheckResult(
                status="fail",
                detail=f"entrance_room_id '{entrance_id}' not found in rooms.",
                score=0.0,
                suggestions=["Set entrance_room_id to an existing room id."],
            )

        visited: set[str] = set()
        q: deque[str] = deque([entrance_id])
        visited.add(entrance_id)
        while q:
            cur = q.popleft()
            for nb in adj[cur]:
                if nb not in visited:
                    visited.add(nb)
                    q.append(nb)

        all_ids   = set(adj.keys())
        unreachable = sorted(all_ids - visited)
        score     = len(visited) / len(all_ids) if all_ids else 0.0

        errors: list[str] = []
        suggestions: list[str] = []

        if unreachable:
            errors.append(
                f"Rooms unreachable from '{entrance_id}': {unreachable}"
            )
            for rid in unreachable:
                suggestions.append(
                    f"Add a doorway connecting '{rid}' to an adjacent reachable room."
                )

        # Floor connectivity
        floors_with_rooms = {r["floor"] for r in rooms}
        connected_floors: set[int] = {0}
        for st in spec.get("staircases", []):
            connected_floors.add(st.get("from_floor", 0))
            connected_floors.add(st.get("to_floor", 1))
        isolated = floors_with_rooms - connected_floors
        if isolated:
            errors.append(f"Floors with rooms but no staircase: {sorted(isolated)}")
            suggestions.append(f"Add staircases connecting floors {sorted(isolated)}.")

        if errors:
            return CheckResult(status="fail", detail=" | ".join(errors),
                               affected_ids=unreachable, score=round(score, 3),
                               suggestions=suggestions)
        return CheckResult(
            status="pass",
            detail=f"All {len(all_ids)} rooms reachable from '{entrance_id}'.",
            score=1.0,
        )

    # ── C. Doorway clearance ──────────────────────────────────────────

    def _check_doorway_clearance(self, spec: dict) -> CheckResult:
        violations: list[str] = []
        for room in spec.get("rooms", []):
            for dw in room.get("doorways", []):
                w = dw.get("width",  0)
                h = dw.get("height", 0)
                if w < self.min_door_width:
                    violations.append(
                        f"Room '{room['id']}' → '{dw.get('to_room_id')}': "
                        f"width={w}m < {self.min_door_width}m"
                    )
                if h < self.min_door_height:
                    violations.append(
                        f"Room '{room['id']}' → '{dw.get('to_room_id')}': "
                        f"height={h}m < {self.min_door_height}m"
                    )
        if violations:
            score = max(0.0, 1.0 - len(violations) * 0.2)
            return CheckResult(
                status="fail",
                detail=f"{len(violations)} clearance violations.",
                affected_ids=violations,
                score=round(score, 3),
                suggestions=[
                    f"Increase all doorways to ≥ {self.min_door_width}m × {self.min_door_height}m.",
                    *violations,
                ],
            )
        return CheckResult(status="pass",
                           detail="All doorways meet minimum clearance.", score=1.0)

    # ── D. Staircase accessibility ────────────────────────────────────

    def _check_staircase_accessibility(self, spec: dict) -> CheckResult:
        num_floors  = spec.get("num_floors", 1)
        staircases  = spec.get("staircases", [])

        if num_floors > 1 and not staircases:
            return CheckResult(
                status="fail",
                detail=f"Building has {num_floors} floors but no staircases.",
                score=0.0,
                suggestions=["Add at least one staircase connecting floor 0 to floor 1."],
            )

        issues: list[str] = []
        for st in staircases:
            sid = st.get("id", "?")
            ow  = st.get("opening_width",  0)
            od  = st.get("opening_depth",  0)
            ff  = st.get("from_floor",     0)
            tf  = st.get("to_floor",       1)
            if ff >= num_floors or tf >= num_floors:
                issues.append(f"Staircase '{sid}': floor index out of range (num_floors={num_floors}).")
            if ow < 1.0:
                issues.append(f"Staircase '{sid}': opening_width={ow}m < 1.0m.")
            if od < 2.0:
                issues.append(f"Staircase '{sid}': opening_depth={od}m < 2.0m (insufficient headroom).")

        if issues:
            return CheckResult(
                status="fail",
                detail=f"{len(issues)} staircase issues.",
                score=max(0.0, 1.0 - len(issues) * 0.3),
                suggestions=issues,
            )
        return CheckResult(status="pass",
                           detail=f"All {len(staircases)} staircase(s) valid.", score=1.0)

    # ── E. Visual fidelity ────────────────────────────────────────────

    def _check_visual_fidelity(
        self,
        spec: dict,
        rendered_image_path: Optional[str],
        reference_image_paths: Optional[list[str]],
    ) -> CheckResult:
        if not spec.get("has_interior_photos", False):
            return CheckResult(
                status="warning",
                detail=(
                    "Visual fidelity is approximate: no interior photographs provided. "
                    "Layout is inferred from exterior photos and user requirements."
                ),
                score=0.5,
                suggestions=["Provide interior photos for higher-confidence fidelity assessment."],
            )
        if rendered_image_path is None:
            return CheckResult(status="skip",
                               detail="No rendered image available for comparison.")
        # Placeholder — SSIM/CLIP implementation goes here
        return CheckResult(
            status="warning",
            detail="Visual fidelity: rendered image available but metric not yet computed.",
            score=0.6,
        )

    # ── F. Mesh integrity ─────────────────────────────────────────────

    def _check_mesh_integrity(self, er) -> CheckResult:
        BAD_PATTERNS = [
            "invalid mesh", "non-manifold", "degenerate",
            "zero-area face", "floating object", "mesh error",
        ]
        log = (er.stdout + er.stderr).lower()
        found = [p for p in BAD_PATTERNS if p in log]
        if found:
            return CheckResult(
                status="fail",
                detail=f"Mesh issues in execution log: {found}",
                score=max(0.0, 1.0 - len(found) * 0.25),
                suggestions=[
                    "Verify wall segment lengths are positive.",
                    "Check for zero-length walls caused by openings at exact wall boundaries.",
                ],
            )
        if not er.success:
            return CheckResult(status="fail", detail="Execution failed; mesh not generated.", score=0.0)
        return CheckResult(status="pass",
                           detail="No mesh integrity issues detected in execution logs.", score=1.0)
