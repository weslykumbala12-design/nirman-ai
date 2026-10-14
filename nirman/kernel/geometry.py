"""
NIRMAN AI — Blender Geometry Kernel
Runs inside Blender's Python interpreter (bpy available at runtime).

DESIGN PRINCIPLE — SEGMENT-BASED WALL CONSTRUCTION
===================================================
Doorways and windows are NOT created by Boolean subtraction.
Instead, a wall is decomposed into an ordered list of solid segments
separated by empty gaps (openings). This produces clean, reliable geometry
that never suffers from Boolean failures or Z-fighting.

A wall with one central doorway:
    [LEFT SEGMENT] [  OPENING  ] [RIGHT SEGMENT]
                    ^ empty gap ^  + LINTEL above if door shorter than wall

Default clearances enforced by the geometry kernel:
    Doorway : ≥ 0.8 m wide × ≥ 2.0 m high
    Stair headroom : ≥ 2.0 m
    Stair rise : 0.175 m   run : 0.28 m
"""

import bpy
import bmesh
import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

# ── Constants ────────────────────────────────────────────────────────────────
FLOOR_HEIGHT   = 3.0      # default metres per floor
WALL_THICKNESS = 0.2
DOOR_W_MIN     = 0.8
DOOR_H_MIN     = 2.0
STAIR_RISE     = 0.175
STAIR_RUN      = 0.28
SLAB_THICKNESS = 0.2

# ── Tiny helpers ─────────────────────────────────────────────────────────────

@dataclass
class Vec2:
    x: float
    y: float

    def to_3d(self, z: float = 0.0) -> Tuple[float, float, float]:
        return (self.x, self.y, z)

    def dist(self, other: "Vec2") -> float:
        return math.sqrt((self.x - other.x) ** 2 + (self.y - other.y) ** 2)

    def unit_toward(self, other: "Vec2") -> Tuple[float, float]:
        d = self.dist(other)
        if d < 1e-9:
            return (1.0, 0.0)
        return ((other.x - self.x) / d, (other.y - self.y) / d)


@dataclass
class Opening:
    """An opening (door or window) expressed as a fraction along a wall."""
    position_frac: float   # 0 = wall start, 1 = wall end
    width:         float
    height:        float
    bottom_z:      float = 0.0   # 0 for doors; sill_height for windows


# ── Material cache ────────────────────────────────────────────────────────────

_MATERIALS: dict = {}

def create_material(
    name: str,
    color: Tuple[float, float, float, float] = (0.8, 0.8, 0.8, 1.0),
    metallic: float = 0.0,
    roughness: float = 0.8,
) -> "bpy.types.Material":
    """Create or retrieve a PBR material by name."""
    if name in _MATERIALS:
        return _MATERIALS[name]
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = color
        bsdf.inputs["Metallic"].default_value   = metallic
        bsdf.inputs["Roughness"].default_value  = roughness
    _MATERIALS[name] = mat
    return mat


def _assign_material(obj: "bpy.types.Object", mat: "bpy.types.Material") -> None:
    if obj.data.materials:
        obj.data.materials[0] = mat
    else:
        obj.data.materials.append(mat)


# ── Scene management ──────────────────────────────────────────────────────────

def clear_scene() -> None:
    """Remove all mesh objects and reset the material cache."""
    _MATERIALS.clear()
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for block in list(bpy.data.meshes):
        bpy.data.meshes.remove(block)


# ── Primitive: axis-aligned box ───────────────────────────────────────────────

def create_box(
    name: str,
    cx: float, cy: float, cz: float,
    sx: float, sy: float, sz: float,
    rotation_z: float = 0.0,
) -> "bpy.types.Object":
    """
    Create a box mesh centered at (cx, cy, cz) with size (sx, sy, sz),
    optionally rotated around Z.
    """
    mesh = bpy.data.meshes.new(name)
    obj  = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)

    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=(sx, sy, sz), verts=bm.verts)
    bm.to_mesh(mesh)
    bm.free()

    obj.location = (cx, cy, cz)
    if rotation_z:
        obj.rotation_euler[2] = rotation_z
    bpy.context.view_layer.update()
    return obj


# ── Floor slab ────────────────────────────────────────────────────────────────

