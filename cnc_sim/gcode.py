"""Strict modal 3-axis NC parser. Unsupported motion is never silently ignored."""
from __future__ import annotations
from dataclasses import dataclass, field
import math
import re
import numpy as np


class NCError(ValueError):
    def __init__(self, line, message):
        super().__init__(f"NC line {line}: {message}")
        self.line = line


@dataclass
class Move:
    start: np.ndarray
    end: np.ndarray
    tool: int
    spindle: int
    rpm: float
    rapid: bool
    line: int
    t0: float
    t1: float
    kind: str = "line"


@dataclass
class Program:
    moves: list[Move]
    warnings: list[str] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)
    @property
    def duration(self):
        return self.moves[-1].t1 if self.moves else 0.


WORD = re.compile(r"([A-Za-z])\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))")


def strip_comments(line, lineno):
    chars, depth = [], 0
    for c in line:
        if c == ";" and depth == 0:
            break
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth < 0:
                raise NCError(lineno, "Unmatched comment parenthesis")
        elif depth == 0:
            chars.append(c)
    if depth:
        raise NCError(lineno, "Unclosed comment")
    return "".join(chars).strip()


def arc_points(start, end, words, clockwise, plane, absolute_center, scale, offset, tolerance, line):
    # These ordered axes are right-handed when viewed from the positive normal.
    u, v, w = {17: (0, 1, 2), 18: (2, 0, 1), 19: (1, 2, 0)}[plane]
    letters = "IJK"
    s, e = start[[u, v]], end[[u, v]]
    if "R" in words:
        if any(c in words for c in "IJK"):
            raise NCError(line, "Arc must use R or IJK, not both")
        radius = abs(words["R"]*scale)
        chord = e-s
        length = float(np.linalg.norm(chord))
        if length < 1e-10 or radius <= 0 or length > 2*radius+1e-8:
            raise NCError(line, "Impossible R arc; full circles need IJK")
        mid = (s+e)/2
        normal = np.array([-chord[1], chord[0]])/length
        distance = math.sqrt(max(0., radius*radius-length*length/4))
        direction = -1 if clockwise else 1
        if words["R"] < 0:
            direction *= -1
        center = mid+direction*distance*normal
    else:
        if not any(letters[d] in words for d in (u, v)):
            raise NCError(line, "Arc has no center")
        if letters[w] in words:
            raise NCError(line, "Arc contains a center word outside the active plane")
        center = s.copy()
        for index, axis in enumerate((u, v)):
            letter = letters[axis]
            if absolute_center:
                if letter not in words:
                    raise NCError(line, "G90.1 requires both in-plane center coordinates")
                center[index] = words[letter]*scale+offset[axis]
            else:
                center[index] += words.get(letter, 0.)*scale
        radius = float(np.linalg.norm(s-center))
        if radius <= 1e-10:
            raise NCError(line, "Arc radius is zero")
    end_radius = float(np.linalg.norm(e-center))
    # Do not repair an invalid arc into a different toolpath.
    if abs(radius-end_radius) > max(1e-7, tolerance):
        raise NCError(line, f"Arc radii disagree by {abs(radius-end_radius):.6g} mm (tolerance {tolerance:g})")
    a0 = math.atan2(s[1]-center[1], s[0]-center[0])
    a1 = math.atan2(e[1]-center[1], e[0]-center[0])
    sweep = (a1-a0) % (2*math.pi)
    if clockwise:
        sweep = -((a0-a1) % (2*math.pi))
    if abs(sweep) < 1e-10:
        sweep = -2*math.pi if clockwise else 2*math.pi
    angle_step = 2*math.acos(max(-1., 1-tolerance/max(radius, end_radius)))
    count = max(1, int(math.ceil(abs(sweep)/max(1e-6, angle_step))))
    if count > 2_000_000:
        raise NCError(line, "Arc would create more than two million segments")
    points = []
    for i in range(1, count+1):
        f = i/count
        p = start+(end-start)*f
        # Tiny accepted rounding discrepancies are interpolated, not jumped at
        # the endpoint. They remain bounded by the configured arc tolerance.
        r = radius+(end_radius-radius)*f
        p[u] = center[0]+r*math.cos(a0+sweep*f)
        p[v] = center[1]+r*math.sin(a0+sweep*f)
        points.append(p)
    points[-1] = end.copy()
    return points


