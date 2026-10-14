"""
Pytest configuration and shared fixtures for NIRMAN AI tests.
No real Blender, MongoDB, or VLM API required.
"""
import pytest


@pytest.fixture
def minimal_valid_spec():
    """A minimal 1-floor spec that passes all validators."""
    return {
        "num_floors": 1,
        "floors": [{"level": 0, "slab_thickness": 0.2, "room_ids": ["lobby", "kitchen"]}],
        "rooms": [
            {
                "id": "lobby", "type": "lobby", "floor": 0,
                "dimensions": {"width": 5.0, "depth": 4.0, "height": 3.0},
                "position": {"x": 0.0, "y": 0.0},
                "doorways": [
                    {"to_room_id": "kitchen", "width": 0.9, "height": 2.1,
                     "wall_side": "east", "position_along_wall": 0.5,
                     "confidence": "assumed"}
                ],
                "windows": [],
                "confidence": "assumed",
                "is_entrance": True,
                "notes": None,
            },
            {
                "id": "kitchen", "type": "kitchen", "floor": 0,
                "dimensions": {"width": 3.0, "depth": 3.0, "height": 3.0},
                "position": {"x": 5.0, "y": 0.0},
                "doorways": [],
                "windows": [
                    {"width": 1.2, "height": 1.0, "sill_height": 0.9,
                     "wall_side": "north", "position_along_wall": 0.5,
                     "confidence": "assumed"}
                ],
                "confidence": "assumed",
                "is_entrance": False,
                "notes": None,
            },
        ],
        "staircases": [],
        "walls": [],
        "roof": {"type": "flat", "pitch_degrees": None,
                 "has_terrace_access": False, "access_staircase_id": None},
        "entrance_room_id": "lobby",
        "style_notes": None,
        "source_confidence": "assumed",
        "has_interior_photos": False,
        "has_measurements": False,
    }


@pytest.fixture
def two_floor_spec(minimal_valid_spec):
    """A 2-floor spec with a staircase — extends minimal_valid_spec."""
    spec = dict(minimal_valid_spec)
    spec["num_floors"] = 2
    spec["floors"].append(
        {"level": 1, "slab_thickness": 0.2, "room_ids": ["bedroom"]}
    )
    spec["rooms"].append({
        "id": "bedroom", "type": "bedroom", "floor": 1,
        "dimensions": {"width": 4.0, "depth": 3.5, "height": 3.0},
        "position": {"x": 0.0, "y": 0.0},
        "doorways": [],
        "windows": [],
        "confidence": "assumed",
        "is_entrance": False,
        "notes": None,
    })
    spec["staircases"] = [{
        "id": "stair_main", "from_floor": 0, "to_floor": 1,
        "position": {"x": 3.0, "y": 2.0},
        "direction": "north",
        "width": 1.0,
        "run_depth": 0.28,
        "rise_height": 0.175,
        "num_steps": None,
        "opening_width": 1.2,
        "opening_depth": 2.5,
    }]
    return spec


@pytest.fixture
def mock_execution_result_success():
    """A fake successful ExecutionResult."""
    from unittest.mock import MagicMock
    er = MagicMock()
    er.success         = True
    er.stdout          = "NIRMAN_SUCCESS"
    er.stderr          = ""
    er.exit_code       = 0
    er.execution_time_s = 12.4
    er.gltf_path       = "/fake/building.gltf"
    er.blend_path      = "/fake/building.blend"
    er.error_message   = None
    er.error_detail    = None
    return er


@pytest.fixture
def mock_execution_result_failure():
    """A fake failed ExecutionResult."""
    from unittest.mock import MagicMock
    er = MagicMock()
    er.success         = False
    er.stdout          = "NIRMAN_ERROR:{\"error\": \"NameError: bpy not defined\"}"
    er.stderr          = "Traceback..."
    er.exit_code       = 1
    er.execution_time_s = 3.1
    er.gltf_path       = None
    er.blend_path      = None
    er.error_message   = "Script execution failed"
    er.error_detail    = {"error": "NameError: bpy not defined"}
    return er
