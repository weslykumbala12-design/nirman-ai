"""
NIRMAN AI — Specification Validator
Three-layer validation: schema → connectivity (BFS) → geometry.
"""
from __future__ import annotations
import logging
from collections import deque
from typing import Optional

from pydantic import BaseModel, ValidationError

from .schema import BuildingSpec

logger = logging.getLogger(__name__)


class ValidationResult(BaseModel):
    is_valid:             bool
    schema_errors:        list[str] = []
    connectivity_errors:  list[str] = []
    geometry_errors:      list[str] = []
    warnings:             list[str] = []
    spec:                 Optional[BuildingSpec] = None

    model_config = {"arbitrary_types_allowed": True}


class SpecificationValidator:
    """Validates a building specification dict at three levels."""

    # ------------------------------------------------------------------
    # Layer 1 — Pydantic schema
    # ------------------------------------------------------------------

    def validate_schema(self, data: dict) -> tuple[Optional[BuildingSpec], list[str]]:
        """Parse and validate against BuildingSpec. Returns (spec | None, errors)."""
        try:
            spec = BuildingSpec.model_validate(data)
            return spec, []
        except ValidationError as exc:
            errors = []
            for err in exc.errors():
                loc = " -> ".join(str(l) for l in err["loc"])
                errors.append(f"{loc}: {err['msg']}")
            return None, errors
        except Exception as exc:
            return None, [f"Unexpected parse error: {exc}"]

    # ------------------------------------------------------------------
    # Layer 2 — BFS room connectivity
    # ------------------------------------------------------------------

    def validate_connectivity(self, spec: BuildingSpec) -> tuple[bool, list[str]]:
        """
        Build adjacency graph from doorways (bidirectional).
        BFS from entrance to check every room is reachable.
        Also checks that multi-floor buildings have staircases.
        """
        errors: list[str] = []

        # Build adjacency list
        adj: dict[str, set[str]] = {r.id: set() for r in spec.rooms}
        for room in spec.rooms:
            for dw in room.doorways:
                adj[room.id].add(dw.to_room_id)
                if dw.to_room_id in adj:
                    adj[dw.to_room_id].add(room.id)

        # BFS from entrance
        visited: set[str] = set()
        queue: deque[str] = deque([spec.entrance_room_id])
        visited.add(spec.entrance_room_id)
        while queue:
            cur = queue.popleft()
            for nb in adj.get(cur, set()):
                if nb not in visited:
                    visited.add(nb)
                    queue.append(nb)

        unreachable = sorted(set(adj.keys()) - visited)
        if unreachable:
            errors.append(
                f"Rooms unreachable from entrance '{spec.entrance_room_id}': {unreachable}"
            )
            errors.append("Fix: add doorways so every room is BFS-reachable from the entrance.")

        # Floor connectivity via staircases
        floors_with_rooms = {r.floor for r in spec.rooms}
        connected: set[int] = {0}
        for st in spec.staircases:
            connected.add(st.from_floor)
            connected.add(st.to_floor)
        disconnected = floors_with_rooms - connected
        if disconnected:
            errors.append(
                f"Floors with rooms but no staircase: {sorted(disconnected)}. "
                "Add a staircase connecting these floors."
            )

        return len(errors) == 0, errors

    # ------------------------------------------------------------------
    # Layer 3 — Geometry consistency
    # ------------------------------------------------------------------

    def validate_geometry(self, spec: BuildingSpec) -> tuple[bool, list[str]]:
        """
        Checks doorway widths vs wall lengths, staircase floor bounds,
        and flags suspiciously small rooms.
        """
        errors:   list[str] = []
        warnings: list[str] = []

        for room in spec.rooms:
            for dw in room.doorways:
                wall_len = (
                    room.dimensions.width
                    if dw.wall_side.value in ("north", "south")
                    else room.dimensions.depth
                )
                if dw.width >= wall_len:
                    errors.append(
                        f"Room '{room.id}': doorway to '{dw.to_room_id}' "
                        f"width={dw.width}m ≥ wall length={wall_len:.2f}m"
                    )

        for st in spec.staircases:
            rooms_on_from = [r for r in spec.rooms if r.floor == st.from_floor]
            if not rooms_on_from:
                errors.append(
                    f"Staircase '{st.id}' from_floor={st.from_floor} has no rooms."
                )

        for room in spec.rooms:
            area = room.dimensions.width * room.dimensions.depth
            if area < 1.0:
                warnings.append(
                    f"Room '{room.id}' ({room.type.value}) area={area:.2f}m² is very small."
                )

        return len(errors) == 0, errors

    # ------------------------------------------------------------------
    # Combined entry point
    # ------------------------------------------------------------------

    def validate_all(self, data: dict) -> ValidationResult:
        """Run all three validation layers and return a unified result."""
        spec, schema_errors = self.validate_schema(data)
        if spec is None:
            return ValidationResult(is_valid=False, schema_errors=schema_errors)

        conn_ok,  conn_errors  = self.validate_connectivity(spec)
        geom_ok,  geom_errors  = self.validate_geometry(spec)

        # Collect geometry warnings (non-fatal)
        _, geom_warnings_raw = self.validate_geometry(spec)
        # Re-run for warnings only (small rooms) — already captured above
        warnings: list[str] = []
        for room in spec.rooms:
            if room.dimensions.width * room.dimensions.depth < 1.0:
                warnings.append(
                    f"Room '{room.id}' has area < 1 m² — check dimensions."
                )

        is_valid = not schema_errors and conn_ok and geom_ok

        return ValidationResult(
            is_valid=is_valid,
            schema_errors=schema_errors,
            connectivity_errors=conn_errors,
            geometry_errors=geom_errors,
            warnings=warnings,
            spec=spec,
        )
