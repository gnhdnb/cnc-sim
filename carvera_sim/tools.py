"""Axisymmetric rotating cutter envelopes; every profile is a union of frusta.

Rows are (x_offset, y_offset, z_bottom, z_top, bottom_radius, top_radius).
All dimensions are millimetres, measured upwards from the programmed tool tip.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
from pathlib import Path
import re
import numpy as np

EMPTY_FRUSTA = np.empty((0, 6), dtype=np.float64)
EMPTY_BOXES = np.empty((0, 6), dtype=np.float64)


@dataclass
class Body:
    name: str
    frusta: np.ndarray = field(default_factory=lambda: EMPTY_FRUSTA.copy())
    boxes: np.ndarray = field(default_factory=lambda: EMPTY_BOXES.copy())
    role: str = "shank"


@dataclass
class Tool:
    number: int
    name: str
    kind: str
    cutting: np.ndarray
    bodies: list[Body]
    stickout: float
    verified: bool
    spec: dict


def finite(value, name, positive=False):
    x = float(value)
    if not math.isfinite(x) or (positive and x <= 0):
        raise ValueError(f"{name} must be {'positive and ' if positive else ''}finite")
    return x


def profile_frusta(points, offset=(0, 0, 0)):
    p = np.asarray(points, dtype=np.float64)
    if p.ndim != 2 or p.shape[1] != 2 or len(p) < 2:
        raise ValueError("A profile requires at least two [height, radius] points")
    if not np.isfinite(p).all() or (p[:, 1] < 0).any() or (np.diff(p[:, 0]) < 0).any():
        raise ValueError("Profile heights must be ordered; radii nonnegative; values finite")
    rows = [[offset[0], offset[1], a[0]+offset[2], b[0]+offset[2], a[1], b[1]]
            for a, b in zip(p[:-1], p[1:]) if b[0] > a[0] and max(a[1], b[1]) > 0]
    if not rows:
        raise ValueError("Profile has no positive-volume segments")
    return np.asarray(rows, dtype=np.float64)


def arc_profile(radius, tolerance, theta_end=math.pi/2, radial_offset=0):
    # Chords lie inside the circular profile; maximum normal error <= tolerance.
    angle = 2 * math.acos(max(-1., 1 - tolerance / radius))
    count = max(2, int(math.ceil(theta_end / max(angle, 1e-5))))
    return [(radius*(1-math.cos(t)), radial_offset+radius*math.sin(t))
            for t in np.linspace(0, theta_end, count+1)]


ALIASES = {
    "flat": "flat", "flatend": "flat", "flatendmill": "flat", "endmill": "flat",
    "corn": "flat", "cornbit": "flat", "oflute": "flat", "spiralo": "flat",
    "ball": "ball", "ballend": "ball", "ballendmill": "ball", "ballnose": "ball",
    "bull": "bull", "bullnose": "bull", "bullend": "bull", "radiusend": "bull",
    "bullnoseendmill": "bull", "cornerradius": "bull",
    "v": "v", "vbit": "v", "engraving": "v", "engravingbit": "v",
    "engraver": "v", "chamfer": "v", "chamfermill": "v", "chamfering": "v",
    "uvsoldermask": "v", "drill": "drill", "drillbit": "drill",
    "taperedflat": "tapered_flat", "taperedend": "tapered_flat", "taperedendmill": "tapered_flat",
    "taperedball": "tapered_ball", "taperedballnose": "tapered_ball",
    "thread": "thread", "threadmill": "thread", "threadmilling": "thread",
    "threadmillingbit": "thread", "lollipop": "lollipop", "dovetail": "dovetail",
    "tslot": "t_slot", "keyhole": "t_slot", "profile": "profile", "custom": "profile",
    "face": "flat", "facemill": "flat", "form": "profile", "formmill": "profile",
    "radius": "profile", "radiusmill": "profile", "cornerround": "profile",
    "circlesegmentbarrel": "profile", "circlesegmentlens": "profile",
    "circlesegmentoval": "profile", "circlesegmenttaper": "profile",
    "lollipopmill": "lollipop", "dovetailmill": "dovetail", "slot": "t_slot", "slotmill": "t_slot",
    "tapered": "tapered_flat", "taperedmill": "tapered_flat",
}


def normalize_kind(value):
    key = re.sub(r"[^a-z0-9]", "", str(value).lower())
    if key not in ALIASES:
        raise ValueError(f"Unsupported cutter type {value!r}; supply an explicit 'profile' tool")
    return ALIASES[key]


def make_tool(number, spec, tolerance=0.005):
    from .catalog import resolve_tool_spec
    spec = resolve_tool_spec(spec)
    permitted = {"name","type","diameter","flute_length","shoulder_length","shank_diameter",
                 "stickout","shoulder_diameter","corner_radius","angle","tip_diameter","tip_radius",
                 "half_angle","neck_diameter","thread_angle","tooth_height","teeth","pitch",
                 "tooth_start","profile","noncut_profile","bodies","verified","handedness",
                 "catalog_id","source_note","source","notes"}
    if set(spec)-permitted:
        raise ValueError(f"Unknown tool fields: {sorted(set(spec)-permitted)}")
    if "verified" in spec and not isinstance(spec["verified"], bool):
        raise ValueError("Tool verified must be a JSON boolean, not a string")
    if "type" not in spec or "flute_length" not in spec:
        raise ValueError("Every tool requires type and flute_length")
    kind = normalize_kind(spec.get("type", "flat"))
    if kind not in ("profile", "tapered_ball") and "diameter" not in spec:
        raise ValueError("This tool requires diameter")
    tolerance = finite(tolerance, "profile tolerance", True)
    L = finite(spec.get("flute_length", 10), "flute_length", True)
    R = finite(spec.get("diameter", 3.175), "diameter", True)/2
    stickout = finite(spec.get("stickout", max(L+10, 25.5)), "stickout", True)
    shank_radius = finite(spec.get("shank_diameter", 3.175), "shank_diameter", True)/2
    if spec.get("handedness", "right") not in ("left", "right"):
        raise ValueError("handedness must be left or right")
    shoulder = finite(spec.get("shoulder_length", L), "shoulder_length", True)
    if shoulder < L or stickout < shoulder:
        raise ValueError(f"T{number}: require flute_length <= shoulder_length <= stickout")
    points = []
    if kind == "flat":
        points = [(0, R), (L, R)]
    elif kind in ("ball", "bull", "lollipop"):
        c = R if kind != "bull" else finite(spec["corner_radius"], "corner_radius", True)
        if c > R:
            raise ValueError("corner_radius exceeds tool radius")
        top_angle = math.pi if kind == "lollipop" else math.pi/2
        points = arc_profile(c, tolerance, top_angle, R-c)
        if L < points[-1][0] - 1e-9:
            raise ValueError("flute_length is shorter than the rounded tip")
        if L > points[-1][0] and kind != "lollipop":
            points.append((L, R))
        elif kind == "lollipop" and abs(L-2*R) > 1e-9:
            raise ValueError("lollipop flute_length must equal diameter")
    elif kind in ("v", "drill", "tapered_flat", "dovetail"):
        if kind in ("v", "drill", "tapered_flat") and "angle" not in spec:
            raise ValueError("V, drill and tapered-flat cutters require an explicit included angle")
        angle = finite(spec.get("angle", 118 if kind == "drill" else 60), "included angle", True)
        if not 0 < angle < 180:
            raise ValueError("Included angle must be between 0 and 180 degrees")
        tip = finite(spec.get("tip_diameter", 0), "tip_diameter")/2
        if not 0 <= tip <= R:
            raise ValueError("tip_diameter must be between zero and diameter")
        if kind == "dovetail":
            neck = finite(spec["neck_diameter"], "neck_diameter", True)/2
            if neck > R:
                raise ValueError("neck diameter exceeds dovetail diameter")
            points = [(0, R), (L, neck)]
        else:
            slope = math.tan(math.radians(angle/2))
            h = (R-tip)/slope
            points = [(0, tip), (min(h, L), min(R, tip+L*slope))]
            if h < L:
                points.append((L, R))
    elif kind == "tapered_ball":
        tip = finite(spec["tip_radius"], "tip_radius", True)
        alpha = math.radians(finite(spec["half_angle"], "half_angle", True))
        if not 0 < alpha < math.pi/2:
            raise ValueError("half_angle must be between 0 and 90")
        points = arc_profile(tip, tolerance, math.pi/2-alpha)
        h, r = points[-1]
        if L <= h:
            raise ValueError("flute_length must exceed the spherical tip height")
        points.append((L, r+(L-h)*math.tan(alpha)))
    elif kind == "thread":
        neck = finite(spec["neck_diameter"], "neck_diameter", True)/2
        if neck >= R:
            raise ValueError("thread neck diameter must be smaller than cutting diameter")
        angle = finite(spec.get("thread_angle", 60), "thread_angle", True)
        if angle >= 180:
            raise ValueError("thread_angle must be less than 180")
        height = finite(spec.get("tooth_height", 2*(R-neck)*math.tan(math.radians(angle/2))), "tooth_height", True)
        count = int(spec.get("teeth", 1))
        if count < 1 or count != spec.get("teeth", 1):
            raise ValueError("teeth must be a positive integer")
        pitch = finite(spec.get("pitch", height), "pitch", True)
        start = finite(spec.get("tooth_start", 0), "tooth_start")
        if pitch < height-1e-9 or start < 0 or start+(count-1)*pitch+height > L+1e-9:
            raise ValueError("Thread teeth must fit inside flute_length without overlap")
        rows = []
        for i in range(count):
            z = start+i*pitch
            rows.extend(profile_frusta([(z, neck), (z+height/2, R), (z+height, neck)]))
        cutting = np.asarray(rows, dtype=np.float64)
    elif kind == "t_slot":
        points = [(0, R), (L, R)]
    elif kind == "profile":
        points = spec["profile"]
        if float(points[0][0]) < 0 or abs(float(points[-1][0])-L) > 1e-8:
            raise ValueError("Custom cutting profile must lie in [0, flute_length] and end at flute_length")
    if kind != "thread":
        cutting = profile_frusta(points)
    bodies = []
    if "noncut_profile" in spec:
        bodies.append(Body("shank", profile_frusta(spec["noncut_profile"])))
    else:
        neck_radius = finite(spec.get("neck_diameter", spec.get("shoulder_diameter", 2*cutting[-1, 5])), "neck diameter", True)/2
        z0 = 0 if kind == "thread" else L
        if shoulder > z0:
            bodies.append(Body("neck", profile_frusta([(z0, neck_radius), (shoulder, neck_radius)])))
        if stickout > shoulder:
            bodies.append(Body("shank", profile_frusta([(shoulder, shank_radius), (stickout, shank_radius)])))
    for extra in spec.get("bodies", []):
        bodies.append(make_body(extra, stickout))
    # An omitted stickout is usable for material removal, never a verified assembly.
    verified = (bool(spec.get("verified", False)) and "stickout" in spec and
                ("shank_diameter" in spec or "noncut_profile" in spec))
    return Tool(int(number), str(spec.get("name", f"T{number} {kind}")), kind, cutting, bodies, stickout, verified, spec)


def make_body(spec, stickout=0):
    permitted = {"name","role","shape","anchor","offset","z","radius","radius_bottom",
                 "radius_top","profile","min","max","notes","source"}
    if set(spec)-permitted:
        raise ValueError(f"Unknown body fields: {sorted(set(spec)-permitted)}")
    anchor = spec.get("anchor", "gauge")
    if anchor not in ("gauge", "tip"):
        raise ValueError("Body anchor must be 'gauge' or 'tip'")
    offset = np.asarray(spec.get("offset", [0, 0, 0]), dtype=float)
    if offset.shape != (3,) or not np.isfinite(offset).all():
        raise ValueError("Body offset requires three finite values")
    offset[2] += stickout if anchor == "gauge" else 0
    name = str(spec["name"])
    role = str(spec.get("role", name))
    if spec["shape"] in ("cylinder", "frustum"):
        z0, z1 = map(float, spec["z"])
        r0 = float(spec.get("radius", spec.get("radius_bottom", -1)))
        r1 = float(spec.get("radius", spec.get("radius_top", -1)))
        if z1 <= z0:
            raise ValueError("Body top must be above its bottom")
        return Body(name, profile_frusta([(z0, r0), (z1, r1)], offset), role=role)
    if spec["shape"] == "profile":
        return Body(name, profile_frusta(spec["profile"], offset), role=role)
    if spec["shape"] == "box":
        bounds = np.asarray([*spec["min"], *spec["max"]], dtype=float)
        if bounds.shape != (6,) or not np.isfinite(bounds).all() or np.any(bounds[3:] <= bounds[:3]):
            raise ValueError("Invalid box bounds")
        bounds[:3] += offset
        bounds[3:] += offset
        return Body(name, boxes=bounds.reshape(1, 6), role=role)
    raise ValueError(f"Unsupported body shape: {spec['shape']}")


def load_tools(path, tolerance=0.005):
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    specs = data.get("tools", data)
    if not isinstance(specs, dict):
        raise ValueError("Tool file must contain a tools object keyed by NC tool number")
    return {int(n): make_tool(int(n), spec, tolerance) for n, spec in specs.items()}


def embedded_tools(text, tolerance=0.005, skip=()):
    """Read documented-by-export ;@MKR|TOOL|... records. No diameter guessing."""
    result, warnings = {}, []
    for line in text.splitlines():
        if not line.lstrip().startswith(";@MKR|TOOL|"):
            continue
        fields = dict(x.split("=", 1) for x in line.split("|")[2:] if "=" in x)
        n = int(fields["number"])
        if n in skip:
            continue
        kind = normalize_kind(fields["type"])
        spec = {"name": fields.get("name", f"T{n}"), "type": kind,
                "diameter": float(fields["diameter"]),
                "flute_length": float(fields["flutelength"]),
                "shank_diameter": float(fields["handlediameter"]),
                "shoulder_length": max(float(fields["shoulderlength"]), float(fields["flutelength"])),
                "tip_diameter": float(fields.get("tipdiameter", 0)),
                "verified": False}
        stick = float(fields.get("sticklength", 0))
        if stick > 0:
            spec["stickout"] = stick
        if kind in ("v", "drill", "tapered_flat"):
            spec["angle"] = float(fields.get("angle", 0)) or 2*float(fields.get("halfAngle", 0))
            if not spec["angle"]:
                raise ValueError(f"T{n}: NC metadata lacks a usable tip angle; provide --tools")
        if kind == "bull":
            spec["corner_radius"] = float(fields["cornerradius"])
        if kind in ("thread", "tapered_ball", "profile", "dovetail"):
            raise ValueError(f"T{n}: {kind} metadata does not fully define the profile; provide --tools")
        result[n] = make_tool(n, spec, tolerance)
        warnings.append(f"T{n} read from NC metadata; verify stickout and shoulder geometry with --tools")
    return result, warnings
