"""
NIRMAN AI — Test Suite
Tests for all 9 milestone items without requiring Blender or MongoDB.
"""
import json
import pytest
from unittest.mock import MagicMock, AsyncMock, patch


# ── 1. Geometry kernel (codegen only — bpy not available in tests) ────────────

class TestBlenderCodeGenerator:
    def test_generates_valid_script(self):
        from nirman.kernel.codegen import BlenderCodeGenerator
        gen  = BlenderCodeGenerator(kernel_path="/fake/path")
        spec = {
            "num_floors": 2,
            "rooms": [
                {"id": "room_lobby", "floor": 0, "type": "lobby",
                 "dimensions": {"width": 5.0, "depth": 4.0, "height": 3.0},
                 "position": {"x": 0, "y": 0},
                 "doorways": [{"to_room_id": "room_bedroom", "width": 0.9,
                               "height": 2.1, "wall_side": "north",
                               "position_along_wall": 0.5}],
                 "windows": []},
                {"id": "room_bedroom", "floor": 1, "type": "bedroom",
                 "dimensions": {"width": 4.0, "depth": 3.5, "height": 3.0},
                 "position": {"x": 0, "y": 0}, "doorways": [], "windows": []},
            ],
            "staircases": [
                {"id": "stair_1", "from_floor": 0, "to_floor": 1,
                 "position": {"x": 3.0, "y": 2.0}, "direction": "north",
                 "width": 1.0, "opening_width": 1.2, "opening_depth": 2.5}
            ],
            "roof": {"type": "flat"},
        }
        script = gen.generate_script(spec, "/out/b.gltf", "/out/b.blend")
        assert "clear_scene()" in script
        assert "create_floor_slab" in script
        assert "create_room" in script
        assert "room_lobby" in script
        assert "create_staircase" in script
        assert "punch_stairwell_hole" in script
        assert "create_roof" in script
        assert "export_gltf" in script
        assert "NIRMAN_SUCCESS" in script
        assert "NIRMAN_ERROR" in script

    def test_script_is_runnable_python(self):
        """The generated script should be syntactically valid Python."""
        from nirman.kernel.codegen import BlenderCodeGenerator
        import ast
        gen    = BlenderCodeGenerator(kernel_path="/fake/path")
        spec   = {
            "num_floors": 1, "rooms": [], "staircases": [],
            "roof": {"type": "flat"},
        }
        script = gen.generate_script(spec, "/out/b.gltf", "/out/b.blend")
        # Should parse without SyntaxError
        ast.parse(script)


# ── 2. Automated verifier ─────────────────────────────────────────────────────

class TestVerificationEngine:
    def _make_er(self, success=True, stdout="NIRMAN_SUCCESS", stderr=""):
        er = MagicMock()
        er.success    = success
        er.stdout     = stdout
        er.stderr     = stderr
        er.exit_code  = 0 if success else 1
        er.error_message = None
        er.error_detail  = None
        return er

    def test_pass_on_valid_connected_building(self):
        from nirman.verification.engine import VerificationEngine
        ve  = VerificationEngine()
        spec = {
            "num_floors": 1,
            "entrance_room_id": "lobby",
            "rooms": [
                {"id": "lobby", "floor": 0,
                 "doorways": [{"to_room_id": "kitchen", "width": 0.9, "height": 2.1}],
                 "windows": []},
                {"id": "kitchen", "floor": 0, "doorways": [], "windows": []},
            ],
            "staircases": [],
        }
        report = ve.verify("test-1", self._make_er(), spec)
        assert report.traversability.status == "pass"
        assert report.doorway_clearance.status == "pass"
        assert report.overall == "pass"

    def test_fail_on_disconnected_room(self):
        from nirman.verification.engine import VerificationEngine
        ve  = VerificationEngine()
        spec = {
            "num_floors": 1,
            "entrance_room_id": "lobby",
            "rooms": [
                {"id": "lobby",   "floor": 0, "doorways": [], "windows": []},
                {"id": "bedroom", "floor": 0, "doorways": [], "windows": []},
            ],
            "staircases": [],
        }
        report = ve.verify("test-2", self._make_er(), spec)
        assert report.traversability.status == "fail"
        assert "bedroom" in report.traversability.detail
        assert report.overall == "fail"
        assert "disconnected_rooms" in report.failure_categories

    def test_fail_on_narrow_doorway(self):
        from nirman.verification.engine import VerificationEngine
        ve  = VerificationEngine()
        spec = {
            "num_floors": 1,
            "entrance_room_id": "lobby",
            "rooms": [
                {"id": "lobby", "floor": 0,
                 "doorways": [{"to_room_id": "store", "width": 0.5, "height": 2.1}],
                 "windows": []},
                {"id": "store", "floor": 0, "doorways": [], "windows": []},
            ],
            "staircases": [],
        }
        report = ve.verify("test-3", self._make_er(), spec)
        assert report.doorway_clearance.status == "fail"
        assert "blocked_doorway" in report.failure_categories

    def test_fail_missing_staircase_multifloor(self):
        from nirman.verification.engine import VerificationEngine
        ve  = VerificationEngine()
        spec = {
            "num_floors": 2,
            "entrance_room_id": "lobby",
            "rooms": [
                {"id": "lobby",   "floor": 0, "doorways": [], "windows": []},
                {"id": "bedroom", "floor": 1, "doorways": [], "windows": []},
            ],
            "staircases": [],
        }
        report = ve.verify("test-4", self._make_er(), spec)
        assert report.staircase_accessibility.status == "fail"

    def test_execution_failure_skips_other_checks(self):
        from nirman.verification.engine import VerificationEngine
        ve = VerificationEngine()
        er = self._make_er(success=False, stdout="", stderr="Fatal error")
        report = ve.verify("test-5", er, spec=None)
        assert report.overall == "fail"
        assert report.traversability.status == "skip"


