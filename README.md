# Carvera voxel simulator

A Python 3-axis CNC material-removal simulator and geometric collision checker.
Default voxel pitch is **0.1 mm (100 µm)**. The result is a genuine 3D NumPy
boolean array, including cavities and undercuts, rather than a height map.

Headless operation requires NumPy and Numba. The optional native desktop viewer
uses PySide6 Essentials, PyQtGraph and OpenGL. There is no network service or
connection to the CNC machine.

## Windows quick start

Use **standard (GIL-enabled), 64-bit CPython 3.14** on Windows 10/11.
Extract this folder somewhere writable. Double-click `setup_windows.cmd`, then
`demo_viewer.cmd`.
The setup creates `.venv314`, so it can also be run in a folder containing an
older `.venv` installation.

Equivalent PowerShell commands, from this folder:

```powershell
py -3.14 -m venv .venv314
.\.venv314\Scripts\python.exe -m pip install ".[viewer]"
.\.venv314\Scripts\python.exe -m carvera_sim examples/demo.nc --stock 30 20 6 --tools examples/tools.json --start 0 0 5 --output result.npy --visualize
```

For headless-only installation, install `.` instead of `.[viewer]`.
No Visual Studio/C++ compiler is required; dependencies have Windows x64 wheels.
Numba compiles and caches the numeric kernels on the first invocation, so that
invocation has additional startup cost. A working OpenGL desktop driver is
needed for the viewer.

Version **0.2.0** targets Python 3.14. All **97 tests** passed on Linux with
Python 3.14.10, including metric, meshing and Qt widget regressions. Native
Python 3.14 desktop playback and chart/mouse controls were exercised. The
80 × 60 × 12 mm benchmark achieved about **31 FPS at 0.1 mm display pitch**
with 10× playback, using Mesa software OpenGL. Initial verification and full
mesh generation are excluded from this frame-rate measurement.
Windows x64 Python 3.14 dependency wheels were resolved/downloaded during 0.1.1;
**a native Windows runtime was not available for execution testing**. A
Windows/Linux, Python 3.14 GitHub Actions test matrix is included, but has
not been run on GitHub as part of this delivery.

## Run your job

```powershell
.\.venv314\Scripts\python.exe -m carvera_sim job.nc --stock 50 50 5 --tools my_tools.json --machine my_machine.json --start 0 0 10 -o result.npy
```

Add `--visualize` to open the desktop window. Omit it for agent verification.
If the NC includes complete `;@MKR|TOOL|...` records for its cutter types,
`--tools` can be omitted. Older NC files generally need a separate tool file.
NC alone cannot reliably identify a physical tool, stickout, fixtures or offsets.
Embedded metadata does not automatically count as verified geometry.

Minimum input with supported embedded tools:

```powershell
.\.venv314\Scripts\python.exe -m carvera_sim job.nc --stock 50 50 5 -o result.npy
```

This uses a nominal Carvera Air head model, assumes initial tip `(0,0,5)`, and
returns an **incomplete** verification status until those assumptions are
resolved. It still computes and saves the stock.

All command-line dimensions, tools, fixtures, offsets and reported coordinates
are **millimetres**, even when a parsed NC program uses G20.

### Coordinates

By default, stock occupies `X=[0,width]`, `Y=[0,length]`, `Z=[-height,0]`.
Thus NC zero is the top/front/left corner. The positional argument order for
`--stock` is always **X Y Z**. Specify the minimum corner explicitly when needed:

```powershell
# Stock centred in XY, with its top at Z=0:
.\.venv314\Scripts\python.exe -m carvera_sim job.nc --stock 50 50 5 --stock-origin -25 -25 -5 --tools my_tools.json --start 0 0 10 -o result.npy
```

`--start X Y Z` is the actual starting **tool-tip** position in this same
simulation coordinate frame. The tool axis is always +Z, with its tip at the
commanded position. Tool length compensation is represented by tool-tip
coordinates plus explicit stickout, not by applying an imaginary H table.

### Outputs and exit codes

