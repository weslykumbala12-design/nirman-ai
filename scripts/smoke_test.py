"""
NIRMAN AI -- End-to-end smoke test
Uploads a synthetic test image, runs the full VLM planning pipeline,
validates the spec, and prints results. Does NOT require Blender.
"""
from __future__ import annotations
import asyncio
import base64
import io
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

# ── Create a simple synthetic "building photo" (100x100 grey PNG) ────────────
try:
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (400, 300), color=(180, 160, 140))
    draw = ImageDraw.Draw(img)
    # Draw simple building outline
    draw.rectangle([50, 80, 350, 280], outline=(60, 40, 20), width=3)   # building
    draw.rectangle([160, 180, 240, 280], outline=(60, 40, 20), width=2) # door
    draw.rectangle([70, 110, 130, 160], outline=(60, 40, 20), width=2)  # window L
    draw.rectangle([270, 110, 330, 160], outline=(60, 40, 20), width=2) # window R
    draw.rectangle([50, 10, 350, 80], outline=(80, 60, 40), width=2)    # roof
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    img_bytes = buf.getvalue()
    img_b64 = base64.b64encode(img_bytes).decode()
    print("[IMG] Synthetic building image created (400x300 JPEG)")
except ImportError:
    # Fallback: 1x1 white pixel
    img_b64 = "/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAABAAEDASIAAhEBAxEB/8QAFgABAQEAAAAAAAAAAAAAAAAABgUEB"
    print("[IMG] Using fallback 1-pixel image")

# ── Run the planning pipeline ─────────────────────────────────────────────────
async def main():
    from nirman.vlm.provider import VLMProviderFactory
    from nirman.vlm.planner import VLMPlanner
    from nirman.vlm.prompts import PromptBuilder
    from nirman.graph.models import GraphCell, CellType, PhotoEntry, ContextSelection
    from nirman.validation.validator import SpecificationValidator

    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        print("[ERROR] GEMINI_API_KEY not set"); sys.exit(1)

    print(f"[VLM] Connecting to Gemini...")
    provider = VLMProviderFactory.create("gemini", api_key)
    planner  = VLMPlanner(provider)

    # Build a minimal context selection (1 exterior photo cell)
    photo = PhotoEntry(
        id="p1", file_path="test.jpg", prompt="Front exterior of a 2-storey house",
        cell_id="cell_ext", encoded_data=img_b64
    )
    cell = GraphCell(
        id="cell_ext", cell_type=CellType.EXTERIOR_FACADE,
        photos=[photo], cell_prompt="Exterior facade of a simple 2-floor residential building"
    )
    ctx = ContextSelection(
        selected_cells=[cell],
        total_photos=1,
        total_tokens_estimated=600,
        selection_reason="Smoke test"
    )

    user_request = (
        "Generate a simple 2-floor house with: ground floor having a living room, kitchen, "
        "and bathroom; first floor having 2 bedrooms and a bathroom. "
        "All rooms must be connected by doorways. Include a staircase."
    )

    print(f"[VLM] Sending planning request to Gemini...")
    spec_dict, vlm_resp = planner.plan_building(ctx, user_request, failure_history=[])

    print(f"\n[VLM] Tokens used: {vlm_resp.input_tokens} in + {vlm_resp.output_tokens} out")
    print(f"[VLM] Model: {vlm_resp.model}")

    if spec_dict is None:
        print("[FAIL] VLM returned no JSON. Raw response:")
        print(vlm_resp.text[:500])
        sys.exit(1)

    print(f"\n[SPEC] Received BuildingSpec JSON with {len(spec_dict.get('rooms', []))} rooms")

    # ── Validate ──────────────────────────────────────────────────────────────
    print("\n[VALIDATE] Running spec validator...")
    validator = SpecificationValidator()
    result = validator.validate_all(spec_dict)

    print(f"  Schema errors:       {result.schema_errors or 'none'}")
    print(f"  Connectivity errors: {result.connectivity_errors or 'none'}")
    print(f"  Geometry errors:     {result.geometry_errors or 'none'}")
    print(f"  Valid:               {result.is_valid}")

    if result.is_valid and result.spec:
        spec = result.spec
        print(f"\n[SUCCESS] Valid BuildingSpec:")
        print(f"  Floors:     {spec.num_floors}")
        print(f"  Rooms:      {[r.id for r in spec.rooms]}")
        print(f"  Staircases: {[s.id for s in spec.staircases]}")
        print(f"  Entrance:   {spec.entrance_room_id}")
        print(f"  Roof type:  {spec.roof.type}")

        # Save spec to file
        out_path = Path("outputs") / "smoke_test_spec.json"
        out_path.parent.mkdir(exist_ok=True)
        out_path.write_text(json.dumps(spec_dict, indent=2))
        print(f"\n[SAVED] Spec written to {out_path}")
    else:
        print("\n[WARN] Spec has errors but may still be usable. Raw spec preview:")
        print(json.dumps(spec_dict, indent=2)[:800])

    print("\n=== Smoke test complete ===\n")


if __name__ == "__main__":
    asyncio.run(main())
