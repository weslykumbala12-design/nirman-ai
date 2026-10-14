"""
NIRMAN AI — VLM Planner
Orchestrates VLM calls: planning, correction, and targeted room edits.
"""
from __future__ import annotations
import base64
import json
import logging
import re
from pathlib import Path
from typing import Optional

from .provider import BaseVLMProvider, VLMMessage, VLMResponse
from .prompts import PromptBuilder

logger = logging.getLogger(__name__)


class VLMPlanner:
    """Generates and corrects BuildingSpec JSON via a VLM provider."""

    def __init__(self, provider: BaseVLMProvider) -> None:
        self.provider = provider
        self.pb       = PromptBuilder()

    # ------------------------------------------------------------------
    # Primary: full building plan
    # ------------------------------------------------------------------

    def plan_building(
        self,
        context_selection,
        user_request: str,
        failure_history: list[dict] = [],
    ) -> tuple[Optional[dict], VLMResponse]:
        """
        Generate a BuildingSpec JSON from selected graph context + user request.
        Returns (parsed_dict | None, raw VLMResponse).
        """
        system  = self.pb.build_system_prompt()
        prompt  = self.pb.build_planning_prompt(context_selection, user_request, failure_history)
        images  = self._collect_images(context_selection)
        msgs    = [VLMMessage(role="user", content=prompt, images=images)]
        resp    = self.provider.generate(msgs, system)
        spec    = self._parse_json(resp.text)
        if spec is None:
            logger.warning("VLM returned non-JSON. Snippet: %s", resp.text[:200])
        return spec, resp

    # ------------------------------------------------------------------
    # Correction loop
    # ------------------------------------------------------------------

    def correct_specification(
        self, spec: dict, errors: list[str]
    ) -> tuple[Optional[dict], VLMResponse]:
        """Ask the VLM to fix validation errors in an existing spec."""
        system  = self.pb.build_system_prompt()
        prompt  = self.pb.build_correction_prompt(spec, errors)
        msgs    = [VLMMessage(role="user", content=prompt)]
        resp    = self.provider.generate(msgs, system)
        return self._parse_json(resp.text), resp

    # ------------------------------------------------------------------
    # Targeted room edit
    # ------------------------------------------------------------------

    def edit_room(
        self,
        room_id: str,
        edit_request: str,
        current_spec: dict,
        context_selection,
    ) -> tuple[Optional[dict], VLMResponse]:
        """Generate a modified spec targeting a single room."""
        system  = self.pb.build_system_prompt()
        prompt  = self.pb.build_room_edit_prompt(room_id, edit_request, current_spec, context_selection)
        images  = self._collect_images(context_selection)
        msgs    = [VLMMessage(role="user", content=prompt, images=images)]
        resp    = self.provider.generate(msgs, system)
        return self._parse_json(resp.text), resp

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _collect_images(self, context_selection) -> list[str]:
        images: list[str] = []
        for cell in context_selection.selected_cells:
            for photo in cell.photos:
                if photo.encoded_data:
                    images.append(photo.encoded_data)
                elif photo.file_path and Path(photo.file_path).exists():
                    images.append(self._encode_image(photo.file_path))
        return images

    def _encode_image(self, file_path: str) -> str:
        with open(file_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    def _parse_json(self, text: str) -> Optional[dict]:
        """Strip markdown fences and parse JSON. Returns None on failure."""
        text = text.strip()
        # Remove ```json … ``` or ``` … ``` fences
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.MULTILINE)
        text = re.sub(r"```\s*$",          "", text, flags=re.MULTILINE)
        text = text.strip()
        # Find the outermost { … } block
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            text = m.group(0)
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            logger.error("JSON parse failed: %s | text[:300]=%s", exc, text[:300])
            return None
