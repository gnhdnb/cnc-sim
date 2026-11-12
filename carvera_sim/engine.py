from __future__ import annotations
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import time
import zlib
import numpy as np

from . import __version__
from .gcode import Program, Move
from .tools import Body, Tool, make_body, EMPTY_FRUSTA
from .kernels import (remove_sweep, collide_frusta, collide_boxes,
                      frustum_fixture_hit, box_fixture_hit)


@dataclass
class Stock:
    dimensions: np.ndarray
    origin: np.ndarray
    pitch: float = 0.1

    def __post_init__(self):
        self.dimensions = np.asarray(self.dimensions, dtype=float)
        self.origin = np.asarray(self.origin, dtype=float)
        if (self.dimensions.shape != (3,) or self.origin.shape != (3,) or
            not np.isfinite(self.dimensions).all() or not np.isfinite(self.origin).all() or
            np.any(self.dimensions <= 0) or not math.isfinite(self.pitch) or self.pitch <= 0):
            raise ValueError("Stock dimensions and pitch must be positive finite values; origin must be finite")

    @property
    def shape(self):
        return tuple(int(math.ceil(x/self.pitch-1e-10)) for x in self.dimensions)

    @property
    def nbytes(self):
        return math.prod(self.shape)

    def initialize(self, grid):
        grid[:] = True
        # Cell-centre occupancy, also for a partial final cell at stock boundaries.
        for d in range(3):
            if (grid.shape[d]-.5)*self.pitch > self.dimensions[d]+1e-10:
                sl = [slice(None)]*3
                sl[d] = -1
                grid[tuple(sl)] = False


class Machine:
    def __init__(self, config=None):
        self.config = config or {}
        permitted={"name","verified","notes","source","source_commit","coordinate_derivation",
                   "bodies","fixtures","travel_limits","limits_reference","work_offsets",
                   "machine_origin","clearance_moves","tool_change_moves","tool_change_restores_tip","max_rpm"}
        if set(self.config)-permitted:
            raise ValueError(f"Unknown machine fields: {sorted(set(self.config)-permitted)}")
        for key in ("verified","tool_change_restores_tip"):
            if key in self.config and not isinstance(self.config[key],bool):
                raise ValueError(f"Machine {key} must be a JSON boolean")
        for key in ("clearance_moves","tool_change_moves"):
            for point in self.config.get(key,[]):
                if not point or set(point)-set("xyz") or not all(math.isfinite(float(v)) for v in point.values()):
                    raise ValueError(f"{key} needs finite partial xyz waypoints in the simulation frame")
        if "max_rpm" in self.config and (not math.isfinite(float(self.config["max_rpm"])) or self.config["max_rpm"]<=0):
            raise ValueError("max_rpm must be positive and finite")
        self.name = self.config.get("name", "Unconfigured machine")
        self.verified = bool(self.config.get("verified", False))
        self.body_specs = self.config.get("bodies", [])
        self.fixtures = []
        for fixture in self.config.get("fixtures", []):
            if set(fixture)-{"name","shape","min","max","notes"}:
                raise ValueError("Unknown fixture field")
            if fixture.get("shape", "box") != "box":
                raise ValueError("Fixtures currently require axis-aligned box bounds")
            bounds = np.array([*fixture["min"], *fixture["max"]], dtype=float)
            if bounds.shape != (6,) or not np.isfinite(bounds).all() or np.any(bounds[3:] <= bounds[:3]):
                raise ValueError("Invalid fixture bounds")
            self.fixtures.append((str(fixture["name"]), bounds))
        self.limits = self.config.get("travel_limits")
        if self.limits is not None:
            self.limits = np.asarray([self.limits["min"],self.limits["max"]], dtype=float)
            if self.limits.shape != (2,3) or not np.isfinite(self.limits).all() or np.any(self.limits[1] <= self.limits[0]):
                raise ValueError("Invalid travel limits")
        if self.config.get("limits_reference", "tip") not in ("tip", "gauge"):
            raise ValueError("limits_reference must be tip or gauge")
        # Validate even if no tool ever reaches a body during the job.
        for spec in self.body_specs:
            make_body(spec, 0)

    def bodies(self, tool):
        return tool.bodies+[make_body(spec, tool.stickout) for spec in self.body_specs]

    def missing(self):
        result = []
        roles = {s.get("role", s.get("name")) for s in self.body_specs}
        for role in ("holder", "spindle", "head"):
            if role not in roles:
                result.append(f"Machine geometry has no {role} body")
        if not self.verified:
            result.append("Machine geometry is not marked verified against this physical setup")
        return result