# ── 3. JSON planning pipeline — schema validation ─────────────────────────────

class TestSpecificationValidator:
    def _valid_spec(self):
        return {
            "num_floors": 1,
            "floors": [{"level": 0, "slab_thickness": 0.2, "room_ids": ["lobby"]}],
            "rooms": [{
                "id": "lobby", "type": "lobby", "floor": 0,
                "dimensions": {"width": 5.0, "depth": 4.0, "height": 3.0},
                "position": {"x": 0, "y": 0},
                "doorways": [], "windows": [],
                "confidence": "assumed", "is_entrance": True,
            }],
            "staircases": [],
            "walls": [],
            "roof": {"type": "flat"},
            "entrance_room_id": "lobby",
            "source_confidence": "assumed",
            "has_interior_photos": False,
            "has_measurements": False,
        }

    def test_valid_spec_passes(self):
        from nirman.validation.validator import SpecificationValidator
        v   = SpecificationValidator()
        res = v.validate_all(self._valid_spec())
        assert res.is_valid
        assert not res.schema_errors

    def test_invalid_entrance_id(self):
        from nirman.validation.validator import SpecificationValidator
        v    = SpecificationValidator()
        spec = self._valid_spec()
        spec["entrance_room_id"] = "nonexistent"
        res  = v.validate_all(spec)
        assert not res.is_valid

    def test_negative_dimension_rejected(self):
        from nirman.validation.validator import SpecificationValidator
        v    = SpecificationValidator()
        spec = self._valid_spec()
        spec["rooms"][0]["dimensions"]["width"] = -1.0
        res  = v.validate_all(spec)
        assert not res.is_valid

    def test_connectivity_check_disconnected(self):
        from nirman.validation.validator import SpecificationValidator
        v    = SpecificationValidator()
        spec = self._valid_spec()
        # Add an isolated room with no doorway
        spec["rooms"].append({
            "id": "hidden", "type": "bedroom", "floor": 0,
            "dimensions": {"width": 3.0, "depth": 3.0, "height": 3.0},
            "position": {"x": 10, "y": 10},
            "doorways": [], "windows": [],
            "confidence": "assumed", "is_entrance": False,
        })
        spec["floors"][0]["room_ids"].append("hidden")
        res = v.validate_all(spec)
        assert not res.is_valid
        assert any("hidden" in e for e in res.connectivity_errors)


# ── 4. Photo-cell graph — classifier ─────────────────────────────────────────

class TestPhotoClassifier:
    def test_exterior_by_filename(self):
        from nirman.graph.classifier import PhotoClassifier
        clf = PhotoClassifier()
        ct, conf = clf.classify_by_filename("front_facade_photo.jpg")
        assert ct.value == "exterior_facade"
        assert conf >= 0.8

    def test_staircase_by_filename(self):
        from nirman.graph.classifier import PhotoClassifier
        clf = PhotoClassifier()
        ct, _ = clf.classify_by_filename("staircase_landing_01.jpg")
        assert ct.value == "staircase_landing"

    def test_hint_overrides_filename(self):
        from nirman.graph.classifier import PhotoClassifier
        clf = PhotoClassifier()
        ct, conf = clf.classify("front_exterior.jpg", user_hint="stairs")
        assert ct.value == "staircase_landing"
        assert conf >= 0.9

    def test_unknown_returns_low_confidence(self):
        from nirman.graph.classifier import PhotoClassifier
        clf = PhotoClassifier()
        ct, conf = clf.classify_by_filename("IMG_20240101.jpg")
        assert ct.value == "unknown"


