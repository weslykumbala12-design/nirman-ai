"""
NIRMAN AI — FastAPI Routes
All HTTP endpoints for the generation pipeline.
"""
from __future__ import annotations
import uuid
import logging
from pathlib import Path
from typing import Annotated, Optional

import aiofiles
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..config import get_settings
from ..graph.manager import GraphContextManager
from ..graph.models import BuildingGraph
from ..memory.store import FailureMemoryStore

logger = logging.getLogger(__name__)
router = APIRouter()

# ── In-process graph store (production: swap to Redis/MongoDB) ────────────────
_GRAPHS: dict[str, dict] = {}   # building_id → serialised BuildingGraph
_GM = GraphContextManager()


# ── Request / Response models ─────────────────────────────────────────────────

class GenerateRequest(BaseModel):
    user_request:    str
    target_cell_ids: Optional[list[str]] = None
    use_best_of_n:   bool = True


class FeedbackRequest(BaseModel):
    feedback: str
    accepted: bool


class RoomEditRequest(BaseModel):
    edit_request:    str
    target_cell_ids: Optional[list[str]] = None


# ── Dependency helpers ────────────────────────────────────────────────────────

def _get_graph(building_id: str) -> BuildingGraph:
    if building_id not in _GRAPHS:
        raise HTTPException(404, f"Building '{building_id}' not found. Upload photos first.")
    return _GM.from_dict(_GRAPHS[building_id])


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/health")
async def health():
    """Health check."""
    return {"status": "ok", "service": "nirman-ai"}


@router.post("/buildings/{building_id}/upload-photos")
async def upload_photos(
    building_id: str,
    files:   list[UploadFile]  = File(...),
    prompts: list[str]         = Form(default=[]),
    hints:   list[str]         = Form(default=[]),
):
    """
    Upload one or more building photographs with per-photo prompts and hints.
    Automatically classifies photos into context cells and builds the graph.
    """
    settings  = get_settings()
    upload_dir = Path(settings.output_dir) / building_id / "photos"
    upload_dir.mkdir(parents=True, exist_ok=True)

    photo_list: list[dict] = []
    for i, file in enumerate(files):
        dest = upload_dir / f"{uuid.uuid4().hex}_{file.filename}"
        async with aiofiles.open(dest, "wb") as f:
            content = await file.read()
            await f.write(content)
        photo_list.append({
            "file_path": str(dest),
            "prompt":    prompts[i] if i < len(prompts) else "",
            "hint":      hints[i]   if i < len(hints)   else None,
        })

    graph = _GM.auto_build_graph(building_id, photo_list)
    _GRAPHS[building_id] = _GM.to_dict(graph)

    return {
        "building_id": building_id,
        "photos_uploaded": len(files),
        "cells_created": len(graph.cells),
        "edges_created": len(graph.edges),
        "cells": [
            {"id": c.id, "type": c.cell_type.value, "photos": len(c.photos)}
            for c in graph.cells.values()
        ],
    }


@router.post("/buildings/{building_id}/generate")
async def generate_building(
    building_id: str,
    req: GenerateRequest,
    request: Request,
):
    """
    Trigger the full generation pipeline for a building.
    Returns attempt_id, status, and verification summary.
    """
    pipeline = request.app.state.pipeline
    graph    = _get_graph(building_id)

    result = await pipeline.run(
        building_id=building_id,
        graph=graph,
        user_request=req.user_request,
        target_cell_ids=req.target_cell_ids,
        use_best_of_n=req.use_best_of_n,
    )

    return {
        "attempt_id":          result.attempt_id,
        "success":             result.success,
        "verification_overall": result.verification_report.get("overall") if result.verification_report else "fail",
        "verification_score":  result.verification_score,
        "gltf_available":      result.gltf_path is not None,
        "blend_available":     result.blend_path is not None,
        "error":               result.error,
    }


@router.get("/buildings/{building_id}/attempts")
async def list_attempts(building_id: str, request: Request):
    """List all generation attempts for a building (most recent first)."""
    memory: FailureMemoryStore = request.app.state.memory
    attempts = await memory.get_attempts_for_building(building_id)
    return {"building_id": building_id, "attempts": attempts}