def expanded_body(body, margin):
    if margin == 0:
        return body
    frusta = body.frusta.copy()
    for r in frusta:
        slope = (r[5]-r[4])/(r[3]-r[2])
        add = margin*math.sqrt(1+slope*slope)
        r[2] -= margin
        r[3] += margin
        r[4] += add-slope*margin
        r[5] += add+slope*margin
    boxes = body.boxes.copy()
    boxes[:, :3] -= margin
    boxes[:, 3:] += margin
    return Body(body.name, frusta, boxes, body.role)


class Simulator:
    def __init__(self, stock: Stock, tools: dict[int, Tool], machine: Machine | None = None,
                 grid=None, margin=0., start_verified=True, warnings=None):
        if not math.isfinite(margin) or margin < 0:
            raise ValueError("Collision margin must be finite and nonnegative")
        self.stock, self.tools = stock, tools
        self.machine = machine or Machine()
        self.grid = np.empty(stock.shape, dtype=np.bool_) if grid is None else grid
        if self.grid.shape != stock.shape or self.grid.dtype != np.bool_ or not self.grid.flags.c_contiguous or not self.grid.flags.writeable:
            raise ValueError("Stock array must be writable, C-contiguous bool with stock.shape")
        self.margin = margin
        self.start_verified = start_verified
        self.warnings = list(warnings or [])
        self.bodies = {n:[expanded_body(b,margin) for b in self.machine.bodies(t)] for n,t in tools.items()}
        self.cutter_bodies = {n:expanded_body(Body("cutter",t.cutting,role="cutter"),margin) for n,t in tools.items()}
        self.reset()

    def reset(self):
        self.stock.initialize(self.grid)
        self.removed = 0
        self.collisions = []
        self._events = {}
        self._previous_tool = None

    def _event(self, move, body, target, hit, point=None, reason="collision"):
        if not 0 <= hit <= 1:
            return
        key = (move.line, body, target, reason)
        when = move.t0+(move.t1-move.t0)*hit
        if key in self._events:
            event = self._events[key]
            event["occurrences"] += 1
            if when >= event["time_s"]:
                return
        else:
            event = {"occurrences": 1}
            self.collisions.append(event)
            self._events[key] = event
        event.update({"line": move.line, "tool": move.tool, "body": body, "target": target,
                      "reason": reason, "time_s": float(when), "segment_fraction": float(hit),
                      "tip_mm": (move.start+(move.end-move.start)*hit).tolist(),
                      "stock_voxel_center_mm": None if point is None else list(map(float,point))})

    def _check_body(self, move, body, cutters, reason="collision"):
        args=(self.grid,self.stock.origin,self.stock.pitch)
        if len(body.frusta):
            hit,*point=collide_frusta(*args,body.frusta,cutters,move.start,move.end)
            self._event(move,body.name,"stock",hit,point,reason)
        if len(body.boxes):
            hit,*point=collide_boxes(*args,body.boxes,cutters,move.start,move.end)
            self._event(move,body.name,"stock",hit,point,reason)
        for name,fixture in self.machine.fixtures:
            best=2.
            for row in body.frusta:
                best=min(best,frustum_fixture_hit(row,fixture,move.start,move.end))
            for box in body.boxes:
                best=min(best,box_fixture_hit(box,fixture,move.start,move.end))
            self._event(move,body.name,name,best,reason="fixture_collision")

    def apply(self, move: Move, check=True):
        if move.tool not in self.tools:
            raise ValueError(f"NC line {move.line}: no geometry for T{move.tool}")
        tool=self.tools[move.tool]
        direction = -1 if tool.spec.get("handedness", "right") == "left" else 1
        cutting = not move.rapid and move.spindle == direction and move.rpm > 0
        cutters=tool.cutting if cutting else EMPTY_FRUSTA
        if check:
            if self._previous_tool != move.tool:
                initial=Move(move.start,move.start,move.tool,0,0,True,move.line,move.t0,move.t0)
                self._check_body(initial,self.cutter_bodies[move.tool],EMPTY_FRUSTA,"initial_tool_overlap")
            if not cutting:
                reason="rapid_into_stock" if move.rapid else ("spindle_off" if move.spindle == 0 or move.rpm <= 0 else "wrong_spindle_direction")
                self._check_body(move,self.cutter_bodies[move.tool],EMPTY_FRUSTA,reason)
            else:
                # Fixtures are never machinable stock, even when the spindle runs.
                for name,fixture in self.machine.fixtures:
                    best=min(frustum_fixture_hit(r,fixture,move.start,move.end) for r in self.cutter_bodies[move.tool].frusta)
                    self._event(move,"cutter",name,best,reason="fixture_collision")
            for body in self.bodies[move.tool]:
                self._check_body(move,body,cutters)
            if self.machine.limits is not None:
                offset=np.array([0.,0.,tool.stickout if self.machine.config.get("limits_reference","tip")=="gauge" else 0.])
                for fraction,point in ((0.,move.start+offset),(1.,move.end+offset)):
                    if np.any(point < self.machine.limits[0]-1e-9) or np.any(point > self.machine.limits[1]+1e-9):
                        self._event(move,"tip" if offset[2]==0 else "gauge","travel_limits",fraction,reason="travel_limit")
            if move.rpm > self.machine.config.get("max_rpm", math.inf):
                self._event(move,"spindle","rpm_limit",0.,reason="spindle_speed_limit")
        if cutting:
            self.removed += int(remove_sweep(self.grid,self.stock.origin,self.stock.pitch,cutters,move.start,move.end))
        self._previous_tool=move.tool

    def run(self, program: Program, progress=None, snapshots=None, cancelled=None):
        self.reset()
        missing_tools={m.tool for m in program.moves}-set(self.tools)
        if missing_tools:
            raise ValueError(f"Missing tool definitions: {sorted(missing_tools)}")
        start=time.perf_counter()
        last_update=start
        if snapshots is not None:snapshots.add(0,self.grid,force=True)
        for i,move in enumerate(program.moves):
            if cancelled and cancelled():raise InterruptedError("Simulation cancelled")
            self.apply(move)
            if snapshots is not None:snapshots.add(i+1,self.grid)
            now=time.perf_counter()
            if progress and (now-last_update > .15 or i==len(program.moves)-1):
                progress((i+1)/len(program.moves),move.line)
                last_update=now
        self.elapsed=time.perf_counter()-start
        self.collisions.sort(key=lambda c:c["time_s"])
        return self.report(program)

    def report(self, program):
        missing=self.machine.missing()
        if not self.start_verified:missing.append("Initial tip position was assumed; set --start")
        used=sorted({m.tool for m in program.moves})
        for n in used:
            if not self.tools[n].verified:
                missing.append(f"T{n} geometry/stickout is not marked verified")
        # A macro that changes the tip position cannot be assumed collision-free.
        if any("M6 service motion excluded" in w for w in program.warnings):
            if not self.machine.config.get("tool_change_restores_tip",False):
                missing.append("M6 return position is unconfirmed; set tool_change_restores_tip only after checking firmware behavior")
        status="collisions" if self.collisions else ("incomplete" if missing else "clear_in_model")
        exit_code=2 if self.collisions else (3 if missing else 0)
        initial=math.prod(sum((np.arange(n)+.5)*self.stock.pitch <= dim+1e-10) for n,dim in zip(self.stock.shape,self.stock.dimensions))
        return {"schema_version":1,"simulator_version":__version__,"status":status,"exit_code":exit_code,
                "verification_complete":not missing,"incomplete_reasons":missing,
                "scope":"Programmed 3-axis machining path; hidden ATC/probe/homing/service motion and cutting physics excluded",
                "array":{"dtype":"bool","axis_order":"XYZ","true":"material remaining","false":"air",
                         "shape":list(self.stock.shape),"pitch_mm":self.stock.pitch,"origin_min_mm":self.stock.origin.tolist(),
                         "stock_dimensions_mm":self.stock.dimensions.tolist(),"grid_dimensions_mm":(np.array(self.stock.shape)*self.stock.pitch).tolist(),
                         "coordinate_rule":"origin_min_mm + (index + 0.5) * pitch_mm","occupancy_rule":"voxel center inside remaining solid",
                         "bytes":self.grid.nbytes},
                "removed_voxels":self.removed,"remaining_voxels":int(initial-self.removed),
                "removed_volume_mm3":self.removed*self.stock.pitch**3,
                "nominal_job_time_s":program.duration,"simulation_time_s":getattr(self,"elapsed",None),
                "linearized_segments":len(program.moves),"collision_margin_mm":self.margin,
                "collision_count":len(self.collisions),"collisions":self.collisions,
                "warnings":list(dict.fromkeys(self.warnings+program.warnings)),"machine":self.machine.config,
                "tools":{str(n):self.tools[n].spec for n in used},"events":program.events,
                "limits":["100 um is voxel pitch, not a physical machining-accuracy guarantee",
                          "Sub-voxel features and clearances may be unresolved; set a finer pitch or collision margin",
                          "Motion is nominal; no deflection, runout, backlash, acceleration, corner blending or material forces",
                          "After a reported collision, removal continues as a hypothetical rigid-tool path"]}


