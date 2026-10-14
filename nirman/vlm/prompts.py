"""
NIRMAN AI — VLM Prompt Builder
All prompt strings for the planning, correction, and editing workflows.
"""
from __future__ import annotations
import json


# Full BuildingSpec JSON schema reference embedded into prompts
_SCHEMA_REFERENCE = """
{
  "num_floors": <int ≥1>,
  "floors": [
    {"level": <int>, "slab_thickness": 0.2, "room_ids": ["room_id_1", ...]}
  ],
  "rooms": [
    {
      "id": "<unique_string>",
      "type": "living_room|bedroom|kitchen|bathroom|corridor|staircase|lobby|office|storage|terrace|other",
      "floor": <int>,
      "dimensions": {"width": <m>, "depth": <m>, "height": <m>},
      "position": {"x": <m>, "y": <m>},
      "doorways": [
        {
          "to_room_id": "<other_room_id>",
          "width": <m ≥0.8>,
          "height": <m ≥2.0>,
          "wall_side": "north|south|east|west",
          "position_along_wall": <0.0–1.0>,
          "confidence": "measured|inferred|assumed"
        }
      ],
      "windows": [
        {
          "width": <m>, "height": <m>, "sill_height": <m ≥0.3>,
          "wall_side": "north|south|east|west",
          "position_along_wall": <0.0–1.0>,
          "confidence": "measured|inferred|assumed"
        }
      ],
      "confidence": "measured|inferred|assumed",
      "is_entrance": <bool>,
      "notes": "<optional string>"
    }
  ],
  "staircases": [
    {
      "id": "<unique_string>",
      "from_floor": <int>,
      "to_floor": <int>,
      "position": {"x": <m>, "y": <m>},
      "direction": "north|south|east|west",
      "width": <m ≥0.9>,
      "run_depth": <m ≥0.25>,
      "rise_height": <m ≤0.22>,
      "num_steps": <int or null>,
      "opening_width": <m ≥1.0>,
      "opening_depth": <m ≥2.0>
    }
  ],
  "walls": [],
  "roof": {
    "type": "flat|gabled|hipped",
    "pitch_degrees": <0–60 or null>,
    "has_terrace_access": <bool>,
    "access_staircase_id": "<staircase_id or null>"
  },
  "entrance_room_id": "<room_id>",
  "style_notes": "<optional string>",
  "source_confidence": "measured|inferred|assumed",
  "has_interior_photos": <bool>,
  "has_measurements": <bool>
}
"""