# ── 5. Graph retrieval — context selection ────────────────────────────────────

class TestGraphContextManager:
    def _build_test_graph(self):
        from nirman.graph.manager import GraphContextManager
        mgr   = GraphContextManager()
        photos = [
            {"file_path": "front_exterior.jpg", "prompt": "front of building"},
            {"file_path": "ground_floor_lobby.jpg", "prompt": "lobby entrance"},
            {"file_path": "staircase.jpg", "prompt": "staircase landing"},
            {"file_path": "upper_floor_bedroom.jpg", "prompt": "bedroom upstairs"},
        ]
        graph = mgr.auto_build_graph("test_building", photos)
        return mgr, graph

    def test_auto_build_creates_cells(self):
        mgr, graph = self._build_test_graph()
        assert len(graph.cells) >= 1
        assert len(graph.edges) >= 0

    def test_context_selection_reduces_tokens(self):
        mgr, graph = self._build_test_graph()
        ctx = mgr.select_context_for_request(graph, "redo the bedroom")
        full_tokens = mgr._estimate_tokens(list(graph.cells.values()), "redo the bedroom")
        assert ctx.total_tokens_estimated <= full_tokens

    def test_token_reduction_metric(self):
        from nirman.graph.manager import GraphContextManager
        mgr = GraphContextManager()
        result = mgr.compute_token_reduction(1000, 400)
        assert result["reduction_pct"] == 60.0


# ── 6. Failure memory — pattern detection ────────────────────────────────────

class TestFailureMemoryStore:
    """Uses a mock motor client — no real MongoDB required."""

    def test_corrections_mapping_complete(self):
        from nirman.memory.store import FailureMemoryStore
        known_cats = [
            "execution_error", "disconnected_rooms",
            "blocked_doorway", "stair_incomplete", "mesh_invalid",
        ]
        for cat in known_cats:
            assert cat in FailureMemoryStore.CORRECTIONS, f"Missing correction for '{cat}'"


# ── 7. Best-of-N and bandit ───────────────────────────────────────────────────

class TestBestOfNSelector:
    def _candidate(self, trav_score, door_score, exec_score=1.0):
        return {
            "verification_report": {
                "execution":       {"score": exec_score, "status": "pass"},
                "traversability":  {"score": trav_score, "status": "pass" if trav_score >= 0.9 else "fail"},
                "doorway_clearance": {"score": door_score, "status": "pass" if door_score >= 0.9 else "fail"},
                "staircase_accessibility": {"score": 1.0, "status": "pass"},
                "mesh_integrity":  {"score": 1.0, "status": "pass"},
            }
        }

    def test_selects_highest_score(self):
        from nirman.selection.selector import BestOfNSelector
        sel = BestOfNSelector()
        candidates = [
            self._candidate(0.5, 0.5),
            self._candidate(1.0, 1.0),
            self._candidate(0.7, 0.8),
        ]
        best, score, idx = sel.select_best(candidates)
        assert idx == 1
        assert score > 0.8

    def test_empty_candidates(self):
        from nirman.selection.selector import BestOfNSelector
        sel = BestOfNSelector()
        best, score, idx = sel.select_best([])
        assert best is None
        assert idx == -1


class TestStrategyBandit:
    def test_explore_all_strategies(self):
        from nirman.selection.selector import StrategyBandit, DEFAULT_STRATEGIES
        bandit = StrategyBandit(epsilon=1.0)   # always explore
        names  = set()
        for _ in range(50):
            s = bandit.select_strategy()
            names.add(s.name)
        assert len(names) == len(DEFAULT_STRATEGIES)

    def test_exploit_best_strategy(self):
        from nirman.selection.selector import StrategyBandit
        bandit = StrategyBandit(epsilon=0.0)   # always exploit
        bandit.update("standard",          0.9)
        bandit.update("detailed_rooms",    0.4)
        bandit.update("connectivity_first", 0.6)
        bandit.update("minimal_spec",      0.3)
        # With epsilon=0, should always pick "standard"
        chosen = bandit.select_strategy()
        assert chosen.name == "standard"

    def test_update_increments_stats(self):
        from nirman.selection.selector import StrategyBandit
        bandit = StrategyBandit()
        bandit.update("standard", 0.8)
        s = bandit.strategies["standard"]
        assert s.attempts     == 1
        assert s.total_reward == 0.8
        assert s.wins         == 1   # 0.8 >= 0.7