class SnapshotCache:
    """Compressed, bounded checkpoints. Restoring never touches the output file."""
    def __init__(self, move_count, max_bytes=128*1024**2, count=24):
        self.interval=max(1,math.ceil(move_count/count))
        self.max_bytes=max_bytes
        self.frames={}
        self.bytes=0

    def add(self,index,grid,force=False):
        if not force and index % self.interval:return
        blob=zlib.compress(np.packbits(grid,axis=None,bitorder="little").tobytes(),1)
        if len(blob)>self.max_bytes:return
        while self.frames and self.bytes+len(blob)>self.max_bytes:
            key=next(iter(self.frames))
            self.bytes-=len(self.frames.pop(key))
        self.frames[index]=blob
        self.bytes+=len(blob)

    def restore(self,index,grid,stock):
        keys=[k for k in self.frames if k<=index]
        if not keys:
            stock.initialize(grid)
            return 0
        k=max(keys)
        packed=np.frombuffer(zlib.decompress(self.frames[k]),dtype=np.uint8)
        # Unpack in small chunks; a large job should not require a second grid.
        flat=grid.reshape(-1)
        chunk=1024**2
        for p in range(0,len(packed),chunk):
            values=np.unpackbits(packed[p:p+chunk],bitorder="little")
            end=min(flat.size,(p+chunk)*8)
            flat[p*8:end]=values[:end-p*8]
        return k