The first array in `result.npy` is C-contiguous `numpy.bool_`, ordered **[X, Y, Z]**. `True` means
material remains; `False` means air. Shape is `ceil(stock_dimensions / pitch)`.
Initial occupancy is determined by voxel centres, including partial boundary
cells. This can quantize each stock face by up to half a voxel.

A second, structured numeric array in the **same file** stores the time-resolved
metrics. Existing `np.load("result.npy")` and `mmap_mode="r"` consumers still
receive the bool grid. Use `load_metrics()` / `load_result()` below to read the
appended array. No pickle or object arrays are used.

`result.report.json`: origin, pitch, shape, coordinate mapping, raw array hash,
NC hash, tool/machine configuration, warnings, removed volume, timings and
collision records with NC line, time, tool, body, target and contact voxel.
JSON and NPY are individually written through temporary files and renamed.
The JSON hash can detect a mismatched pair after an interrupted write.

| Exit code | Meaning |
|---|---|
| 0 | No collision found in the configured, verified geometric model |
| 1 | Input, unsupported command, configuration, allocation or other error |
| 2 | One or more collisions / configured limit violations detected |
| 3 | Simulation completed, but geometry or starting assumptions are unverified |
| 130 | Cancelled |

Code 2 takes precedence over code 3. `verification_complete` and
`incomplete_reasons` remain available even when collisions were found.
An error never silently converts unsupported motion into a successful result.
Existing completed output is not removed merely because a subsequent run fails;
check the exit code and the report's NC hash before consuming it.

For agents:

```powershell
.\.venv314\Scripts\python.exe -m carvera_sim job.nc --stock 50 50 5 --tools my_tools.json --machine my_machine.json --start 0 0 10 -o result.npy --json --quiet
```

The final report is the only stdout JSON. Progress/errors otherwise go to
stderr. The viewer also writes the final files, but does not accept `--json`.

Reading the result:

```python
import json
import numpy as np

stock = np.load("result.npy", mmap_mode="r")
report = json.load(open("result.report.json", encoding="utf-8"))
origin = np.array(report["array"]["origin_min_mm"])
pitch = report["array"]["pitch_mm"]
index = np.array([100, 120, 20])
voxel_center_mm = origin + (index + 0.5) * pitch
material_present = bool(stock[tuple(index)])
```

## Dynamic metrics

Metrics are computed during verification, saved in the NPY, and displayed in
two linked charts above the viewer timeline. Click a chart or drag its cursor
to pause and seek to a suspicious interval. Chart rendering preserves visible
peaks when reducing points to screen pixels; the saved samples are unchanged.

| Field | Meaning |
|---|---|
| `t_start_s`, `t_end_s` | Nominal interval start/end in seconds |
| `line`, `tool` | NC line and T number |
| `removed_mm3` | Material actually removed in this interval |
| `removal_rate_mm3_min` | Removed voxel volume × 60 / interval seconds |
| `approach_speed_mm_min` | Largest positive velocity component toward a remaining-stock voxel face within 20 mm of the rotating cutter envelope |
| `rapid` | Whether this is a G0 interval |

Approach is zero for tangential/retreating motion when no stock lies ahead
along a moving axis within 20 mm. A diagonal move over a horizontal surface
reports its downward component, not its total feed. Pockets and undercut
ceilings use the remaining three-dimensional stock. The normal is a **voxel
face normal**, not a fitted smooth-surface normal; staircase effects remain on
curved/sloping surfaces. Fixtures and holder/head geometry have separate
collision checks and are not included in this metric.

Each motion is split into intervals of at most **0.1 s and 1 mm**. Approach is
the maximum of start/mid/end probes against stock before that interval is cut;
removal rate is the interval mean. These are diagnostic samples, not a bounded
continuous peak detector. An interval crossing the 20 mm threshold can carry
a nonzero peak even though its start was farther away. Use smaller sampling
limits when inspecting a short transient:

```powershell
.\.venv314\Scripts\python.exe -m carvera_sim job.nc --stock 50 50 5 --tools my_tools.json --start 0 0 10 -o result.npy --metrics-period 0.02 --metrics-distance 0.2 --visualize
```