def create_floor_slab(
    level: int,
    x: float, y: float,
    width: float, depth: float,
    thickness: float = SLAB_THICKNESS,
    stair_hole: Optional[dict] = None,
) -> "bpy.types.Object":
    """
    Create a floor slab at `level`.  The top surface sits at level*FLOOR_HEIGHT.
    stair_hole = {"x": float, "y": float, "w": float, "d": float} cuts a
    rectangular opening for the stairwell using vertex-level bmesh editing
    (no Boolean modifier needed).
    """
    top_z    = level * FLOOR_HEIGHT
    center_z = top_z - thickness / 2.0
    name     = f"slab_floor_{level}"

    if stair_hole is None:
        # Simple solid slab
        obj = create_box(name, x + width / 2, y + depth / 2, center_z, width, depth, thickness)
    else:
        # Build slab with rectangular hole using bmesh quad-loop method
        hx = stair_hole["x"]
        hy = stair_hole["y"]
        hw = stair_hole["w"]
        hd = stair_hole["d"]

        # Clamp hole to slab bounds
        hx = max(x + 0.01, min(hx, x + width  - hw - 0.01))
        hy = max(y + 0.01, min(hy, y + depth - hd - 0.01))

        mesh = bpy.data.meshes.new(name)
        obj  = bpy.data.objects.new(name, mesh)
        bpy.context.collection.objects.link(obj)

        bm   = bmesh.new()
        z0   = center_z - thickness / 2
        z1   = center_z + thickness / 2

        def add_face(verts_2d):
            bottom = [bm.verts.new((*v, z0)) for v in verts_2d]
            top    = [bm.verts.new((*v, z1)) for v in verts_2d]
            bm.faces.new(bottom)
            bm.faces.new(list(reversed(top)))
            for i in range(len(verts_2d)):
                ni = (i + 1) % len(verts_2d)
                bm.faces.new([bottom[i], bottom[ni], top[ni], top[i]])

        # Outer corners
        ox, oy = x, y
        ex, ey = x + width, y + depth
        # Hole corners
        ih_x0, ih_y0 = hx,      hy
        ih_x1, ih_y1 = hx + hw, hy + hd

        # Build 8 quads around the hole
        quads = [
            [(ox, oy),    (ih_x0, oy),   (ih_x0, ih_y0), (ox, ih_y0)],      # SW
            [(ih_x0, oy), (ih_x1, oy),   (ih_x1, ih_y0), (ih_x0, ih_y0)],   # S-mid
            [(ih_x1, oy), (ex, oy),      (ex, ih_y0),    (ih_x1, ih_y0)],    # SE
            [(ox, ih_y0), (ih_x0, ih_y0),(ih_x0, ih_y1), (ox, ih_y1)],       # W
            [(ih_x1, ih_y0),(ex, ih_y0), (ex, ih_y1),   (ih_x1, ih_y1)],     # E
            [(ox, ih_y1), (ih_x0, ih_y1),(ih_x0, ey),   (ox, ey)],           # NW
            [(ih_x0, ih_y1),(ih_x1, ih_y1),(ih_x1, ey), (ih_x0, ey)],        # N-mid
            [(ih_x1, ih_y1),(ex, ih_y1), (ex, ey),      (ih_x1, ey)],        # NE
        ]
        for quad in quads:
            add_face(quad)

        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.001)
        bm.to_mesh(mesh)
        bm.free()

    mat = create_material("concrete", (0.65, 0.65, 0.65, 1.0), roughness=0.9)
    _assign_material(obj, mat)
    obj.name = name
    return obj


# ── Segment-based wall construction ───────────────────────────────────────────

def _wall_segment(
    name: str,
    start: Vec2,
    direction: Tuple[float, float],
    length: float,
    bottom_z: float,
    top_z: float,
    thickness: float = WALL_THICKNESS,
) -> "bpy.types.Object":
    """
    Create one rectangular prism for a single wall segment.
    The segment runs from `start` in `direction` for `length` metres.
    """
    if length < 1e-4:
        return None
    angle = math.atan2(direction[1], direction[0])
    cx = start.x + direction[0] * length / 2
    cy = start.y + direction[1] * length / 2
    cz = (bottom_z + top_z) / 2
    height = top_z - bottom_z
    obj = create_box(name, cx, cy, cz, length, thickness, height, rotation_z=angle)
    return obj