@router.get("/buildings/{building_id}/attempts/{attempt_id}")
async def get_attempt(building_id: str, attempt_id: str, request: Request):
    """Get a single generation attempt with full verification report."""
    memory: FailureMemoryStore = request.app.state.memory
    doc = await memory.get_attempt(attempt_id)
    if not doc:
        raise HTTPException(404, f"Attempt '{attempt_id}' not found.")
    if doc.get("building_id") != building_id:
        raise HTTPException(403, "Attempt does not belong to this building.")
    return doc


@router.post("/buildings/{building_id}/attempts/{attempt_id}/feedback")
async def submit_feedback(
    building_id: str, attempt_id: str, req: FeedbackRequest, request: Request
):
    """Record user accept/reject feedback for a generation attempt."""
    pipeline = request.app.state.pipeline
    await pipeline.submit_feedback(attempt_id, req.feedback, req.accepted)
    return {"status": "recorded", "attempt_id": attempt_id, "accepted": req.accepted}


@router.get("/buildings/{building_id}/attempts/{attempt_id}/gltf")
async def serve_gltf(building_id: str, attempt_id: str, request: Request):
    """Serve the GLTF file for a generation attempt."""
    memory: FailureMemoryStore = request.app.state.memory
    doc = await memory.get_attempt(attempt_id)
    if not doc or not doc.get("gltf_path"):
        raise HTTPException(404, "GLTF file not available for this attempt.")
    gltf_path = Path(doc["gltf_path"])
    if not gltf_path.exists():
        raise HTTPException(404, "GLTF file not found on disk.")
    return FileResponse(str(gltf_path), media_type="model/gltf+json",
                        filename="building.gltf")


@router.post("/buildings/{building_id}/rooms/{room_id}/edit")
async def edit_room(
    building_id: str, room_id: str, req: RoomEditRequest, request: Request
):
    """Targeted room edit — re-generates only the specified room's context."""
    pipeline = request.app.state.pipeline
    graph    = _get_graph(building_id)

    # For room edits, retrieve only the relevant cell context
    ctx = pipeline.graph_mgr.select_context_for_request(
        graph, req.edit_request, req.target_cell_ids
    )
    failure_history = await pipeline.memory.build_failure_context(building_id)

    # Get current best spec
    best = await pipeline.memory.get_best_accepted_attempt(building_id)
    current_spec = best.get("specification", {}) if best else {}

    spec_dict, vlm_resp = pipeline.planner.edit_room(
        room_id, req.edit_request, current_spec, ctx
    )
    if spec_dict is None:
        raise HTTPException(422, "VLM failed to generate a valid room edit.")

    val = pipeline.validator.validate_all(spec_dict)
    return {
        "room_id":    room_id,
        "valid":      val.is_valid,
        "spec":       spec_dict,
        "errors":     val.schema_errors + val.connectivity_errors + val.geometry_errors,
        "tokens_used": vlm_resp.input_tokens + vlm_resp.output_tokens,
    }


@router.get("/buildings/{building_id}/graph")
async def get_graph(building_id: str):
    """Return the building's photo-cell graph as JSON."""
    if building_id not in _GRAPHS:
        raise HTTPException(404, f"Building '{building_id}' not found.")
    return _GRAPHS[building_id]


@router.get("/buildings/{building_id}/failure-patterns")
async def get_failure_patterns(building_id: str, request: Request):
    """Return aggregated failure category counts for this building."""
    memory: FailureMemoryStore = request.app.state.memory
    summary = await memory.get_failure_pattern_summary(building_id)
    context = await memory.build_failure_context(building_id)
    return {
        "building_id": building_id,
        "pattern_counts": summary,
        "corrective_hints": context,
    }


@router.get("/bandit/stats")
async def bandit_stats(request: Request):
    """Return current strategy bandit statistics."""
    return request.app.state.pipeline.bandit.get_stats()