class PromptBuilder:
    """Builds all prompt strings for NIRMAN AI's VLM interactions."""

    @staticmethod
    def build_system_prompt() -> str:
        return (
            "You are NIRMAN AI's architectural planning engine. "
            "Your role is to analyse building photographs and user requirements, "
            "then produce a STRICTLY VALID JSON building specification.\n\n"

            "## Core responsibilities\n"
            "1. Interpret photographs to infer room types, approximate dimensions, "
            "connectivity, and architectural style.\n"
            "2. Produce output that is geometrically valid and functionally traversable.\n"
            "3. Label every dimension and layout decision with a confidence level: "
            "'measured' (from a known reference), 'inferred' (from visual evidence), "
            "or 'assumed' (best-guess default).\n"
            "4. NEVER claim exact reconstruction when photographs do not provide enough "
            "information. Be honest about what is inferred.\n\n"

            "## Traversability requirement (CRITICAL)\n"
            "Every room MUST be reachable from the entrance room via doorways. "
            "If you place a room, you MUST add a doorway connecting it to the rest of "
            "the building. Imagine walking a BFS from the entrance — no room must be "
            "left unreachable.\n\n"

            "## Wall construction model\n"
            "Use a segment-based mental model for walls:\n"
            "- A wall is a sequence of solid segments separated by openings.\n"
            "- Doorways are GAPS between segments — they are NOT geometry to be "
            "  subtracted later. Simply leave the opening unspecified.\n"
            "- Minimum doorway: width ≥ 0.8 m, height ≥ 2.0 m.\n\n"

            "## Staircases\n"
            "- A staircase must span from `from_floor` to `to_floor` completely.\n"
            "- Include a stairwell opening in the destination floor slab.\n"
            "- opening_width ≥ 1.0 m, opening_depth ≥ 2.0 m.\n"
            "- If the building has N floors, at least N-1 staircases are required.\n\n"

            "## Output format\n"
            "Output ONLY a single JSON object. "
            "Do NOT wrap it in markdown code fences. "
            "Do NOT add any explanation text before or after the JSON. "
            "The JSON must conform exactly to the schema provided in the user message."
        )

    @staticmethod
    def build_planning_prompt(
        context_selection,
        user_request: str,
        failure_history: list[dict] = [],
    ) -> str:
        parts: list[str] = []

        # Describe selected cells
        parts.append("## Selected building context\n")
        for cell in context_selection.selected_cells:
            style_tag = (
                " [STYLE REFERENCE ONLY — do not modify room layout from this cell]"
                if cell.id in context_selection.style_only_cell_ids else ""
            )
            parts.append(
                f"### Cell: {cell.cell_type.value}{style_tag}\n"
                f"Description: {cell.cell_prompt}\n"
                f"Photos in this cell: {len(cell.photos)}\n"
                + (
                    "\n".join(f"  - {p.prompt}" for p in cell.photos if p.prompt)
                )
            )

        # User request
        parts.append(f"\n## User requirement\n{user_request}\n")

        # Failure history injection
        if failure_history:
            parts.append("## Previous failure corrections (MUST be avoided this attempt)\n")
            for entry in failure_history:
                parts.append(
                    f"- [{entry.get('failure_category', '?')} × {entry.get('occurrences', 1)}] "
                    f"{entry.get('correction', '')}"
                )
            parts.append("")

        # Schema reference
        parts.append("## Required JSON schema\n")
        parts.append(_SCHEMA_REFERENCE)

        # Final instructions
        parts.append(
            "\n## Instructions\n"
            "1. Analyse all attached photographs and the context descriptions above.\n"
            "2. Generate ONE JSON object matching the schema exactly.\n"
            "3. Set `has_interior_photos` and `has_measurements` truthfully.\n"
            "4. Ensure BFS reachability: every room must connect to the entrance via doorways.\n"
            "5. Use realistic metric dimensions (metres). Default floor height: 3.0 m.\n"
            "6. Position rooms on a 2D grid (position.x, position.y) without overlapping.\n"
            "7. Output ONLY the JSON object — no explanation, no markdown fences."
        )

        return "\n".join(parts)

    @staticmethod
    def build_correction_prompt(spec: dict, validation_errors: list[str]) -> str:
        errors_block = "\n".join(f"  - {e}" for e in validation_errors)
        return (
            "The following building specification has validation errors that must be fixed.\n\n"
            f"## Validation errors\n{errors_block}\n\n"
            "## Current (broken) specification\n"
            f"{json.dumps(spec, indent=2)}\n\n"
            "## Instructions\n"
            "Return a corrected version of the specification as a single JSON object.\n"
            "Fix ALL listed errors. Do not change parts of the spec not mentioned in the errors.\n"
            "Output ONLY the corrected JSON object."
        )

    @staticmethod
    def build_room_edit_prompt(
        room_id: str,
        edit_request: str,
        current_spec: dict,
        context_selection,
    ) -> str:
        cell_descs = "\n".join(
            f"- {c.cell_type.value}: {c.cell_prompt}" for c in context_selection.selected_cells
        )
        return (
            f"## Room edit request\n"
            f"Target room: `{room_id}`\n"
            f"Edit instruction: {edit_request}\n\n"
            f"## Relevant context\n{cell_descs}\n\n"
            "## Current full building specification\n"
            f"{json.dumps(current_spec, indent=2)}\n\n"
            "## Instructions\n"
            f"Modify only the room with id `{room_id}` (and any directly affected doorways) "
            "to satisfy the edit instruction. Keep all other rooms unchanged.\n"
            "Ensure the modified spec still satisfies BFS traversability from the entrance.\n"
            "Output ONLY the complete updated JSON building specification."
        )

    @staticmethod
    def estimate_tokens(prompt: str, num_images: int) -> int:
        """Approximate token count: text chars/4 + 500 per image."""
        return len(prompt) // 4 + num_images * 500