def create_wall_with_openings(
    room_id: str,
    wall_index: int,
    wall_start: Vec2,
    wall_end:   Vec2,
    floor_z:    float,
    wall_top_z: float,
    openings:   List[Opening],
    thickness:  float = WALL_THICKNESS,
) -> List["bpy.types.Object"]:
    """
    KEY FUNCTION — Segment-based wall construction.

    Algorithm:
    1. Sort openings by position_frac.
    2. Walk along the wall, emitting solid segments in the gaps.
    3. For each opening:
       - Emit a LINTEL if opening top < wall top (creates header beam).
       - Emit a SILL   if opening bottom > 0     (creates window sill).
    4. The opening gap itself is left EMPTY — no geometry, no Boolean.
    """
    wall_len = wall_start.dist(wall_end)
    direction = wall_start.unit_toward(wall_end)
    objects: List["bpy.types.Object"] = []
    mat = create_material("wall_paint", (0.95, 0.94, 0.90, 1.0), roughness=0.85)

    def emit(seg_name, start_frac, end_frac, bz, tz):
        seg_len = (end_frac - start_frac) * wall_len
        if seg_len < 1e-4:
            return
        seg_start = Vec2(
            wall_start.x + direction[0] * start_frac * wall_len,
            wall_start.y + direction[1] * start_frac * wall_len,
        )
        obj = _wall_segment(seg_name, seg_start, direction, seg_len, bz, tz, thickness)
        if obj:
            _assign_material(obj, mat)
            objects.append(obj)

    openings_sorted = sorted(openings, key=lambda o: o.position_frac)
    seg_idx = 0
    cursor  = 0.0   # fraction along wall

    for op in openings_sorted:
        op_start_frac = op.position_frac - (op.width / wall_len) / 2
        op_end_frac   = op.position_frac + (op.width / wall_len) / 2
        op_start_frac = max(0.0, op_start_frac)
        op_end_frac   = min(1.0, op_end_frac)

        # Solid segment BEFORE this opening (full height)
        if op_start_frac > cursor + 1e-4:
            emit(
                f"{room_id}_w{wall_index}_seg{seg_idx}",
                cursor, op_start_frac,
                floor_z, wall_top_z,
            )
            seg_idx += 1

        opening_bottom_z = floor_z + op.bottom_z
        opening_top_z    = opening_bottom_z + op.height

        # SILL below window
        if op.bottom_z > 1e-4:
            emit(
                f"{room_id}_w{wall_index}_sill{seg_idx}",
                op_start_frac, op_end_frac,
                floor_z, opening_bottom_z,
            )
            seg_idx += 1

        # LINTEL above opening (if opening doesn't reach wall top)
        if opening_top_z < wall_top_z - 1e-4:
            emit(
                f"{room_id}_w{wall_index}_lintel{seg_idx}",
                op_start_frac, op_end_frac,
                opening_top_z, wall_top_z,
            )
            seg_idx += 1

        cursor = op_end_frac

    # Solid segment AFTER last opening
    if cursor < 1.0 - 1e-4:
        emit(
            f"{room_id}_w{wall_index}_seg{seg_idx}",
            cursor, 1.0,
            floor_z, wall_top_z,
        )

    return objects


# ── Room (4 walls) ───────────────────────────────────────────────────────────

def create_room(
    room_id:     str,
    floor_level: int,
    x: float, y: float,
    width: float, depth: float,
    wall_height: float,
    doorways:    List[dict],
    windows:     List[dict],
) -> List["bpy.types.Object"]:
    """
    Construct 4 walls for a room using create_wall_with_openings.

    Wall layout (Y-up):
        South wall  →  from (x,   y)      to (x+w, y)       — wall_side='south'
        North wall  →  from (x+w, y+d)    to (x,   y+d)     — wall_side='north'
        West wall   →  from (x,   y+d)    to (x,   y)       — wall_side='west'
        East wall   →  from (x+w, y)      to (x+w, y+d)     — wall_side='east'
    """
    floor_z    = floor_level * FLOOR_HEIGHT
    wall_top_z = floor_z + wall_height
    objects    = []

    # Build per-wall opening lists
    wall_openings: dict[str, List[Opening]] = {
        "south": [], "north": [], "west": [], "east": []
    }

    for dw in doorways:
        side = dw.get("wall_side", "south")
        frac = dw.get("position_along_wall", 0.5)
        wall_openings[side].append(
            Opening(position_frac=frac, width=dw.get("width", 0.9),
                    height=dw.get("height", 2.1), bottom_z=0.0)
        )

    for win in windows:
        side = win.get("wall_side", "south")
        frac = win.get("position_along_wall", 0.5)
        wall_openings[side].append(
            Opening(position_frac=frac, width=win.get("width", 1.0),
                    height=win.get("height", 1.2),
                    bottom_z=win.get("sill_height", 0.9))
        )

    walls = {
        "south": (Vec2(x, y),         Vec2(x + width, y)),
        "north": (Vec2(x + width, y + depth), Vec2(x, y + depth)),
        "west":  (Vec2(x, y + depth), Vec2(x, y)),
        "east":  (Vec2(x + width, y), Vec2(x + width, y + depth)),
    }

    for idx, (side, (ws, we)) in enumerate(walls.items()):
        objs = create_wall_with_openings(
            room_id, idx, ws, we, floor_z, wall_top_z,
            wall_openings.get(side, []),
        )
        objects.extend(objs)

    return objects