class Parser:
    def __init__(self, start=(0, 0, 5), initial_tool=1, rapid_feed=2400., arc_tolerance=0.005,
                 work_offsets=None, machine_origin=None, clearance_moves=None,
                 tool_change_moves=None, block_delete=False):
        self.start = np.asarray(start, dtype=float)
        if self.start.shape != (3,) or not np.isfinite(self.start).all():
            raise ValueError("Initial tip position needs three finite coordinates")
        if not math.isfinite(rapid_feed) or rapid_feed <= 0 or not math.isfinite(arc_tolerance) or arc_tolerance <= 0:
            raise ValueError("Rapid feed and arc tolerance must be positive and finite")
        self.initial_tool = int(initial_tool)
        self.rapid_feed = rapid_feed
        self.arc_tolerance = arc_tolerance
        self.offsets = {54: np.zeros(3)}
        for code, value in (work_offsets or {}).items():
            code = int(str(code).upper().removeprefix("G"))
            a = np.asarray(value, dtype=float)
            if code not in range(54, 60) or a.shape != (3,) or not np.isfinite(a).all():
                raise ValueError("Work offsets must map G54..G59 to three finite coordinates")
            self.offsets[code] = a
        self.machine_origin = None if machine_origin is None else np.asarray(machine_origin, dtype=float)
        if self.machine_origin is not None and (self.machine_origin.shape != (3,) or not np.isfinite(self.machine_origin).all()):
            raise ValueError("machine_origin needs three finite coordinates")
        self.clearance_moves = clearance_moves
        self.tool_change_moves = tool_change_moves
        self.block_delete = block_delete

    def parse(self, text):
        moves, warnings, events = [], [], []
        pos = self.start.copy()
        tool = selected = self.initial_tool
        spindle, rpm, feed, scale, clock = 0, 0., None, 1., 0.
        absolute, absolute_center, plane, wcs = True, False, 17, 54
        temp, saved_temp = np.zeros(3), np.zeros(3)
        offsets = {k:v.copy() for k,v in self.offsets.items()}
        mode, inverse_time, retract_initial = 0, False, True
        cycle, cycle_params, cycle_initial = None, {}, None
        tlo_cancelled = False

        def emit(end, rapid, line, duration=None, kind="line", local_feed=None):
            nonlocal pos, clock
            if tlo_cancelled:
                raise NCError(line, "Motion/dwell after G49 has unknown tool-tip compensation; M6 must establish the next tool first")
            end = np.asarray(end, dtype=float)
            distance = float(np.linalg.norm(end-pos))
            if duration is None:
                rate = (local_feed or self.rapid_feed) if rapid else feed
                if rate is None or rate <= 0:
                    raise NCError(line, "Feed motion before a positive F word")
                duration = 60*distance/rate
            moves.append(Move(pos.copy(), end.copy(), tool, spindle, rpm, rapid, line, clock, clock+duration, kind))
            clock += duration
            pos = end.copy()

        for lineno, original in enumerate(text.splitlines(), 1):
            line = strip_comments(original, lineno)
            if not line or line == "%":
                continue
            if line.startswith("/"):
                if self.block_delete:
                    continue
                line = line[1:].lstrip()
            matches = list(WORD.finditer(line))
            remainder = WORD.sub("", line)
            if remainder.strip():
                raise NCError(lineno, f"Unsupported syntax {remainder.strip()!r} (macros/subprograms are not expanded)")
            words, gs, ms = {}, [], []
            for match in matches:
                letter, number = match.group(1).upper(), float(match.group(2))
                if not math.isfinite(number):
                    raise NCError(lineno, "Non-finite number")
                if letter == "G": gs.append(number)
                elif letter == "M": ms.append(number)
                elif letter == "N": continue
                elif letter in words: raise NCError(lineno, f"Duplicate {letter} word")
                else: words[letter] = number
            if any(c in words for c in "ABCUVW"):
                raise NCError(lineno, "Rotary/auxiliary axes are outside this 3-axis simulator")
            if "O" in words:
                if len(words) == 1 and not gs and not ms:
                    continue
                raise NCError(lineno, "Subprograms are unsupported")
            unknown_words = set(words)-set("XYZIJKRFSTHPQLD")
            if unknown_words:
                raise NCError(lineno, f"Unsupported words: {sorted(unknown_words)}")
            # Reject conflicting modal commands rather than selecting the last.
            groups = [(0, 1, 2, 3, 80, 81, 82, 83), (17, 18, 19), (20, 21), (90, 91),
                      (90.1, 91.1), (93, 94), (54, 55, 56, 57, 58, 59), (98, 99)]
            for group in groups:
                if sum(g in group for g in gs) > 1:
                    raise NCError(lineno, "Conflicting commands in a modal group")
            allowed_g = {0,1,2,3,4,10,17,18,19,20,21,28,40,49,53,54,55,56,57,58,59,
                         61,64,80,81,82,83,90,91,90.1,91.1,92,92.1,92.2,92.3,93,94,98,99}
            for g in gs:
                if g not in allowed_g:
                    raise NCError(lineno, f"Unsupported G{g:g}; refusing an unverified path")
            for m in ms:
                if m not in {0,1,2,3,4,5,6,7,8,9,30,400}:
                    raise NCError(lineno, f"Unsupported M{m:g}; machine-specific motion/state needs explicit support")
            if sum(m in (3,4,5) for m in ms) > 1:
                raise NCError(lineno, "Conflicting spindle commands")
            if 20 in gs:
                scale = 25.4
                warnings.append(f"Line {lineno}: G20 converted to mm; controller-specific inch-mode behavior is not modeled")
            if 21 in gs: scale = 1.
            if 90 in gs: absolute = True
            if 91 in gs: absolute = False
            if 90.1 in gs: absolute_center = True
            if 91.1 in gs: absolute_center = False
            if 93 in gs and not inverse_time: inverse_time,feed = True,None
            if 94 in gs and inverse_time: inverse_time,feed = False,None
            if 98 in gs: retract_initial = True
            if 99 in gs: retract_initial = False
            if 49 in gs: tlo_cancelled = True
            for g in gs:
                if g in (17,18,19): plane = int(g)
                if g in range(54,60):
                    if int(g) not in offsets:
                        raise NCError(lineno, f"G{g:g} offset is undefined")
                    wcs = int(g)
            offset = offsets[wcs]+temp
            if "T" in words:
                if words["T"] != int(words["T"]) or words["T"] <= 0:
                    raise NCError(lineno, "Only positive integer milling tool numbers are supported")
                selected = int(words["T"])
            if 6 in ms:
                if set(words)-{"T"} or any(g in gs for g in (0,1,2,3)):
                    raise NCError(lineno, "Use a standalone Tn M6 block; M6 options are not inferred")
                spindle, rpm = 0, 0.
                events.append({"line": lineno, "time_s": clock, "kind": "tool_change", "tool": selected})
                # Optional explicit macro return position. Hidden ATC/probe motion
                # is outside the NC machining-path verification scope.
                tool = selected
                tlo_cancelled = False
                if self.tool_change_moves:
                    for waypoint in self.tool_change_moves:
                        p = pos.copy()
                        for d, c in enumerate("XYZ"):
                            if c.lower() in waypoint: p[d] = float(waypoint[c.lower()])
                        emit(p, True, lineno, kind="tool_change_return")
                else:
                    warnings.append(f"Line {lineno}: M6 service motion excluded; assumes return to the same programmed tip position")
                continue
            if "S" in words and 4 not in gs:
                rpm = words["S"]
                if rpm < 0: raise NCError(lineno, "Negative spindle speed")
            if 3 in ms: spindle = 1
            if 4 in ms: spindle = -1
            if 5 in ms: spindle = 0
            if any(g in gs for g in (10,92,92.1,92.2,92.3)):
                if len(gs) != 1 or ms:
                    raise NCError(lineno, "Coordinate-setting commands require a separate block")
                if 10 in gs:
                    if words.get("L") != 2 or words.get("P",0) != int(words.get("P",0)) or int(words.get("P",0)) not in range(1,7):
                        raise NCError(lineno, "Only G10 L2 P1..6 is supported")
                    code = 53+int(words["P"])
                    if self.machine_origin is None:
                        raise NCError(lineno, "G10 L2 requires machine_origin to map machine coordinates into the stock frame")
                    if code not in offsets and not all(c in words for c in "XYZ"):
                        raise NCError(lineno, "A new G10 work offset needs all XYZ coordinates or a preconfigured offset")
                    value = offsets.get(code, np.zeros(3)).copy()
                    for d,c in enumerate("XYZ"):
                        if c in words: value[d] = words[c]*scale+self.machine_origin[d]
                    offsets[code] = value
                elif 92 in gs:
                    for d,c in enumerate("XYZ"):
                        if c in words: temp[d] = pos[d]-offsets[wcs][d]-words[c]*scale
                    saved_temp = temp.copy()
                elif 92.1 in gs: temp[:], saved_temp[:] = 0., 0.
                elif 92.2 in gs: saved_temp, temp = temp.copy(), np.zeros(3)
                else: temp = saved_temp.copy()
                continue
            if 28 in gs:
                if words or len(gs) != 1 or ms:
                    raise NCError(lineno, "G28 accepts only a standalone configured waypoint sequence; intermediate or axis behavior is not inferred")
                if not self.clearance_moves:
                    raise NCError(lineno, "G28 needs explicit clearance_moves in --machine; controller-specific homing or clearance behavior is not inferred")
                for waypoint in self.clearance_moves:
                    p = pos.copy()
                    for d,c in enumerate("xyz"):
                        if c in waypoint: p[d] = float(waypoint[c])
                    emit(p, True, lineno, kind="clearance")
                continue
            if 4 in gs:
                if set(words)-{"P","S"} or len(gs) != 1:
                    raise NCError(lineno, "G4 accepts P seconds only (or S seconds)")
                duration = words.get("P", words.get("S", 0.))
                if duration < 0: raise NCError(lineno, "Negative dwell")
                emit(pos, False, lineno, duration=duration, kind="dwell")
                continue
            for g in gs:
                if g in (0,1,2,3): mode, cycle = int(g), None
                if g == 80: cycle = None
                if g in (81,82,83):
                    cycle = int(g)
                    cycle_initial = pos[2]
                    cycle_params = {}
            rapid_f = None
            if "F" in words:
                if words["F"] <= 0: raise NCError(lineno, "F must be positive")
                if mode == 0 and cycle is None and not inverse_time and any(c in words for c in "XYZ"):
                    rapid_f = words["F"]*scale  # Community G0 F is block-local.
                else:
                    feed = words["F"] if inverse_time else words["F"]*scale
            if cycle and (any(c in words for c in "XYZR") or any(g in gs for g in (81,82,83))):
                if plane != 17 or inverse_time:
                    raise NCError(lineno, "Drilling cycles require G17 and G94")
                for c in "RZQP":
                    if c in words: cycle_params[c] = words[c]
                if not {"R","Z"}.issubset(cycle_params):
                    raise NCError(lineno, "Cycle needs R and Z")
                repeats = int(words.get("L",1))
                if repeats < 1 or repeats != words.get("L",1) or repeats > 100000:
                    raise NCError(lineno, "Invalid drilling cycle repeat count")
                for _ in range(repeats):
                    r = cycle_params["R"]*scale+(offset[2] if absolute else cycle_initial)
                    z = cycle_params["Z"]*scale+(offset[2] if absolute else r)
                    if z >= r: raise NCError(lineno, "Cycle bottom must lie below R")
                    if pos[2] < r:
                        p=pos.copy();p[2]=r;emit(p,True,lineno)
                    p=pos.copy()
                    for d,c in enumerate("XY"):
                        if c in words:p[d]=words[c]*scale+(offset[d] if absolute else pos[d])
                    emit(p,True,lineno)
                    p=pos.copy();p[2]=r;emit(p,True,lineno)
                    if cycle == 83:
                        q = cycle_params.get("Q",0)*scale
                        if q <= 0: raise NCError(lineno,"G83 needs positive Q")
                        if (r-z)/q > 100000: raise NCError(lineno,"Too many pecks")
                        depth=r
                        while depth > z+1e-10:
                            depth=max(z,depth-q)
                            p=pos.copy();p[2]=depth;emit(p,False,lineno)
                            p=pos.copy();p[2]=r;emit(p,True,lineno)
                            if depth>z+1e-10:
                                # Return at feed to avoid an unverified firmware-specific rapid clearance.
                                p=pos.copy();p[2]=depth;emit(p,False,lineno)
                    else:
                        p=pos.copy();p[2]=z;emit(p,False,lineno)
                        if cycle==82:
                            dwell=cycle_params.get("P",0)
                            if dwell<0:raise NCError(lineno,"Negative cycle dwell")
                            emit(pos,False,lineno,duration=dwell,kind="dwell")
                    p=pos.copy();p[2]=max(r,cycle_initial) if retract_initial else r
                    emit(p,True,lineno)
            else:
                has_motion = any(c in words for c in "XYZ") or (mode in (2,3) and any(c in words for c in "IJKR"))
                if 80 in gs and has_motion:
                    raise NCError(lineno,"Axis words in G80 cancellation block")
                if has_motion:
                    target=pos.copy()
                    if 53 in gs:
                        if not absolute or self.machine_origin is None or mode not in (0,1):
                            raise NCError(lineno,"G53 requires G90, G0/G1 and configured machine_origin")
                        effective_offset=self.machine_origin
                    else:effective_offset=offset
                    for d,c in enumerate("XYZ"):
                        if c in words:target[d]=words[c]*scale+(effective_offset[d] if absolute else pos[d])
                    if any(c in words for c in "HLDQP"):
                        raise NCError(lineno,"Unexpected offset/cycle parameter on motion")
                    if inverse_time and mode!=0 and "F" not in words:
                        raise NCError(lineno,"G93 needs F on every feed block")
                    if mode in (2,3):
                        points=arc_points(pos,target,words,mode==2,plane,absolute_center,scale,effective_offset,self.arc_tolerance,lineno)
                        lengths=np.linalg.norm(np.diff(np.vstack([pos,*points]),axis=0),axis=1)
                        total=float(lengths.sum())
                        for point,length in zip(points,lengths):
                            duration=(60/feed*length/total) if inverse_time else None
                            emit(point,False,lineno,duration=duration,kind="arc")
                    else:
                        if any(c in words for c in "IJKR"):
                            raise NCError(lineno,"Arc words on a linear move")
                        duration=60/feed if inverse_time and mode!=0 else None
                        emit(target,mode==0,lineno,duration=duration,local_feed=rapid_f)
                elif any(c in words for c in "IJKRHLDQP"):
                    raise NCError(lineno,"Unconsumed geometric/cycle words")
            if 64 in gs:
                warnings.append(f"Line {lineno}: nominal NC path simulated; controller corner blending is not modeled")
            for m in ms:
                if m in (0,1):events.append({"line":lineno,"time_s":clock,"kind":"pause","optional":m==1})
            if 2 in ms or 30 in ms:
                events.append({"line":lineno,"time_s":clock,"kind":"end"})
                break
        if not moves:
            raise NCError(0,"No motion or dwell commands")
        return Program(moves,list(dict.fromkeys(warnings)),events)
