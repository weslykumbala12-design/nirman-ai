"""
NIRMAN AI — Graph Context Models
Pydantic models for building photo cells, typed edges, and context selections.
"""
from __future__ import annotations
from datetime import datetime
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field


class CellType(str, Enum):
    GROUND_FLOOR_INTERIOR = "ground_floor_interior"
    UPPER_FLOOR_INTERIOR  = "upper_floor_interior"
    EXTERIOR_FACADE       = "exterior_facade"
    STAIRCASE_LANDING     = "staircase_landing"
    ROOF_TERRACE          = "roof_terrace"
    UNKNOWN               = "unknown"


class EdgeType(str, Enum):
    STAIRS_TO     = "stairs_to"
    ADJACENT_TO   = "adjacent_to"
    SAME_FLOOR_AS = "same_floor_as"
    CONTEXT_OF    = "context_of"
    DERIVED_FROM  = "derived_from"
    CONFLICTS_WITH = "conflicts_with"
    FEEDBACK_ON   = "feedback_on"


class PhotoEntry(BaseModel):
    id:           str
    file_path:    str
    prompt:       str  = ""
    cell_id:      str
    encoded_data: Optional[str] = None   # base64 image bytes
    mime_type:    str  = "image/jpeg"


class GraphCell(BaseModel):
    id:            str
    cell_type:     CellType
    photos:        list[PhotoEntry] = Field(default_factory=list)
    cell_prompt:   str = ""
    inferred_info: dict[str, Any] = Field(default_factory=dict)
    confidence:    float = Field(default=0.5, ge=0.0, le=1.0)
    floor_level:   Optional[int] = None
    created_at:    datetime = Field(default_factory=datetime.utcnow)
    updated_at:    datetime = Field(default_factory=datetime.utcnow)


class GraphEdge(BaseModel):
    source_id:  str
    target_id:  str
    edge_type:  EdgeType
    weight:     float = 1.0
    metadata:   dict[str, Any] = Field(default_factory=dict)


class BuildingGraph(BaseModel):
    building_id: str
    cells:       dict[str, GraphCell] = Field(default_factory=dict)
    edges:       list[GraphEdge]      = Field(default_factory=list)
    created_at:  datetime             = Field(default_factory=datetime.utcnow)


class ContextSelection(BaseModel):
    selected_cells:         list[GraphCell]
    total_photos:           int
    total_tokens_estimated: int
    selection_reason:       str
    style_only_cell_ids:    list[str] = Field(default_factory=list)