The default `--max-metric-samples` guard is 2,000,000 (57 bytes per row).
Zero-duration material removal retains `removed_mm3` and has a `NaN` rate;
the JSON counts these undefined samples. A rapid never excavates material.
The rates use programmed constant segment velocity, without acceleration,
backlash, deflection or material-force simulation. They expose potentially
hazardous commands; no material-specific danger threshold is inferred.

```python
from carvera_sim.engine import load_result, load_metrics

stock, metrics = load_result("result.npy")  # stock is memory-mapped by default
rate = metrics["removal_rate_mm3_min"]
approach = metrics["approach_speed_mm_min"]
times = metrics["t_start_s"]
# Or load only metrics without reading the voxel payload:
metrics = load_metrics("result.npy")
```

Without this package, open the file once and call `np.load(stream,
allow_pickle=False)` twice: first stock, then metrics. `load_metrics()` returns
an empty typed table for legacy stock-only files. The schema-v2 JSON report
documents sampling, units, peaks, array offset and separate raw-array hashes.

## Tools

`examples/tools.json` demonstrates tool definitions. Keys must match the actual
NC T numbers. A T number is a job assignment, not a unique cutter catalog ID.
`verified: true` is an assertion that you have checked the dimensions and
installed stickout. It is not a request to guess missing dimensions.

```json
{
  "tools": {
    "1": {
      "name": "My measured flat end mill",
      "type": "flat",
      "diameter": 3.175,
      "flute_length": 12,
      "shoulder_length": 12,
      "shank_diameter": 3.175,
      "stickout": 25,
      "verified": true
    }
  }
}
```

`stickout` is the tip-to-lowest-holder-face distance. Machine bodies anchored at
`gauge` begin at that height. All profile coordinates are measured upward from
the tool tip. `angle` is an **included** angle; `half_angle` is explicitly a
half angle. Diameters and radii have distinct field names.

| Family / aliases | Geometry and additional parameters |
|---|---|
| `flat`, corn, O flute, face | Flat cylindrical cutting envelope |
| `ball`, ball nose | Hemispherical tip followed by cylindrical flutes |
| `bull`, bull nose | `corner_radius`; flat centre plus toroidal corner profile |
| `v`, engraving, chamfer, UV solder-mask removal | `angle`, `tip_diameter`; truncated cone and optional cylindrical continuation |
| `drill` | Explicit `angle` such as 118; conical point and cylindrical flutes |
| `tapered_flat` | `angle`, `tip_diameter`; taper limited by `diameter` and flute length |
| `tapered_ball` | `tip_radius`, `half_angle`; spherical tip tangent to taper |
| `thread` | `neck_diameter`, `thread_angle`, optional `tooth_height`, `teeth`, `pitch`, `tooth_start` |
| `lollipop` | Spherical envelope; `flute_length` must equal `diameter`; set the neck dimensions |
| `dovetail` | Diameter decreases from `diameter` at the tip to `neck_diameter` at flute top |
| `t_slot`, keyhole, slot | Cylindrical cutting head; narrower neck/shoulder is separately non-cutting |
| `profile`, form, radius, corner-round, circle-segment barrel/lens/oval/taper | Explicit `[height, radius]` profile; supports increasing/decreasing radii and steps |

Custom form tools are supported through their actual profile, rather than
substituting a flat mill for an unfamiliar type. For example:

```json
{
  "type": "profile",
  "flute_length": 4,
  "profile": [[0,0.5],[0.5,2.0],[1.0,0.5],[4.0,0.5]],
  "shoulder_length": 6,
  "shank_diameter": 3.175,
  "stickout": 20,
  "noncut_profile": [[4,0.5],[6,0.5],[7,1.5875],[20,1.5875]],
  "verified": true
}
```

Repeated heights allow abrupt radial steps. Heights must be nondecreasing and
radii nonnegative. Circular portions of a custom profile should be sampled
finely enough for your geometric tolerance. `noncut_profile` overrides the
default neck/shank model and can describe shoulder tapers. Without it the
default shank starts at `shoulder_length`; a narrow neck occupies any gap
between flute and shoulder lengths. Optional per-tool `bodies` can add collars.

### Makera catalog and embedded metadata