def save_result(path, grid, report):
    """Atomic .npy + JSON writes; chunked so a memmap is never copied into RAM."""
    path=Path(path).resolve()
    if path.suffix.lower()!=".npy":raise ValueError("Output filename must end in .npy")
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix=path.stem+"-",suffix=".partial.npy",dir=path.parent)
    os.close(fd)
    try:
        out=np.lib.format.open_memmap(tmp,mode="w+",dtype=np.bool_,shape=grid.shape)
        src,dst=grid.reshape(-1),out.reshape(-1)
        chunk=8*1024**2
        digest=hashlib.sha256()
        for i in range(0,src.size,chunk):
            dst[i:i+chunk]=src[i:i+chunk]
            digest.update(memoryview(np.ascontiguousarray(src[i:i+chunk])).cast("B"))
        out.flush()
        del dst
        out._mmap.close()
        del out
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)
    report=dict(report)
    report["array"]=dict(report["array"],file=path.name,raw_array_sha256=digest.hexdigest())
    report_path=path.with_suffix(".report.json")
    fd,tmp=tempfile.mkstemp(prefix=path.stem+"-",suffix=".json",dir=path.parent)
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as f:json.dump(report,f,indent=2,allow_nan=False)
        os.replace(tmp,report_path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)
    return report,path,report_path


def warmup():
    """Compile/cache kernels once. Windows wheels need no compiler toolchain."""
    grid=np.ones((2,2,2),dtype=np.bool_)
    origin=np.zeros(3);a=np.array([0.,0.,3.]);b=np.array([1.,1.,3.])
    rows=np.array([[0.,0.,0.,1.,1.,.5]])
    boxes=np.array([[-1.,-1.,0.,1.,1.,1.]])
    remove_sweep(grid,origin,.1,rows,a,b)
    collide_frusta(grid,origin,.1,rows,rows,a,b)
    collide_boxes(grid,origin,.1,boxes,rows,a,b)
    frustum_fixture_hit(rows[0],boxes[0],a,b)
    box_fixture_hit(boxes[0],boxes[0],a,b)
