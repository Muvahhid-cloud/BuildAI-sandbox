"""Pure plan-geometry helpers shared by validation, the geometric checks (K2.5) and the layout
engine.

Tolerances (docs/building-model.md §4.1). `EPS` (0.1 mm, primitives.py) compares stored
coordinates: every stored length is rounded to 1 mm, so a real violation is at least 1 mm while
float noise stays far below EPS. Values *derived* from several rounded numbers (a roof underside
computed through tan(pitch), a sum of elevations) may be off by up to half a millimetre per
operand, hence DERIVED_TOLERANCE (1.5 mm). Polygon intersections smaller than
OVERLAP_AREA_TOLERANCE are contact, not overlap.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass

from app.modules.building.elements import Railing, Roof, Stair, Wall
from app.modules.building.enums import RoofType, WallAlignment
from app.modules.building.primitives import EPS, Rotation, Vec2, Vec3

Point = tuple[float, float]

DERIVED_TOLERANCE = 0.0015  # m
OVERLAP_AREA_TOLERANCE = 1e-3  # m²
ANGLE_TOLERANCE = 1e-5  # rad; stored angles are rounded to 1e-6 rad


def to_absolute(points: Sequence[Vec2], position: Vec3, rotation: Rotation) -> list[Point]:
    """Level-plan coordinates of an element-relative polygon (rotation.z about position)."""
    c, s = math.cos(rotation.z), math.sin(rotation.z)
    return [(position.x + p.x * c - p.y * s, position.y + p.x * s + p.y * c) for p in points]


def signed_area(points: Sequence[Point]) -> float:
    """Shoelace formula; positive for counter-clockwise polygons."""
    n = len(points)
    return 0.5 * sum(
        points[i][0] * points[(i + 1) % n][1] - points[(i + 1) % n][0] * points[i][1]
        for i in range(n)
    )


def perimeter(points: Sequence[Point]) -> float:
    n = len(points)
    return sum(math.dist(points[i], points[(i + 1) % n]) for i in range(n))


def is_rectilinear(points: Sequence[Point]) -> bool:
    n = len(points)
    for i in range(n):
        (x0, y0), (x1, y1) = points[i], points[(i + 1) % n]
        if abs(x0 - x1) > EPS and abs(y0 - y1) > EPS:
            return False
    return True


def is_axis_aligned_rectangle(points: Sequence[Point]) -> bool:
    return len(points) == 4 and is_rectilinear(points)


def wall_axis(wall: Wall) -> tuple[Point, Point]:
    """Start and end of a wall's axis in level-plan coordinates."""
    start = (wall.position.x, wall.position.y)
    angle = wall.rotation.z
    end = (
        start[0] + wall.dimensions.length * math.cos(angle),
        start[1] + wall.dimensions.length * math.sin(angle),
    )
    return start, end


def segment_overlap_length(a: tuple[Point, Point], b: tuple[Point, Point]) -> float:
    """Length of the collinear overlap of two segments (0 if not collinear)."""
    (ax0, ay0), (ax1, ay1) = a
    dx, dy = ax1 - ax0, ay1 - ay0
    length = math.hypot(dx, dy)
    if length < EPS:
        return 0.0
    ux, uy = dx / length, dy / length
    for px, py in b:  # both endpoints of b must lie on a's supporting line
        if abs((px - ax0) * uy - (py - ay0) * ux) > EPS:
            return 0.0
    t0 = (b[0][0] - ax0) * ux + (b[0][1] - ay0) * uy
    t1 = (b[1][0] - ax0) * ux + (b[1][1] - ay0) * uy
    lo, hi = max(0.0, min(t0, t1)), min(length, max(t0, t1))
    return max(0.0, hi - lo)


def polygon_edges(points: Sequence[Point]) -> list[tuple[Point, Point]]:
    n = len(points)
    return [(points[i], points[(i + 1) % n]) for i in range(n)]


def is_axis_aligned(angle: float) -> bool:
    """True if `angle` (radians) is a multiple of 90 degrees (rectilinear v1 geometry)."""
    quarter = math.pi / 2
    return abs(angle / quarter - round(angle / quarter)) * quarter < ANGLE_TOLERANCE


def is_untilted(rotation: Rotation) -> bool:
    """Only yaw (rotation.z) is used by walls, openings, stairs, slabs and roofs."""
    return abs(rotation.x) < ANGLE_TOLERANCE and abs(rotation.y) < ANGLE_TOLERANCE


