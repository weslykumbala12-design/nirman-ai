"""
NIRMAN AI — Photo Classifier
Classifies building photographs into context cell types using filename
heuristics (highest priority), user hints, and basic image content analysis.
"""
from __future__ import annotations
import os
from pathlib import Path
from typing import Optional

from .models import CellType


class PhotoClassifier:
    """Classifies photos into building cell types."""

    # (keywords, cell_type) — checked in order, first match wins
    FILENAME_RULES: list[tuple[list[str], CellType]] = [
        (["exterior", "facade", "front", "rear", "side", "outside", "elevation"], CellType.EXTERIOR_FACADE),
        (["stair", "stairs", "staircase", "landing", "step", "steps"],            CellType.STAIRCASE_LANDING),
        (["roof", "terrace", "rooftop", "top_floor", "top-floor"],                 CellType.ROOF_TERRACE),
        (["ground", "floor_0", "floor0", "lobby", "entrance", "entry", "ground_floor"], CellType.GROUND_FLOOR_INTERIOR),
        (["floor_1", "floor1", "floor_2", "floor2", "upper", "first_floor", "second_floor"], CellType.UPPER_FLOOR_INTERIOR),
    ]

    HINT_MAP: dict[str, CellType] = {
        "exterior":  CellType.EXTERIOR_FACADE,
        "facade":    CellType.EXTERIOR_FACADE,
        "stairs":    CellType.STAIRCASE_LANDING,
        "staircase": CellType.STAIRCASE_LANDING,
        "landing":   CellType.STAIRCASE_LANDING,
        "roof":      CellType.ROOF_TERRACE,
        "terrace":   CellType.ROOF_TERRACE,
        "ground":    CellType.GROUND_FLOOR_INTERIOR,
        "interior":  CellType.GROUND_FLOOR_INTERIOR,
        "kitchen":   CellType.GROUND_FLOOR_INTERIOR,
        "living":    CellType.GROUND_FLOOR_INTERIOR,
        "lobby":     CellType.GROUND_FLOOR_INTERIOR,
        "upper":     CellType.UPPER_FLOOR_INTERIOR,
        "bedroom":   CellType.UPPER_FLOOR_INTERIOR,
        "bathroom":  CellType.UPPER_FLOOR_INTERIOR,
    }

    def classify_by_filename(self, filename: str) -> tuple[CellType, float]:
        """Heuristic keyword matching on the file stem."""
        stem = Path(filename).stem.lower().replace("-", "_").replace(" ", "_")
        for keywords, cell_type in self.FILENAME_RULES:
            if any(kw in stem for kw in keywords):
                return cell_type, 0.80
        return CellType.UNKNOWN, 0.30

    def classify_by_hint(self, hint: str) -> tuple[CellType, float]:
        """Match a user-supplied hint string."""
        hl = hint.lower().strip()
        for key, ct in self.HINT_MAP.items():
            if key in hl:
                return ct, 0.95
        return CellType.UNKNOWN, 0.30

    def classify_by_content(self, image_path: str) -> tuple[CellType, float]:
        """
        Lightweight content-based proxy: overall brightness.
        Bright → likely exterior; very dark → possibly enclosed staircase.
        """
        try:
            from PIL import Image
            import numpy as np
            img = Image.open(image_path).convert("L")
            brightness = float(np.array(img).mean())
            if brightness > 160:
                return CellType.EXTERIOR_FACADE, 0.45
            if brightness < 60:
                return CellType.STAIRCASE_LANDING, 0.35
            return CellType.GROUND_FLOOR_INTERIOR, 0.40
        except Exception:
            return CellType.UNKNOWN, 0.10

    def classify(
        self, image_path: str, user_hint: Optional[str] = None
    ) -> tuple[CellType, float]:
        """
        Combined classification:
        1. User hint (highest authority, 0.95 confidence)
        2. Filename keywords (0.80)
        3. Image content brightness (0.35–0.45)
        """
        if user_hint:
            ct, conf = self.classify_by_hint(user_hint)
            if ct != CellType.UNKNOWN:
                return ct, conf

        ct, conf = self.classify_by_filename(image_path)
        if ct != CellType.UNKNOWN:
            return ct, conf

        return self.classify_by_content(image_path)