# ── Staircase ─────────────────────────────────────────────────────────────────

def create_staircase(
    stair_id:    str,
    from_floor:  int,
    to_floor:    int,
    x: float, y: float,
    direction:   str,
    stair_width: float = 1.0,
    rise:        float = STAIR_RISE,
    run_depth:   float = STAIR_RUN,
) -> List["bpy.types.Object"]:
    """
    Build a straight-run staircase from from_floor to to_floor.
    Each step is an individual box; handrail posts and rail are added on both sides.
    """
    objects  = []
    n_steps  = round((to_floor - from_floor) * FLOOR_HEIGHT / rise)
    base_z   = from_floor * FLOOR_HEIGHT

    dir_map  = {"north": (0, 1), "south": (0, -1), "east": (1, 0), "west": (-1, 0)}
    dx, dy   = dir_map.get(direction, (0, 1))

    mat_step = create_material("stair_wood", (0.55, 0.35, 0.15, 1.0), roughness=0.7)
    mat_rail = create_material("stair_rail", (0.3, 0.3, 0.3, 1.0), metallic=0.6, roughness=0.4)

    for i in range(n_steps):
        step_z  = base_z + i * rise + rise / 2
        cx      = x + dx * (i + 0.5) * run_depth
        cy      = y + dy * (i + 0.5) * run_depth
        step_sx = stair_width if dy != 0 else run_depth
        step_sy = run_depth   if dy != 0 else stair_width

        step = create_box(f"{stair_id}_step_{i}", cx, cy, step_z,
                          step_sx, step_sy, rise)
        _assign_material(step, mat_step)
        objects.append(step)

    # Handrail posts (every 4 steps) and rails
    rail_height = 0.9
    post_r      = 0.04
    n_posts     = max(2, n_steps // 4)
    for side in (-1, 1):
        perp_x = side * dy * (stair_width / 2 + 0.05)
        perp_y = side * (-dx) * (stair_width / 2 + 0.05)
        for p in range(n_posts + 1):
            frac = p / n_posts
            px   = x + dx * frac * n_steps * run_depth + perp_x
            py   = y + dy * frac * n_steps * run_depth + perp_y
            pz   = base_z + frac * n_steps * rise + rail_height / 2
            post = create_box(f"{stair_id}_post_{side}_{p}", px, py, pz,
                              post_r * 2, post_r * 2, rail_height)
            _assign_material(post, mat_rail)
            objects.append(post)

    return objects


# ── Stairwell hole in slab ────────────────────────────────────────────────────

def punch_stairwell_hole(
    floor_level: int,
    hole_x: float, hole_y: float,
    hole_w: float, hole_d: float,
) -> bool:
    """
    Punch a rectangular hole in the slab at `floor_level`.
    The slab must already exist (named 'slab_floor_{floor_level}').
    Uses bmesh face deletion on faces whose centre falls inside the hole.
    Returns True on success, False if the slab object was not found.
    """
    slab_name = f"slab_floor_{floor_level}"
    slab = bpy.data.objects.get(slab_name)
    if slab is None:
        return False

    bpy.context.view_layer.objects.active = slab
    bpy.ops.object.mode_set(mode="EDIT")
    bm = bmesh.from_edit_mesh(slab.data)
    bm.faces.ensure_lookup_table()

    to_delete = []
    for face in bm.faces:
        cx = sum(v.co.x for v in face.verts) / len(face.verts)
        cy = sum(v.co.y for v in face.verts) / len(face.verts)
        if hole_x <= cx <= hole_x + hole_w and hole_y <= cy <= hole_y + hole_d:
            to_delete.append(face)

    bmesh.ops.delete(bm, geom=to_delete, context="FACES")
    bmesh.update_edit_mesh(slab.data)
    bpy.ops.object.mode_set(mode="OBJECT")
    return True


# ── Roof ──────────────────────────────────────────────────────────────────────

def create_roof(
    x: float, y: float,
    width: float, depth: float,
    top_floor: int,
    roof_type: str = "flat",
    pitch_degrees: float = 20.0,
) -> "bpy.types.Object":
    """Create a flat, gabled, or hipped roof."""
    base_z   = (top_floor + 1) * FLOOR_HEIGHT
    mat_roof = create_material("roof_tile", (0.25, 0.15, 0.10, 1.0), roughness=0.9)

    if roof_type == "flat":
        obj = create_box("roof", x + width / 2, y + depth / 2,
                         base_z + 0.15, width, depth, 0.30)
        _assign_material(obj, mat_roof)
        return obj

    if roof_type in ("gabled", "hipped"):
        mesh = bpy.data.meshes.new("roof")
        obj  = bpy.data.objects.new("roof", mesh)
        bpy.context.collection.objects.link(obj)
        bm   = bmesh.new()

        pitch_h = (width / 2) * math.tan(math.radians(pitch_degrees))

        if roof_type == "gabled":
            verts = [
                bm.verts.new((x,            y,            base_z)),
                bm.verts.new((x + width,    y,            base_z)),
                bm.verts.new((x + width,    y + depth,    base_z)),
                bm.verts.new((x,            y + depth,    base_z)),
                bm.verts.new((x + width/2,  y,            base_z + pitch_h)),
                bm.verts.new((x + width/2,  y + depth,    base_z + pitch_h)),
            ]
            bm.faces.new([verts[0], verts[1], verts[4]])           # S triangle
            bm.faces.new([verts[2], verts[3], verts[5]])           # N triangle
            bm.faces.new([verts[1], verts[2], verts[5], verts[4]]) # E slope
            bm.faces.new([verts[3], verts[0], verts[4], verts[5]]) # W slope

        else:  # hipped
            apex = bm.verts.new((x + width/2, y + depth/2, base_z + pitch_h))
            corners = [
                bm.verts.new((x,         y,         base_z)),
                bm.verts.new((x + width, y,         base_z)),
                bm.verts.new((x + width, y + depth, base_z)),
                bm.verts.new((x,         y + depth, base_z)),
            ]
            for i in range(4):
                bm.faces.new([corners[i], corners[(i+1) % 4], apex])

        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        bm.to_mesh(mesh)
        bm.free()
        _assign_material(obj, mat_roof)
        return obj

    # Fallback
    return create_roof(x, y, width, depth, top_floor, "flat")


# ── Lighting + Camera ─────────────────────────────────────────────────────────

def setup_lighting_and_camera(
    building_width: float,
    building_depth: float,
    num_floors: int,
) -> None:
    """Add a sun lamp, fill area lamp, and isometric camera."""
    building_h = num_floors * FLOOR_HEIGHT
    cx, cy     = building_width / 2, building_depth / 2

    # Sun lamp
    bpy.ops.object.light_add(type="SUN", location=(cx + 10, cy - 10, building_h + 15))
    sun = bpy.context.object
    sun.data.energy = 3.0
    sun.rotation_euler = (math.radians(45), 0, math.radians(45))

    # Fill area lamp
    bpy.ops.object.light_add(type="AREA", location=(cx, cy, building_h + 20))
    fill = bpy.context.object
    fill.data.energy = 500.0
    fill.data.size   = max(building_width, building_depth) * 2

    # Camera — isometric view
    cam_dist = max(building_width, building_depth, building_h) * 2.5
    bpy.ops.object.camera_add(
        location=(cx + cam_dist * 0.7, cy - cam_dist * 0.7, building_h + cam_dist * 0.6)
    )
    cam = bpy.context.object
    cam.rotation_euler = (math.radians(55), 0, math.radians(45))
    bpy.context.scene.camera = cam


# ── Export ────────────────────────────────────────────────────────────────────

def export_gltf(output_path: str) -> None:
    """Export the entire scene as a GLTF file (with separate .bin)."""
    bpy.ops.export_scene.gltf(
        filepath=output_path,
        export_format="GLTF_SEPARATE",
        use_selection=False,
        export_apply=True,
    )


def save_blend(output_path: str) -> None:
    """Save the Blender scene as a .blend file."""
    bpy.ops.wm.save_as_mainfile(filepath=output_path)