The package contains **124 nominal cutting tools** extracted from Makera's
published Fusion profiles: flat/O-flute/corn, ball nose, engraving/chamfer,
drill and thread milling. It records the original numeric geometry and source
commit. These are **not an export of every version of Studio's proprietary
database**, and downloaded catalog entries are unverified by default.

List the catalog:

```powershell
.\.venv314\Scripts\python.exe -m carvera_sim --list-tools > catalog.json
```

Assign a catalog entry to a job T number by its exact `id` or unique `name`:

```json
{
  "tools": {
    "1": {
      "catalog_id": "Spiral O Metal 3.175*12mm",
      "stickout": 25,
      "verified": false
    }
  }
}
```

Confirm the actual tool, neck transition, collar and stickout before changing
`verified`. Nominal catalog stickout uses Fusion's body length (`LB`). Thread
tools use a revolved triangular tooth profile; verify tooth position, height
and any truncation against the real tool or supply an explicit custom profile.

Supported simple `;@MKR|TOOL` records are read automatically. Explicit JSON
definitions override metadata for the same number. A thread/custom/tapered-ball
record that lacks enough shape information requests a separate tool definition
instead of silently approximating it. Unknown cutter names are rejected.
Lasers are outside this mechanical milling simulator's scope.

## Machine and fixtures

The default `carvera_sim/data/carvera_air_nominal.json` comes from the **Z
component of Makera's official simplified Carvera Air STEP model**. It includes
the lower nose/holder, spindle nose, motor envelope and Z head plate. Cylinder
radii are extracted from CAD; motor/plate boxes conservatively enclose their
CAD geometry. The coordinate transform and source commit are in the JSON.

This profile is unverified and is **not a Carvera C1 profile**. It does not
include probes, dust shoes, hoses, wiring, the X gantry or the enclosure.
Add relevant geometry and fixtures for your setup. The separate
`examples/machine.template.json` uses explicitly illustrative dimensions and
demonstrates a configurable G28 clearance path; its values are not factory data.

Bodies may be cylinders, frusta, arbitrary revolved profiles or axis-aligned
boxes, with XYZ offsets and `anchor: "gauge"` or `"tip"`. Each receives a name
and a role (`holder`, `spindle`, `head`, etc.). Every body is swept continuously
through the NC path, not just checked at endpoints.

Fixed fixture boxes are in the stock/simulation coordinate frame:

```json
"fixtures": [
  {"name":"left clamp", "shape":"box", "min":[-8,10,-5], "max":[2,20,3]}
]
```

The cutting tool also collides with fixtures; they are never removed as stock.
Frustum/box contacts with fixture boxes are tested continuously and do not
depend on the stock voxel pitch. Curved fixtures can be conservatively bounded
by boxes. General STL/STEP collision meshes are not an input format in v0.1.

Optional machine keys:

| Key | Meaning |
|---|---|
| `verified` | You have validated the machine bodies against this setup |
| `work_offsets` | `{"G54":[0,0,0],"G55":[x,y,z]}`: workspace origins in the simulation frame |
| `machine_origin` | Position of machine-coordinate zero in the simulation frame; required by G53/G10 |
| `clearance_moves` | Ordered world-frame partial waypoints, e.g. `[{"z":20},{"x":0,"y":0}]`, used for Carvera G28 |
| `tool_change_restores_tip` | Confirms that M6 returns to the same programmed tip position; hidden service motion remains excluded |
| `tool_change_moves` | Optional explicit post-change return waypoints, interpreted in the simulation frame |
| `travel_limits` | `{"min":[x,y,z],"max":[x,y,z]}` in the simulation frame |
| `limits_reference` | `"tip"` or `"gauge"` for those travel limits |
| `max_rpm` | Optional spindle speed ceiling |

No unknown machine home, clearance point, fixture position or tool offset is
invented. A G28 without configured waypoints is an error. Carvera G28 means
clearance positioning, not a generic return-to-home move. Tool-change service
paths, probing and calibration routines are excluded from this simulator.

## Viewer

The window opens while the worker calculates the final stock and report. Once
those files are saved, playback becomes available:

- Start, pause, stop/rewind, 0.1×–250× speed.
- Click/drag timeline or enter an exact nominal time; seek in either direction.
- Excavation and approach charts with synchronized cursors and click/drag seeking.
- Collision list entries seek to the first recorded contact.
- Left drag rotates; right/middle drag or Shift+left drag pans; wheel zooms.
- Space toggles play/pause, Home stops/rewinds, Ctrl+Q closes.
- Show/hide head geometry and toolpath; reset camera; select display detail.

Seeking restores compressed checkpoints and replays the missing path portion.
The saved final result and metric history are immutable during playback.
**Full resolution is now the default and never silently coarsens.** Only
64³-voxel chunks touched by actual removal, plus neighbouring boundary cells,
are remeshed. Cached surfaces are packed into one OpenGL draw. This preserves
all exposed voxel faces, including undercuts, without rescanning the full
stock at every playback frame. Optional 2×/4× previews still use max-pooling
and can hide small holes; the actual display pitch is shown.

Initial meshing and arbitrary seeks can still take about a second on the
57.6-million-voxel benchmark. Very fragmented surfaces, large cutters, high
speed multipliers and GPU/driver differences can lower frame rate. Reproduce
the native playback measurement (with head and path visible) using:

```powershell
.\.venv314\Scripts\python.exe scripts/benchmark_playback.py --seconds 10 --speed 10 --output playback.json
```

## Supported NC and deliberate errors

- Modal G0/G1; G2/G3 circular/helical interpolation in G17/G18/G19.
- Relative IJK, absolute centre G90.1, relative centre G91.1; positive/negative
  R arcs and IJK full circles. Inconsistent arc radii beyond tolerance fail.
- G20/G21, G90/G91, configured G54–G59, G92/G92.1/G92.2/G92.3.
- G53 and G10 L2 P1–6 with known `machine_origin`; a new work offset must be
  fully specified or preconfigured.
- G93 inverse-time / G94 feed-per-minute. G93 requires F on every feed block.
- Community-style block-local G0 F; it does not overwrite the G1 feed.
- T selection, M6, M3/M4/M5 and S. Wrong spindle direction, stopped spindle
  and rapids do not remove material; contact is reported.
- G4 P/S seconds. G81/G82/G83 in G17/G94 are expanded into explicit motions;
  G98/G99, incremental repetition and G80 are supported. Peck re-entry is at
  feed because firmware-specific rapid re-entry clearances are not inferred.
- M0/M1 events, M2/M30 termination, M7/M8/M9, M400; N numbers, semicolon and
  nested parenthesized comments, percent delimiters, configurable block delete.
- G40 is accepted. G49 requires a subsequent M6 before any motion/dwell so an
  unknown tool-length cancellation cannot silently shift the tip. G61/G64 use
  the nominal programmed path; physical corner blending is excluded.

Rotary/auxiliary axes, cutter compensation G41/G42, numeric tool compensation
G43, probing, homing G28.2, height maps, macros, loops, subprograms, unsupported
machine M codes and ambiguous words are rejected. They are not silently skipped.
G20 is geometrically converted but warns about documented community-firmware
inch-mode issues. Canned-cycle support is a parser capability, not a claim that
every Carvera firmware accepts those commands.

## Accuracy, collisions and speed

**100 µm is the grid pitch, not a guarantee that the real machine will cut
within 100 µm.** Material occupancy and stock contacts use voxel centres. At
0.1 mm pitch a cell's centre-to-corner distance is approximately 0.086603 mm.
Features/clearances below the grid scale can be unresolved. Use a finer pitch
or a positive `--collision-margin` for closer inspection. Margin inflates the
collision bodies and can intentionally report conservative false positives.

Curved tool profiles and arcs default to 0.005 mm chord tolerance each.
Straight tool motion uses continuous sweeps, so it has no tool-position sampling
gap, even on a very long move. The tool envelope assumes rotation; individual
flute impacts, feed-per-tooth effects and finite spindle acceleration are not
modeled. There is no runout, tool deflection, backlash, chip evacuation, cutting
force or stock/support deformation model.