# --- Walls ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class WallFrame:
    """Wall-local frame (docs/3d-engine.md §4): u along the axis from the start (0..length),
    v across it (+v = left face = +normal). [v0, v1] is the body's extent across the axis."""

    start: Point
    ux: float
    uy: float
    length: float
    v0: float
    v1: float

    def at(self, u: float, v: float = 0.0) -> Point:
        return (
            self.start[0] + u * self.ux - v * self.uy,
            self.start[1] + u * self.uy + v * self.ux,
        )

    def local(self, p: Point) -> tuple[float, float]:
        """(u, v) of a plan point."""
        dx, dy = p[0] - self.start[0], p[1] - self.start[1]
        return dx * self.ux + dy * self.uy, -dx * self.uy + dy * self.ux

    @property
    def axis(self) -> tuple[Point, Point]:
        return self.start, self.at(self.length)

    def footprint(self, u0: float = 0.0, u1: float | None = None) -> list[Point]:
        """CCW plan rectangle of the wall body between u0 and u1 (default: the whole axis;
        corner joins are not modelled)."""
        end = self.length if u1 is None else u1
        return [
            self.at(u0, self.v0),
            self.at(end, self.v0),
            self.at(end, self.v1),
            self.at(u0, self.v1),
        ]


def wall_frame(wall: Wall) -> WallFrame:
    t = wall.dimensions.thickness
    v0, v1 = {
        WallAlignment.CENTER: (-t / 2, t / 2),
        WallAlignment.LEFT: (0.0, t),
        WallAlignment.RIGHT: (-t, 0.0),
    }[wall.properties.alignment]
    return WallFrame(
        start=(wall.position.x, wall.position.y),
        ux=math.cos(wall.rotation.z),
        uy=math.sin(wall.rotation.z),
        length=wall.dimensions.length,
        v0=v0,
        v1=v1,
    )


# --- Stairs -----------------------------------------------------------------------------------


def stair_region(stair: Stair, x0: float = 0.0, x1: float | None = None) -> list[Point]:
    """CCW plan rectangle of a flight between local x0..x1 along its run (default: all of it).
    The flight runs along local +x from the first riser and spans local +y by its width."""
    end = stair.dimensions.run_length if x1 is None else x1
    w = stair.dimensions.width
    return to_absolute(
        [Vec2(x=x0, y=0), Vec2(x=end, y=0), Vec2(x=end, y=w), Vec2(x=x0, y=w)],
        stair.position,
        stair.rotation,
    )


def stair_point(stair: Stair, along: float) -> Point:
    """Plan point on the flight's centre line at local x = `along` (may lie beyond the flight)."""
    c, s = math.cos(stair.rotation.z), math.sin(stair.rotation.z)
    half = stair.dimensions.width / 2
    return (
        stair.position.x + along * c - half * s,
        stair.position.y + along * s + half * c,
    )


def stair_rises_above(stair: Stair, height: float) -> float | None:
    """Local x from which the flight's treads are higher than `height` above its base, or None
    if no tread is. Tread j (1-based) spans [(j-1)·T, j·T] at height j·R; the last riser, at
    x = run, rises to the arrival floor (docs/3d-engine.md §9)."""
    p = stair.properties
    j = math.floor((height + DERIVED_TOLERANCE) / p.riser_height) + 1
    if j > p.risers - 1:
        return None
    return (j - 1) * p.tread_depth


# --- Roofs ------------------------------------------------------------------------------------


def roof_underside(roof: Roof, p: Point) -> float:
    """Height of the roof's underside above its level at plan point `p` (docs/3d-engine.md §8):
    `position.z` is the top of the covering at the eaves, `thickness` is vertical, and pitched
    planes rise from the eaves (gable: the two eaves parallel to the ridge; hip: all four)."""
    base = roof.position.z - roof.dimensions.thickness
    if roof.properties.roof_type == RoofType.FLAT:
        return base
    pts = to_absolute(roof.properties.outline, roof.position, roof.rotation)
    x0, x1 = min(q[0] for q in pts), max(q[0] for q in pts)
    y0, y1 = min(q[1] for q in pts), max(q[1] for q in pts)
    to_x_eaves = min(p[1] - y0, y1 - p[1])  # distance to the eaves running along x
    to_y_eaves = min(p[0] - x0, x1 - p[0])
    if roof.properties.roof_type == RoofType.HIP:
        d = min(to_x_eaves, to_y_eaves)
    else:
        d = to_x_eaves if roof.properties.ridge_axis == "x" else to_y_eaves
    return base + math.tan(math.radians(roof.properties.pitch_deg)) * d


def shared_boundary_length(a: Sequence[Point], b: Sequence[Point]) -> float:
    """Total collinear overlap of the edges of two closed rings."""
    return sum(segment_overlap_length(ea, eb) for ea in polygon_edges(a) for eb in polygon_edges(b))


def railing_line(railing: Railing) -> tuple[Point, Point]:
    """Plan base line of a railing (it runs along local +x from `position`)."""
    c, s = math.cos(railing.rotation.z), math.sin(railing.rotation.z)
    start = (railing.position.x, railing.position.y)
    length = railing.dimensions.length
    return start, (start[0] + length * c, start[1] + length * s)