The numeric core finds the vertical interval swept by each convex frustum in
each intersected XY voxel column, then clears contiguous Z ranges. This is a
full volumetric representation; it merely uses column spans as an acceleration.
Compiled kernels use float64 geometry and do not enable fast-math relaxation.
For collisions in remaining stock, earliest body arrival is compared with
earliest cutter arrival **before** removal. A later cut cannot erase an earlier
collision. After a crash is reported, the remaining simulation is hypothetical:
the tool continues on the programmed rigid path.

Measured on this development host, with collision checking enabled:

| Job | Grid | Segments | Simulation kernel/dispatch time |
|---|---|---:|---:|
| Included synthetic 80 × 60 × 12 mm raster, 0.2.0 / Python 3.14, metrics enabled | 57,600,000 voxels | 11,570 | 2.92 s |
| Makera TopClamp example, historical 0.1.0 / Python 3.12, no metrics | 50,000,000 voxels | 9,634 | 1.17 s |

These are host-specific observations, not Windows performance promises. They
exclude initialization, parsing, JIT/cache loading, mesh generation and export.
The synthetic run's nominal feed time was about 32.4 minutes. Reproduce it with:

```powershell
.\.venv314\Scripts\python.exe scripts/benchmark.py
```

The bool array uses one byte per voxel: `ceil(X/p) * ceil(Y/p) * ceil(Z/p)`.
For example, 100 × 100 × 20 mm at 0.1 mm needs 200,000,000 bytes (190.7 MiB).
Use `--memmap` for a temporary disk-backed working array. Export is chunked;
viewer checkpoints add compressed bit-packed snapshots, budgeted at 128 MiB
plus transient packing buffers. The default allocation guard is two billion
voxels; increase `--max-voxels` explicitly only when suitable.

## Python API and tests

```python
from carvera_sim.engine import Stock, Machine, Simulator, save_result
from carvera_sim.gcode import Parser
from carvera_sim.tools import load_tools
import json

tools = load_tools("my_tools.json")
machine = Machine(json.load(open("my_machine.json", encoding="utf-8")))
program = Parser(start=(0, 0, 10)).parse(open("job.nc", encoding="utf-8-sig").read())
sim = Simulator(Stock([50, 50, 5], [0, 0, -5], 0.1), tools, machine)
report = sim.run(program)
save_result("result.npy", sim.grid, report)
```

When using the API, pass machine offsets and clearance paths to `Parser`, just
as the CLI does. `sim.grid` remains a normal ndarray/memmap for subsequent
analysis. For latency measurements call `engine.warmup()` first.

```powershell
.\.venv314\Scripts\python.exe -m pip install ".[test,viewer]"
.\.venv314\Scripts\python.exe -m pytest -q
```

Tests cover continuous capsule sweeps, ramps and tapers against independent
dense geometric sampling, fixture tangencies, collision chronology, undercuts,
all catalog entries, all tool families, arc planes/helices, units/offsets,
spindle/rapid behavior, rejection paths, rewind determinism, memmap round-trips,
Unicode/space-safe path handling and timeline clicks. `VALIDATION.json` records
the actual execution environment and results for this delivery.

The source ZIP includes the local Git repository and incremental commits.
Run `git log --oneline` for change boundaries. `HANDOVER.md` documents the
architecture, metric definitions, output compatibility and continuation work;
`validation/` contains this release's test and performance evidence.

## Sources

- [Makera CarveraProfiles](https://github.com/MakeraInc/CarveraProfiles), pinned
  to `de08a657bdc9c230a094dbdba792acd70bfcdf32`: numeric cutter/holder profiles,
  simplified Air STEP and TopClamp NC example.
- [Makera CAM tool library guide](https://wiki.makera.com/en/software/MakeraCAM_userguide).
- [Carvera Community G codes](https://carvera-community.gitbook.io/docs/firmware/supported-commands/gcodes).
- [Carvera Community M codes](https://carvera-community.gitbook.io/docs/firmware/supported-commands/mcodes).

This is an independent simulator. It is not an official Makera product or a
machine safety certification. A `clear_in_model` result covers the configured
geometry and supported nominal NC path only.
