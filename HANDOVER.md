# Carvera voxel simulator — engineering handover

**Snapshot:** 11 November 2026 · **package:** `carvera-voxel-sim` 0.1.1 · **runtime:** standard, GIL-enabled, 64-bit CPython 3.14.

This document describes the delivered implementation, its design rationale, the evidence collected, and the work that remains. It is intended to let another agent continue without the original conversation. Source references and function names refer to the 0.1.1 archive identified below. Decisions are implementation choices, not claims that the model reproduces every behavior of a real controller.

## 1. Start here

The working baseline is implemented and packaged. It accepts a three-axis NC program and rectangular stock, simulates material removal on a full three-dimensional voxel grid, checks configured machine/tool/fixture geometry, exports a NumPy array and JSON report, and optionally opens a native playback window.

**The main unfinished acceptance work is native Windows execution and verification against the user's physical machine/tool setup.** The supplied machine model is a nominal **Carvera Air** model, not a measured assembly or a Carvera C1 model. The bundled catalog is not an exhaustive export of the proprietary Makera Studio database. These distinctions must survive future changes and product claims.

The latest user-directed change was to target Python 3.14. All 80 existing tests passed on CPython 3.14.10 on Linux after that migration. Windows x64 dependency wheels were downloaded successfully. The native Windows application has not been run here.

### Delivered source

[Download carvera-voxel-sim.zip](https://chatgpt.com/library?file_id=libfile_fde3_f-ccf424dfa2388191b14add94ab57380c_e95ac02493bc8191a8d2024072df5f9a&account_id=personal)

| Property | Value at handover |
|---|---|
| Source package version | `0.1.1` |
| Archive filename | `carvera-voxel-sim.zip` |
| Archive bytes | 79,991 |
| Archive files | 32 |
| Archive SHA-256 | `045690f5fb56510ddcb94469d7e79831c3476b75853232d3955a545afd7a677f` |
| Archive top-level folder | `carvera-voxel-sim/` |
| Runtime requirement | `>=3.14,<3.15` |
| Source-control state | No Git repository was created for the simulator; a CI workflow is included |

The archive and local project files were compared byte-for-byte while preparing this handover and matched. This handover is a separate companion document; the source archive was not changed to add it. If the archive is updated later, its checksum and version above describe this snapshot only.

### Suggested first actions for the next agent

1. Obtain the archive, read `README.md` and `VALIDATION.json`, and inspect `pyproject.toml`.
2. On native Windows, install standard x64 Python 3.14 and run `setup_windows.cmd`, then `demo_viewer.cmd`.
3. Run the 80-test suite and the deliberate-collision example. Record the actual OS, Python and package versions.
4. Obtain the actual tool assignments, installed stickouts, work offsets, fixture positions and initial tool-tip position before attempting to verify a real job.
5. Verify the nominal Air geometry and firmware-specific G28/M6 behavior before treating a report as complete.
6. Make any further work against this baseline; preserve the strict parsing, collision chronology and output contracts described below.

## 2. User goal and scope

The original request was a Python voxel **three-axis Carvera CNC simulator** with:

- NC file and stock dimensions as inputs.
- A simulated final job result saved as a NumPy array.
- A nominal 100 µm resolution/accuracy target.
- Support for Makera Studio carving tool families.
- Spindle, holder and machining-head geometry for collision checking.
- A startup visualization flag opening a desktop window with timeline, speed, start/stop/seek and mouse orbit/pan/zoom.
- Enough speed for automated agent verification.
- Windows operation.

The user subsequently required **Python 3.14**. Keep that as the current target, not the earlier Python 3.12 setup.

Relevant workshop context: the user's machine is a **Carvera Air**, and they use community controller/firmware. They also do four-axis work, but the requested simulator is explicitly three-axis. Rotary axes are currently rejected. Do not infer that four-axis support exists because the user owns that accessory.

The intended use is geometric NC verification. The application has no connection to the machine and sends no control commands. It is not a controller emulator, cutting-force solver, crash-proof machine certificate, or material-specific feeds/speeds advisor.

### What “100 µm” currently means

The default **voxel pitch is 0.1 mm**. It does not guarantee physical machining accuracy within 100 µm. Occupancy and stock contacts use voxel centres. Arcs and curved cutter profiles are additionally approximated within configurable chord tolerances. Runout, deflection, backlash and controller dynamics are outside the model.

This was an explicit engineering interpretation of the resolution requirement. A future claim about a bounded total geometric error would require a separate error analysis and acceptance tests.

## 3. Decision register

| Decision | Implemented choice | Reason and consequence |
|---|---|---|
| Stock representation | Dense, C-contiguous, three-dimensional `numpy.bool_` array | Preserves roofs, cavities and undercuts from T-slot, dovetail and similar tools. One byte per voxel; large stock can consume substantial memory. |
| Cutting geometry | Union of coaxial/revolved frusta | One numeric representation handles cylindrical, tapered, rounded and non-monotone radial profiles. Uses the rotating envelope, not individual flutes. |
| Straight motion | Analytic continuous swept volumes | Avoids gaps from stamping tool positions at discrete intervals, including long or fast moves. |
| Curved motion | Arc/helical path split into bounded-error chords | Reuses the same continuous straight-sweep engine while retaining a stated path approximation. |
| Curved cutter profiles | Piecewise-linear radial profile with bounded chord error | Reuses frusta; rounded geometry is not analytically spherical in the cutting kernel. |
| Numeric runtime | Numba CPU kernels, float64 geometry, `cache=True`, `nogil=True`; no `fastmath` | Keeps a Python API and supports normal Windows wheels without requiring a C++ compiler or GPU. No GPU backend is implemented. |
| Collision ordering | Compare first body arrival against first active-cutter arrival before changing stock | A later cut cannot conceal an earlier holder/head crash on the same segment. |
| Fixtures | Fixed axis-aligned boxes, tested continuously | Detects even thin fixtures independently of voxel pitch. General mesh fixtures remain future work. |
| Machine geometry | Frusta/revolved profiles and axis-aligned boxes | Transparent, configurable envelopes with bounded complexity. No runtime STEP/STL collision importer. |
| Default machine | Nominal Air envelopes extracted from official simplified CAD, marked unverified | Better provenance than invented dimensions; still requires physical verification and accessory geometry. |
| Unknown NC behavior | Reject unsupported commands/syntax | An agent must not receive a successful result from a silently altered toolpath. The parser is intentionally a restricted dialect. |
| Work/machine coordinates | One explicit simulation frame; configured offsets | Avoids inventing machine home, WCS positions or tool-length tables. |
| G28 | Explicit ordered clearance waypoints | Carvera-specific clearance positioning is not treated as generic G-code homing. |
| M6 | Tool state changes plus optionally supplied return waypoints | Hidden service/probe/ATC movement is excluded. Default return-position assumption is reported as incomplete. |
| Tool identification | Explicit NC T-number mapping, optional catalog lookup or supported NC metadata | Catalog IDs and job tool slots are different concepts. Names alone cannot prove installed geometry. |
| Verification status | Separate collision, incomplete-model and clear-in-model outcomes | Zero detected collisions must not silently imply verified geometry. |
| Result format | Plain `.npy` plus adjacent JSON report | Easy for agents to memory-map and inspect without the GUI. Geometry metadata is in JSON, not embedded in the ndarray. |
| File writes | Individually atomic NPY and JSON replacement, raw-array hash | Avoids partially written individual files; the pair is not a two-file transaction. |
| UI workflow | Compute and save final result first; then replay | Playback does not overwrite or corrupt the final exported result. |
| Seeking | Bounded compressed checkpoints plus replay | Deterministic backward seeking without storing a full grid for every frame. |
| Display geometry | Greedy voxel boundary mesh, optional max-pooling | Keeps display work separate from simulation accuracy. Coarse display can hide small cavities. |
| Python migration | 0.1.1 targets 3.14 and uses `.venv314` in Windows launchers | Makes the requested runtime explicit and avoids reusing an old `.venv` interpreter. |
| Dependency policy | Bounded version ranges, tested versions recorded | Installation is convenient, but it is not fully locked/reproducible across future releases. |

## 4. Architecture and source map

```mermaid
flowchart TD
    NC["NC text"] --> P["Parser: Program and Move records"]
    TJ["Tool JSON / NC metadata / catalog"] --> T["Tool frusta and non-cutting bodies"]
    MJ["Machine JSON"] --> M["Machine bodies, fixtures and offsets"]
    M --> P
    S["Stock dimensions and pitch"] --> G["Boolean XYZ grid"]
    P --> E["Simulator and Numba kernels"]
    T --> E
    M --> E
    G --> E
    E --> O["Final NPY and JSON report"]
    E --> C["Compressed checkpoints"]
    C --> R["Replay and mesh generation"]
    R --> W["Qt/OpenGL window"]
```

| File | Responsibilities and primary entry points |
|---|---|
| `carvera_sim/cli.py` | `argument_parser()`, `prepare(args)`, `main(argv)`: input validation, metadata precedence, model construction, headless or GUI dispatch, exit codes and temporary memmap cleanup. |
| `carvera_sim/gcode.py` | `NCError`, `Move`, `Program`, `Parser`, `arc_points()`: strict modal parsing and expansion to timed straight segments. |
| `carvera_sim/tools.py` | `Tool`, `Body`, `make_tool()`, `make_body()`, `profile_frusta()`, `load_tools()`, `embedded_tools()`: cutter and assembly geometry. |
| `carvera_sim/catalog.py` | `catalog()`, `resolve_tool_spec()`: package-resource loading and explicit catalog lookup. |
| `carvera_sim/kernels.py` | Continuous sweep/removal/contact routines and numeric interval/quadratic helpers. |
| `carvera_sim/engine.py` | `Stock`, `Machine`, `Simulator`, `SnapshotCache`, `save_result()`, `warmup()`: orchestration, collision reports, checkpoints and export. |
| `carvera_sim/replay.py` | `Replay.seek()`, `Replay.part()`: GUI-independent, fractional, bidirectional replay. |
| `carvera_sim/mesh.py` | `stock_mesh()`, `greedy_mesh()`, `pooled()`, `frusta_mesh()`, `boxes_mesh()`: rendering geometry only. |
| `carvera_sim/viewer.py` | `Worker`, `Signals`, `SeekSlider`, `View`, `Window`, `launch()`: native desktop UI and asynchronous preparation/replay. |
| `carvera_sim/__init__.py` | Package `__version__`. Keep it aligned with `pyproject.toml`. |
| `carvera_sim/__main__.py` | Enables `python -m carvera_sim`. |
| `carvera_sim/data/makera_catalog.json` | 124 nominal cutters and original numeric source geometry. |
| `carvera_sim/data/carvera_air_nominal.json` | Default unverified Air assembly envelopes and CAD transform/provenance. |
| `examples/tools.json` | Synthetic/example flat, ball, V, drill and thread tool dimensions; all unverified. |
| `examples/machine.template.json` | Illustrative machine and G28 configuration, not factory data. |
| `examples/demo.nc` | Two-tool pocket/circular-feature demonstration. |
| `examples/collision.nc` | Deliberate rapid-through-stock program. |
| `examples/results/` | Saved sample NPY and report from 0.1.0, retained as a regression reference. |
| `scripts/benchmark.py` | Reproducible synthetic raster benchmark with collisions enabled. |
| `tests/` | Five test modules; 80 test cases after parametrization. |
| `.github/workflows/tests.yml` | Windows/Linux Python 3.14 matrix; tests and viewer imports. Not run on GitHub in this session. |
| `setup_windows.cmd`, `demo_viewer.cmd` | Windows bootstrap and demonstration; CRLF line endings. |
| `README.md`, `VALIDATION.json` | User-facing manual and recorded validation evidence. |

There are 11 package Python modules. Qt is imported lazily from the CLI only when `--visualize` is requested. The headless engine does not require the viewer extra.

## 5. Runtime, installation and migration history

### Current dependency declarations and tested versions

| Component | Declared requirement | Tested in the Python 3.14 environment |
|---|---|---|
| CPython | `>=3.14,<3.15` | 3.14.10, standard GIL-enabled x64 Linux build |
| NumPy | `>=2.3.3,<2.4` | 2.3.5 |
| Numba | `>=0.63.1,<0.66` | 0.65.1 |
| llvmlite | Transitive Numba requirement | 0.47.0 |
| PySide6 Essentials | `>=6.10,<7`, viewer extra | 6.12.0 |
| Shiboken6 | Exact transitive requirement of PySide6 Essentials | 6.12.0 |
| PyQtGraph | `>=0.14,<0.15`, viewer extra | 0.14.0 |
| PyOpenGL | `>=3.1.7,<4`, viewer extra | 3.1.10 |
| pytest | `>=8.4,<10`, test extra | 9.2.0 |
| setuptools | `>=68`, isolated build dependency | Build succeeded; exact build-env version was not recorded |

`shiboken6` is Qt's Python/C++ bindings support library. It is pulled in automatically by `PySide6-Essentials`; version 6.12.0 of that package requires exactly `shiboken6==6.12.0`. The user asked what it was after installation; no special Shiboken configuration was needed.

Free-threaded Python builds were not tested or targeted. Do not describe a downloaded `cp314` wheel as proof of `cp314t` compatibility.

### Windows quick start

From the extracted project directory:

```powershell
.\setup_windows.cmd
.\demo_viewer.cmd
```

Equivalent manual setup:

```powershell
py -3.14 -m venv .venv314
.\.venv314\Scripts\python.exe -m pip install --upgrade pip
.\.venv314\Scripts\python.exe -m pip install ".[test,viewer]"
.\.venv314\Scripts\python.exe -m pytest -q
.\.venv314\Scripts\python.exe -m carvera_sim --version
```

For headless-only use, install `.` rather than `.[viewer]`. The installed console entry point is `carvera-sim`; `python -m carvera_sim` is often simpler when an agent must select an exact interpreter.

### Changes from 0.1.0 to 0.1.1

- Runtime requirement changed from `>=3.11,<3.14` to `>=3.14,<3.15`.
- Package version changed in both `pyproject.toml` and `carvera_sim/__init__.py`.
- NumPy, Numba, PySide6 and pytest minimums were raised.
- Windows scripts now call `py -3.14` and use `.venv314`.
- README commands and GitHub Actions matrix now target 3.14.
- Validation metadata was updated to distinguish current Python 3.14 tests from original Python 3.12 interactive tests and benchmarks.
- Numeric simulation algorithms were unchanged. The installed 3.14 package produced a demo ndarray exactly equal to the previous sample.

A 0.1.1 wheel was built and inspected for `Requires-Python` and packaged JSON resources. The deliverable is the source ZIP; downloaded dependency wheels and development virtual environments are not bundled.

## 6. Inputs, coordinate conventions and output contract

### CLI defaults worth preserving

| Option | Current default/behavior |
|---|---|
| Positional `nc` | UTF-8 NC file; UTF-8 BOM accepted |
| `--stock X Y Z` | Required positive dimensions, mm |
| `--stock-origin X Y Z` | Minimum stock corner; defaults to `(0,0,-stock_height)` |
| `--pitch` | `0.1` mm |
| `--start X Y Z` | Actual initial tool tip in simulation coordinates; if omitted, assumes `(0,0,5)` and marks result incomplete |
| `--initial-tool` | `1` |
| `--rapid-feed` | `2400` mm/min for nominal timing; not a validated machine maximum |
| `--arc-tolerance` | `pitch/20`; 0.005 mm at default pitch |
| `--profile-tolerance` | `pitch/20`; 0.005 mm at default pitch |
| `--collision-margin` | `0` mm; nonnegative envelope inflation |
| `--tools` | Optional JSON; explicit definitions override corresponding embedded NC tools |
| `--machine` | Optional JSON; otherwise loads nominal Air profile |
| `--output`, `-o` | `result.npy`; suffix must be `.npy` |
| `--memmap` | Off; when enabled, temporary disk-backed working grid |
| `--max-voxels` | 2,000,000,000; allocation guard for one-byte bool voxels |
| `--block-delete` | Off; `/` blocks execute unless flag is supplied |
| `--json` | Final JSON to stdout; progress to stderr; incompatible with `--visualize` |
| `--quiet` | Suppresses progress; use `--json --quiet` for agents |
| `--visualize` | Opens optional native viewer |
| `--list-tools` | Prints bundled catalog and exits without requiring a job |

CLI arc/profile tolerances must be positive and at most half the voxel pitch. The lower-level API does not reproduce every CLI guard automatically.

### Coordinates

All geometry is in millimetres in one simulation/world frame. With the default stock origin, stock spans `X=0..width`, `Y=0..depth`, `Z=-height..0`. The tool tip is the commanded point; the tool extends in positive Z. There is no tool tilt or workpiece rotation.

For voxel index `(i,j,k)`:

```python
center_mm = origin_min_mm + (index + 0.5) * pitch_mm
```

The array is indexed **XYZ**, not the ZYX convention used by many image-processing tools. It is C-contiguous, so Z is the fastest-changing index in memory.

`Stock.shape` uses `ceil(dimension/pitch - 1e-10)` to avoid floating-point near-integer over-allocation. Boundary occupancy is still centre-based: an allocated final cell can initially be air if its centre lies beyond the exact stock dimension. Do not infer material volume solely from `array.size` for non-integral stock dimensions.

Work offsets map G54–G59 origins into this frame. G54 initially exists at `(0,0,0)` unless configured otherwise. `machine_origin` is the location of machine-coordinate zero in the simulation frame. It is required for G53 and supported G10 offset updates.

### Files and report status

`result.npy` contains `numpy.bool_`: **True = material remains**, **False = air**. `result.report.json` supplies shape, pitch, origin, original stock dimensions, hashes, model configuration, warnings, timings, collisions and incomplete reasons. The report schema is currently version 1.

| Exit code | Status/meaning |
|---|---|
| 0 | `clear_in_model`: no collision found and required model assertions are complete |
| 1 | `error`: parsing, unsupported commands, configuration, allocation or runtime error |
| 2 | `collisions`: collision or configured travel/RPM violation |
| 3 | `incomplete`: computation finished but model/setup assertions are missing |
| 130 | Headless keyboard cancellation |

Collision status takes precedence over incomplete status. Always inspect `verification_complete` and `incomplete_reasons` even after exit 2. Exit 0 is only a statement about this model's scope; excluded service motions and physical effects remain excluded.

The GUI returns the final report's exit code after closing. Closing before preparation succeeds leaves the worker's default error code 1; the README's cancellation code 130 describes the headless KeyboardInterrupt path, not every GUI cancellation.

A failed new run can leave an older completed output at the requested path. Agents must check the current process exit code, the report's NC SHA-256 and the array hash instead of consuming a pre-existing file blindly. Prefer separate output paths per job/run when integrating into automation.

`save_result()` writes the array in 8 MiB chunks, then the JSON; each file uses a temporary file and `os.replace`. The two replacements are not transactional as a pair. `array.raw_array_sha256` hashes the C-order bool bytes, not the NPY header or whole file. `input.nc_sha256` hashes the original NC bytes, including any BOM.

## 7. Tool model and catalog

### Core types

`Tool` holds `number`, `name`, `kind`, `cutting`, `bodies`, `stickout`, `verified`, and the resolved input `spec`. `Body` holds a name, role, frusta and/or boxes.

A frustum row is float64 with this exact order:

```text
[x_offset, y_offset, z_bottom, z_top, radius_bottom, radius_top]
```

A box row is:

```text
[x_min, y_min, z_min, x_max, y_max, z_max]
```

Tool-local Z heights are measured upward from the programmed tip. `profile_frusta()` accepts ordered `[height, radius]` points. Repeated heights create radial steps and are skipped as zero-height segments; remaining positive-volume segments form a union. Profiles may increase or decrease in radius, so undercutting tools are supported.

`stickout` means tip-to-lowest-holder-face distance. A body anchored to `gauge` gets a Z translation equal to stickout; a `tip` body does not. `make_body()` also supports an XYZ `offset`.

### Families and parameters

| Family | Shape/required extra geometry |
|---|---|
| Flat, corn, O-flute, face | Cylindrical cutting envelope |
| Ball / ball nose | Hemispherical tip plus cylindrical flutes |
| Bull / corner radius | `corner_radius`; circular corner profile plus flat centre |
| V / engraving / chamfer / UV solder-mask | Explicit included `angle`, optional `tip_diameter` |
| Drill | Explicit included `angle`; conical point plus cylinder |
| Tapered flat | Included `angle`, optional `tip_diameter`, bounded by diameter/flute length |
| Tapered ball | `tip_radius`, `half_angle`; sphere-to-taper tangency |
| Thread mill | `neck_diameter`; optional `thread_angle`, `tooth_height`, `teeth`, `pitch`, `tooth_start` |
| Dovetail | Diameter at bottom narrowing to `neck_diameter` at flute top |
| T-slot / keyhole / slot | Cutting head cylinder plus separately non-cutting neck |
| Lollipop | Spherical envelope; `flute_length == diameter`; explicit neck geometry advised |
| Custom/profile, form, radius, corner-round, circle-segment families | Explicit radial profile; no guessed substitution for missing shape information |

`angle` is an included angle; `half_angle` is a half angle. Diameter and radius fields are distinct. Every tool needs `type` and `flute_length`; conventional tools also need `diameter`. `profile` and `tapered_ball` use their explicit profile/tip parameters.

Default shank diameter is 3.175 mm, default shoulder length is flute length, and default stickout is `max(flute_length + 10, 25.5)` mm. These defaults permit exploratory simulation; they are not measured data. A tool is considered verified only if the JSON `verified` value is an actual boolean true and explicit stickout plus shank diameter or `noncut_profile` are present.

The default neck fills the flute-to-shoulder gap and the shank runs from shoulder to stickout. `noncut_profile` replaces that default model. Optional per-tool `bodies` add collars or other geometry. Left-handed tools use `handedness: "left"`; otherwise clockwise M3 is treated as the cutting direction.

Unknown tool fields and unknown type names raise errors. The `verified` flag is an assertion supplied by the caller; it does not independently measure the tool or guarantee that every supplied profile is physically correct.

### T-number mapping and precedence

Tool JSON can be either a direct object keyed by NC T numbers or `{"tools": {...}}`. A catalog entry can be selected by exact `catalog_id` or a unique exact name, then overridden with measured geometry. Explicit JSON definitions override `;@MKR|TOOL|...` records for the same T number.

The supported metadata reader uses fields such as `number`, `type`, `diameter`, `flutelength`, `handlediameter`, `shoulderlength`, `sticklength`, `angle`/`halfAngle`, `tipdiameter` and `cornerradius`. It marks imported tools unverified and warns. Incomplete thread, tapered-ball, custom-profile and dovetail metadata requires a separate JSON definition. No direct Studio SQLite/database importer is shipped.

### Bundled catalog provenance and limits

124 cutters were extracted from the official Makera Fusion tool-profile files at commit:

`de08a657bdc9c230a094dbdba792acd70bfcdf32`

| Normalized family | Entries |
|---|---:|
| Flat/O-flute/corn | 45 |
| Drill | 30 |
| V/engraving/chamfer | 23 |
| Ball | 18 |
| Thread | 8 |
| **Total** | **124** |

Entries retain `source_file`, original numeric `source_geometry`, original `source_holder` information where present, a resolved `spec`, and a stable source ID. Nominal stickout uses Fusion body length `LB`; this must not be assumed equal to the user's installed extension. Recorded source-holder metadata is provenance and is not automatically substituted for the configured machine holder.

Thread entries use revolved triangular tooth envelopes. Actual tooth location, truncation, pitch, neck and mounting geometry need confirmation. Catalog entries are all unverified by default. Lasers and holder-only definitions were not counted as carving tools.

**Do not claim every tool in every release of Makera Studio is automatically supported.** The engine covers many radial families, and custom profiles cover further axisymmetric forms. The proprietary database, its current schema and every shipped physical tool have not been exhaustively validated.

## 8. Machine model and collision frame

The default is `carvera_sim/data/carvera_air_nominal.json`, derived from the Z component of Makera's official `Machine_Design_Files/Carvera_Air_Simplified.step` at the pinned commit. It is `verified: false` and `tool_change_restores_tip: false`.

The extraction recorded local spindle centre `x = -74.0385852576533`, `z ≈ 29`, and the lower nose face at `y = 201.458967162417` in the CAD component frame. The transformation is:

```text
simulation X = CAD x + 74.0385852576533
simulation Y = 29 - CAD z
simulation Z = CAD y - 201.458967162417
```

The gauge origin is the lower nose face. These are CAD derivation coordinates, not machine homing/WCS offsets.

### Default gauge-anchored envelopes, mm

| Body | Representation |
|---|---|
| `holder_nose` / holder role | Cylinder, radius 8, Z 0..20 |
| `spindle_nose` / spindle role | Cylinder, radius 16.7899370932549, Z 20..25 |
| `spindle_motor_envelope` / spindle role | Box min `[-31.001,-44,25]`, max `[30.650,29,196.210]` |
| `head_plate_envelope` / head role | Box min `[-60,29,26.779]`, max `[59.6,41,199.280]` |

The cylinders use extracted CAD radii; the boxes conservatively enclose their corresponding CAD bodies. The source is simplified CAD, not metrology-grade measurement.

The default omits X gantry, machine frame/enclosure, probe, dust shoe, hoses, wiring and installation-specific accessories. It also has no fixtures, travel limits, RPM ceiling, machine origin or G28 clearance path. Those absent constraints are not automatically inferred, and not all omissions are represented as an incomplete reason. A caller who sets `verified: true` must understand the restricted scope.

The separate machine template is illustrative and contains a sample `[{"z":20},{"x":0,"y":0}]` G28 path. Do not copy these coordinates into a real verification setup without establishing them.

### Supported configuration

- Moving `bodies`: `cylinder`, `frustum`, `profile`, or axis-aligned `box`, with name, role, anchor and optional offset.
- Fixed `fixtures`: named axis-aligned boxes in the simulation frame; fixtures are never cut away.
- `work_offsets`: configured G54–G59 origins.
- `machine_origin`: machine-coordinate zero in the simulation frame.
- `clearance_moves`: ordered partial lower-case `x`, `y`, `z` world-frame waypoints for standalone G28.
- `tool_change_moves`: optional explicit post-M6 return waypoints in the same frame.
- `tool_change_restores_tip`: caller assertion of return to the prior programmed tip when no explicit return path is supplied.
- `travel_limits`: min/max box, with `limits_reference` equal to `tip` or `gauge`.
- `max_rpm`: optional positive spindle speed ceiling.

The completeness check requires machine body roles `holder`, `spindle` and `head` in the machine configuration, plus machine verification. Per-tool bodies alone do not satisfy this machine-role check. Unknown machine/body/fixture fields and string values masquerading as verification booleans are rejected.

All moving bodies currently translate with the tool tip. There is no general machine-kinematic hierarchy. Do not attach a real axis-dependent gantry part as if it followed XYZ identically unless that is a deliberately conservative envelope.

## 9. Parser behavior and firmware boundaries

`Parser.parse()` creates a fresh local modal state on every call. Configured offsets are copied; G10/G92 changes from one parse do not leak into the next parse. `Move` contains start/end arrays, tool number, spindle direction, RPM, rapid flag, source line, start/end time and kind. `Program` holds moves, warnings and events; duration is the final move's end time.

Initial state is mm, G90, incremental arc centres, G17, G54, G0, G94, spindle off, zero RPM, undefined feed and the configured initial tool. The parser's default initial tip is `(0,0,5)`; the CLI tracks whether this was explicitly supplied.

| Commands | Current interpretation |
|---|---|
| G0/G1 | Straight rapid/feed movement; feed movement requires positive F. |
| G2/G3 | G17/G18/G19 arcs and helices; IJK centres or positive/negative R; IJK full circles. |
| G90/G91 | Absolute/incremental endpoints. |
| G90.1/G91.1 | Absolute/incremental arc centres; absolute centres need both in-plane coordinates. |
| G20/G21 | Inch-to-mm conversion / mm; G20 emits a community-firmware caveat. |
| G54–G59 | Configured work offsets; undefined selection is an error. |
| G53 | G90 G0/G1 movement with configured `machine_origin`. |
| G10 L2 P1..6 | Work-offset update using machine origin; a new offset requires XYZ unless already configured. |
| G92 / .1 / .2 / .3 | Temporary offset set, clear, suspend and restore. |
| G28 | Standalone Carvera clearance move requiring explicit ordered waypoints. |
| G93/G94 | Inverse-time / units-per-minute feed. G93 requires F on every feed block. |
| G81/G82/G83 | Expanded drilling cycles in G17/G94; R/Z, dwell, pecks and repeats. |
| G98/G99, G80 | Initial-plane/R-plane cycle retract; cycle cancellation. |
| G4 P or S | Dwell in seconds. `G4 S` does not overwrite spindle RPM. |
| T, M6 | T preselects; standalone Tn M6 changes tool and stops spindle. |
| M3/M4/M5, S | Spindle direction/off and RPM state. |
| M0/M1 | Pause events; user waiting time is not assigned a duration. |
| M2/M30 | End event; later blocks are ignored. |
| M7/M8/M9, M400 | Accepted non-geometric coolant/synchronization commands. |
| G40 | Cutter-compensation cancellation accepted; G41/G42 unavailable. |
| G49 | Marks tip compensation unknown; motion/dwell is rejected until a subsequent M6 establishes tool state. |
| G61/G64 | Nominal programmed path; no corner blending. G64 warns. |

Community-style `G0 ... F...` is block-local when supplied with rapid axis motion; it does not overwrite the later cutting feed. Standalone F sets the modal feed. Default rapid timing is configurable. Speeds affect nominal timing, not the geometric envelope.

Arcs use right-handed plane mappings: G17 `(X,Y,Z)`, G18 `(Z,X,Y)`, G19 `(Y,Z,X)`. Inconsistent endpoint radii beyond `max(1e-7, arc_tolerance)` are rejected. Tiny accepted rounding discrepancies are interpolated rather than creating a final jump. Each arc is guarded against generating more than two million segments.

G83 re-entry toward the previous depth is deliberately emitted at feed, rather than guessing a controller-specific rapid clearance. Cycle repeat and peck counts are guarded. Cycle parsing capability does not imply every Carvera firmware accepts those cycles.

Nested parenthesized comments, semicolon comments, blank lines, `%`, line numbers and bare O program labels are handled. `/` block deletion follows the CLI flag.

### Explicitly unsupported

Rotary/auxiliary `A B C U V W`, cutter compensation G41/G42, numeric tool-length compensation G43/H tables, probing, homing G28.2, height-map compensation, macros/variables, loops and subprogram calls, and unknown G/M commands are rejected. Duplicate words, conflicting supported modal commands, malformed syntax and unconsumed geometric parameters are also rejected in the implemented paths.

This is not a complete formal parser for all RS-274 or Carvera firmware combinations. If a real export fails, establish the exact meaning and add a regression before implementing it. Do not solve compatibility by adding an unconditional “ignore unknown command” mode to verification.

### M6 limitation

M6 sets the newly selected tool and stops spindle/RPM. Explicit `tool_change_moves`, when supplied, model only the configured return movements using the new tool. With no such path the parser warns that service motion is excluded and assumes the same programmed tip position. Unless `tool_change_restores_tip` is confirmed, this becomes an incomplete reason.

Neither branch models the entire ATC/manual-change/probe/calibration sequence. Adding return waypoints does not make hidden service motion verified.

## 10. Numeric geometry and collision chronology

### Material removal

Each convex frustum swept along a straight path intersects a fixed vertical XY column in one Z interval. `frustum_span()` computes that interval from endpoints, radius-transition points and stationary candidates. `remove_sweep()` enumerates candidate XY columns, converts the span to centre-based Z indices and clears those cells.

The algorithm still stores a complete 3D solid. Using column intervals accelerates the subtraction; it does not turn the stock into a height map. A non-convex tool is represented by multiple frusta whose individual contributions form a union.

Long diagonal moves use projected narrow XY bounds per X column rather than scanning their full rectangular XY bounding box. This avoids excessive work without subdividing the motion into arbitrary time steps.

### Contact primitives

- `quadratic_hit()`: earliest solution of a quadratic inequality in a bounded interval, using stable roots.
- `slab()`: linear interval clipping.
- `first_frustum_hit()`: first time a moving frustum reaches a given point.
- `first_box_hit()`: first time a translated box reaches a point.
- `collide_frusta()` / `collide_boxes()`: remaining-stock voxel contacts.
- `frustum_fixture_hit()` / `box_fixture_hit()`: continuous contacts against a fixed box; independent of stock voxel pitch.

`MISS` is 2.0, outside the segment fraction range `[0,1]`; the shared geometric epsilon is `1e-10`, with additional local near-degenerate guards. Fixture logic includes explicit endpoint/tangent checks because contact can occur at an isolated time without an open interval of overlap.

### Per-segment sequence in `Simulator.apply()`

1. Resolve the current tool and whether cutting is active: **not rapid**, positive RPM, and spindle direction matching handedness.
2. On the first segment or a change to a different tool number, check cutter overlap at the segment start before allowing material removal.
3. If cutting is inactive, test the cutter against stock with reason `rapid_into_stock`, `spindle_off`, or `wrong_spindle_direction`.
4. Test active cutters against fixtures; fixtures are never machinable stock.
5. Test every non-cutting tool/machine body against remaining stock and fixtures.
6. Apply configured travel and spindle-RPM limits.
7. Only then remove the swept cutting volume, if cutting is active.

For a stock voxel, a body collision is suppressed only if an active cutter arrives no later than the body, within numerical tolerance. A body arriving first remains a collision even if the cutter would remove that voxel later in the same segment.

A dwell with a running cutter can remove the stationary rotating envelope. The first-tool overlap check still prevents an initial embedded tool from being silently treated as a legitimate plunge.

Travel bounds are checked at segment endpoints. For a linear path through an axis-aligned allowed box this detects an out-of-bounds segment, but the report time is an endpoint sample, not an exact first boundary-crossing time. Arc behavior is based on its chords. RPM checks compare recorded S to an optional limit; there is no spindle acceleration model.

### Collision records

Records contain source line, tool, body, target, reason, nominal time, segment fraction, tip position and an optional contacted stock voxel centre. Fixture events have no stock contact voxel. Records are aggregated by `(line, body, target, reason)`, with earliest time retained and `occurrences` incremented. The count is a count of aggregated records, not a count of all contacted voxels or damaged parts.

After a detected collision, the engine continues subtracting along the hypothetical rigid programmed path. This is useful for diagnosis, but later geometry does not describe what a physically crashed machine would actually do.

### Collision margin

`expanded_body()` inflates collision frusta/boxes. The actual cutting-removal geometry remains uninflated. A positive margin can help inspect small clearances and intentionally produces conservative false positives; it is not a complete error bound covering all omitted physics.

## 11. Replay, rendering and UI concurrency

The GUI uses PySide6 Essentials + PyQtGraph OpenGL + PyOpenGL. A custom stock shader uses ambient and two directional contributions so pocket walls remain legible. The UI is a visualization client around the same simulation engine, not a separate numerical implementation.

`Worker` is one dedicated Python thread. It warms JIT kernels, computes the full report with checkpoints, saves final output, and emits a ready signal. Then it processes replay/mesh requests. This single-worker ownership avoids concurrent mutation of the stock grid.

Requests use a condition variable and one pending slot: a newer request replaces a pending older request. Seeking increments a generation number; stale frames are ignored by the UI. An in-progress sweep or mesh build is not instantly preempted. Cancellation is checked between simulation moves and during replay; closing joins the worker and can wait for an expensive current kernel/mesh operation.

### Checkpoints and replay

`SnapshotCache` targets about 24 checkpoints and a default 128 MiB compressed budget. It uses `np.packbits(..., bitorder="little")` followed by zlib level 1. Old frames are evicted when the budget is exceeded. If no earlier checkpoint remains, replay initializes the original stock and starts from the beginning. Restoration unpacks in chunks.

`Replay.seek()` uses move end times, restores an earlier checkpoint for backward seeking, and applies only the missing complete or fractional straight sweeps. Replay calls `Simulator.apply(check=False)`: it is visual stock reconstruction, not a new verification pass.

**Important API caveat:** replay mutates the simulator's working grid and some counters. The saved report/array remain the authoritative final result. Do not call `Simulator.report()` after arbitrary replay and treat it as a fresh final verification report. Likewise, a user-supplied `grid` to `Simulator` supplies storage; construction/reset initializes stock and does not load a previous machining result as initial material.

### Meshes

`stock_mesh()` extracts the boundary of the entire volumetric grid, including internal exposed surfaces and undercuts. Greedy meshing merges coplanar voxel faces. Auto detail chooses a stride so the largest dimension is approximately 220 display cells. Coarsening uses max-pooling: any occupied fine voxel makes the coarse cell occupied.

There is a 400,000-quad guard. If a mesh overflows, the renderer retries at a coarser stride instead of truncating geometry silently. Even a full-resolution request can therefore fall back; the actual display pitch is shown. Display vertices use float32; numeric simulation remains float64. Very large path displays are decimated, but simulated moves are not.

### Controls

- Start, Pause and Stop; Stop rewinds to zero after preparation.
- Speeds: 0.1, 0.25, 0.5, 1, 2, 5, 10, 25, 50, 100 and 250×; default 10×.
- Click/drag timeline, exact time spinbox, collision-click seeking.
- Left drag orbit; right/middle drag or Shift+left drag pan; wheel zoom.
- Space play/pause, Home stop/rewind, Ctrl+Q close.
- Auto/full/2×/4× display detail, head visibility, path visibility, reset camera.

`SeekSlider` was introduced because the ordinary slider click behavior did not provide direct timeline seeking. It has a Qt mouse-event regression test. A nominal 33 ms UI timer does not imply the numerical renderer guarantees 30 FPS for every stock.

## 12. Accuracy, memory and performance limits

At pitch `p`, a voxel centre is at most `sqrt(3)*p/2` from a corner. At `p=0.1 mm`, that distance is **0.08660254 mm**. Stock-face placement is quantized by centre occupancy, and sub-voxel features or clearances can be unresolved. The 0.005 mm default path/profile chord tolerances are separate approximations; do not simply call the whole simulator “100 µm accurate.”

Straight sweeps are analytic for the primitive model subject to floating-point tolerance. Rounded profile chords lie inside the corresponding ideal circular profile. Arc/tool approximation, actual tool dimensions and machine geometry must all be considered when assessing a narrow clearance.

The model excludes finite-flute engagement, spindle acceleration, runout, tool/workpiece deflection, backlash, acceleration/deceleration, corner blending, cutting forces, chip evacuation and fixture compliance. It also excludes tool breakage and physical consequences after a collision.

### Memory

A bool grid uses approximately `ceil(X/p) * ceil(Y/p) * ceil(Z/p)` bytes. Additional arrays, mesh buffers, Python move objects and checkpoint packing buffers consume memory beyond that number.

| Stock and pitch | Grid shape | Bool-grid bytes |
|---|---|---:|
| 30 × 20 × 6 mm, 0.1 mm | 300 × 200 × 60 | 3,600,000 |
| 80 × 60 × 12 mm, 0.1 mm | 800 × 600 × 120 | 57,600,000 |
| 100 × 100 × 20 mm, 0.1 mm | 1,000 × 1,000 × 200 | 200,000,000 ≈ 190.7 MiB |

Halving pitch multiplies dense grid size by approximately eight. `--memmap` reduces the requirement for a resident working grid, but does not eliminate OS paging, mesh, program-list or checkpoint memory costs. `SnapshotCache`'s 128 MiB limit covers stored compressed blobs, not every transient packing buffer.

The CLI's two-billion-voxel guard is not applied automatically by direct `Stock`/`Simulator` API use. Large repeated or finely linearized programs are also held as Python `Move` objects in memory; there is no streaming NC executor.

### Recorded performance, with collision checking enabled

| Benchmark | Segments | Grid voxels | Simulation loop time |
|---|---:|---:|---:|
| Synthetic raster, 80 × 60 × 12 mm | 11,570 | 57,600,000 | 1.388954731 s |
| Official Makera TopClamp example, 100 × 100 × 5 mm | 9,634 | 50,000,000 | 1.171047187 s |

These are original **Linux / Python 3.12.14** observations. They exclude stock initialization, parsing, JIT/cache loading, mesh generation and export. They are not native Windows or Python 3.14 performance measurements.

The synthetic benchmark's nominal programmed time was 1,941.800565 seconds, approximately 32.36 minutes; it removed 17,636,640 voxels and recorded zero collisions. JIT/cache warmup was approximately 0.600 s and parsing approximately 0.289 s. The nominal machine profile was unverified.

TopClamp removed 5,010,708 voxels and had zero collision records, but report status was **incomplete**. That run used the illustrative machine template, an explicitly supplied sample G28 path and embedded tools. It was a compatibility/performance exercise, not certification of the physical TopClamp job.

Reproduce the included synthetic workload with:

```powershell
.\.venv314\Scripts\python.exe scripts/benchmark.py --output benchmark.json
```

Report current results separately rather than relabeling old benchmark numbers as new-platform measurements.

## 13. Validation evidence and regression expectations

### Current Python 3.14 validation

- CPython **3.14.10**, x64 Linux, standard build.
- **80 passed, 0 failed, 0 skipped**, full suite; recorded duration **25.161 s**.
- Installed package imports identify version 0.1.1.
- `from carvera_sim.viewer import Window` succeeds.
- `pip check` reports no broken requirements.
- Windows x64 binary wheels resolved/downloaded for NumPy, Numba, llvmlite, PySide6 Essentials, Shiboken6 and the remaining viewer/test dependencies.
- A 0.1.1 wheel built successfully; Python requirement and bundled catalog resources inspected.
- Installed-package demo CLI run returned exit 3 as expected for unverified geometry; output was exactly equal to the previous sample ndarray.

No native Windows execution occurred. The GitHub Actions matrix is present but was not run. Under Python 3.14, Qt imports and the offscreen timeline widget test passed; full manual 3D GUI interaction was not repeated after the runtime migration.

### Original native GUI validation

On Linux/X11 with Python 3.12.14, a real desktop window was opened and manually exercised: rendering, start, pause, stop/rewind, speed changes, timeline click, exact-time entry, backward seeking, tool-change display, full-resolution display, head visibility, orbit, pan, zoom and clean Ctrl+Q shutdown.

The GUI-exported final array matched the headless output. Playback did not modify the exported final file.

### Tests and why they matter

| Test module | Evidence covered |
|---|---|
| `tests/test_geometry.py` | Exact capsule comparison; ramps/tapers against independent dense sampling; leading/trailing-body chronology; thin fixture on a long move; randomized cone/fixture cases; stationary and quadratic tangencies; isolated endpoint contact; moving boxes. |
| `tests/test_gcode.py` | Modal units/offsets, local rapid F, all arc planes, full-circle helix, signed-R arcs, inverse-time feed, absolute centres, G53/G10, parser reuse, cycles, G28, G4 S, comments/block delete/M6, G49 and rejection cases. |
| `tests/test_tools.py` | Construction of all 124 catalog entries, tool families, rounded-tip chord bound, embedded metadata overrides and invalid dimensions/types. |
| `tests/test_engine.py` | Spindle/rapid behavior, machine bodies, fixtures, limits, true undercuts, output round-trip, checkpoints/partial replay, stock boundaries, meshes, memmap, Unicode/space paths, errors, initial overlap and strict JSON fields. |
| `tests/test_viewer_widgets.py` | Qt timeline click and drag seeking under the offscreen platform. |

The sampled-reference tests are independent approximations with boundary allowances; they are not a formal proof of the analytic kernels. Construction of 124 catalog entries proves validity under the schema, not physical correctness of every catalog dimension.

### Golden demo values

Run from the project directory:

```powershell
.\.venv314\Scripts\python.exe -m carvera_sim examples/demo.nc --stock 30 20 6 --tools examples/tools.json --start 0 0 5 --output demo_result.npy --json --quiet
```

Expected baseline:

| Quantity | Value |
|---|---|
| Shape / dtype | `(300, 200, 60)` / bool |
| Linearized segments | 88 |
| Removed voxels | 621,656 |
| Remaining voxels | 2,978,344 |
| Removed volume | 621.656 mm³ |
| Nominal time | 35.194261926242916 s |
| Collision records | 0 |
| Status / exit | `incomplete` / 3 |
| Raw array SHA-256 | `82c690b664e20c0efe3136068057741b350909011279408fdbf3f35b4185083e` |

The incomplete reasons are expected: nominal machine and example tools are unverified, and M6 return behavior is unconfirmed. Do not change the example flags just to make the demo return zero.

`examples/results/demo_result.report.json` intentionally still says simulator 0.1.0: it is the original reference export. `VALIDATION.json` records the 0.1.1 migration and exact array equality.

For a deliberate crash, substitute `examples/collision.nc` with the same stock/tools/start options and a separate output path. The expected status is collision/exit 2; model incompleteness can remain true as well.

## 14. Integration examples and invariants

### Agent-facing invocation

```powershell
.\.venv314\Scripts\python.exe -m carvera_sim job.nc --stock 50 50 5 --tools my_tools.json --machine my_machine.json --start 0 0 10 --output job_result.npy --json --quiet
```

Inspect the process exit code before deciding what to do with stdout. Exit 2 or 3 still produces completed result files; exit 1 may leave an older output intact.

### Read a completed array and verify its raw hash

```python
from pathlib import Path
import hashlib
import json
import numpy as np

path = Path("job_result.npy")
report = json.loads(path.with_suffix(".report.json").read_text(encoding="utf-8"))
grid = np.load(path, mmap_mode="r", allow_pickle=False)
assert grid.dtype == np.bool_
assert list(grid.shape) == report["array"]["shape"]
assert report["array"]["axis_order"] == "XYZ"

raw = grid.reshape(-1)
digest = hashlib.sha256()
for start in range(0, raw.size, 8 * 1024**2):
    digest.update(memoryview(raw[start:start + 8 * 1024**2]).cast("B"))
assert digest.hexdigest() == report["array"]["raw_array_sha256"]

origin = np.asarray(report["array"]["origin_min_mm"])
pitch = report["array"]["pitch_mm"]
index = np.array([10, 20, 5])
center = origin + (index + 0.5) * pitch
occupied = bool(grid[tuple(index)])
```

This verifies pair consistency, not physical setup correctness. Also compare `input.nc_sha256` with the intended input when consuming results from an automated workflow.

### Complete lower-level API construction

```python
from pathlib import Path
import json
from carvera_sim.engine import Stock, Machine, Simulator, save_result, warmup
from carvera_sim.gcode import Parser
from carvera_sim.tools import load_tools

config = json.loads(Path("my_machine.json").read_text(encoding="utf-8-sig"))
tools = load_tools("my_tools.json", tolerance=0.005)
machine = Machine(config)
parser = Parser(
    start=(0, 0, 10),
    initial_tool=1,
    rapid_feed=2400,
    arc_tolerance=0.005,
    work_offsets=config.get("work_offsets"),
    machine_origin=config.get("machine_origin"),
    clearance_moves=config.get("clearance_moves"),
    tool_change_moves=config.get("tool_change_moves"),
)
program = parser.parse(Path("job.nc").read_text(encoding="utf-8-sig"))
sim = Simulator(
    Stock([50, 50, 5], [0, 0, -5], 0.1),
    tools,
    machine,
    start_verified=True,  # Only if the caller actually established this tip position.
)
warmup()
report = sim.run(program)
report, array_path, report_path = save_result("job_result.npy", sim.grid, report)
```

The direct API does not add the CLI's NC hash, input metadata or tolerance-report fields automatically. Use CLI preparation or add those fields explicitly if downstream consumers require them. The API also defaults `start_verified=True`; callers must not inherit that default for an assumed start position.

### Invariants to retain during changes

- Full XYZ material representation, including material/air/material along a Z column.
- Continuous segment sweeps; feed or GUI frame rate must not change removed volume.
- Cutter and body arrival compared before mutating stock.
- Fixtures remain non-machinable even with a correctly spinning cutter.
- Unknown motion/state does not silently become a clear result.
- Missing geometry/initial-position assertions remain visible.
- Explicit JSON overrides metadata by actual NC T number.
- Stock origin, pitch, XYZ order and hashes stay in the output contract.
- Simulation resolution is independent of display detail.
- Seeking cannot overwrite the final exported NPY/report.
- Default/sample geometry stays unverified until measured evidence justifies changing it.

## 15. Open work and continuation priorities

These items are outstanding work or review targets, not claims that they were completed.

### Priority 1 — Windows acceptance

Run clean installation, tests and actual OpenGL playback on the user's Windows environment. Include first-run JIT delay, repeat-run cache loading, Unicode/space paths, memmap export, mouse interactions, high-DPI layout and window closure during preparation/seek. Record driver/runtime/package versions and actual behavior. Dependency-wheel resolution and an unrun CI file are insufficient evidence by themselves.

### Priority 2 — Physical setup and real-job acceptance

Measure installed tool geometry and stickout, confirm the nominal Air envelope orientation and holder/nose dimensions, add fixtures/accessories, establish actual start/WCS/machine-origin mappings, and confirm G28/M6 semantics for the exact community firmware version. Compare a simple known physical cut or independent CAM result to the voxel result before using this as a machining decision gate.

Four-axis work, height-map-adjusted motion and hidden firmware macros remain outside scope. A simulator result cannot by itself diagnose controller positioning faults, lost steps or physical deflection.

### Priority 3 — Tool-library coverage

Obtain an actual current Makera Studio export/database sample if exhaustive library compatibility is required. Preserve explicit dimensional provenance and reject incomplete profiles. Add fixtures for each newly supported metadata type. Do not conflate a recognized family name with a fully defined cutter.

The catalog extraction and CAD-envelope extraction were performed during development; reusable regeneration scripts are not included in the source ZIP. Add maintainable import/extraction scripts if the data will be refreshed. Preserve source commit, original geometry and a human-review step for profiles whose mounting dimensions cannot be inferred reliably.

### Priority 4 — Engineering hardening

| Area | Concrete follow-up |
|---|---|
| Source control | Initialize/use a real project repository if requested; the current folder is not Git-backed. |
| Ignore rules | `.gitignore` still lists `.venv/`, but not `.venv314/`. Add the latter before a Windows environment can be accidentally staged. |
| Test fixtures in Git | Broad `*.npy` / `*.report.json` ignores also cover saved example results. Explicitly decide how those fixtures should be tracked. |
| Reproducible installs | Consider a tested constraints/lock file while retaining usable package metadata. Current ranges can resolve newer Qt/test dependencies. |
| Provenance | Add repeatable catalog and CAD derivation tooling instead of relying on generated JSON plus scratch research. |
| Parser compatibility | Build a corpus of actual Makera Studio exports and exact community-firmware variants; add narrow support with tests. |
| Cancellation | Investigate long kernel/mesh work and blocking `worker.join()` on close for very large jobs. |
| Memory/scale | Profile large head/body overlaps, many arc chords and dense full-resolution meshes; checkpoint packing uses transient memory. |
| Primitive expansion | Add mesh/rotated-box fixtures only with a defined continuous-contact and tolerance strategy. |
| Reporting | If needed, make travel-limit timestamps exact; they currently identify offending endpoints. |
| Replay API | If replay will be exposed to external callers, separate visual-state counters from final-report counters. |
| Output durability | Consider a run ID or stronger two-file publication protocol if consumers require transactional pair updates. |
| Public distribution | No project `LICENSE` file is present. Establish intended licensing and source-data provenance before publishing a repository/package. |

Do not expand to 4/5-axis, GPU simulation, a full machine kinematic graph or material-physics estimation merely to polish the handover. Those are separate architectural changes requiring requirements and validation.

## 16. Development context and recoverable references

### Existing session paths

These were present when the handover was written. They are convenience paths for the current workspace, not portable install requirements and not guaranteed to persist into a different agent environment.

| Path | Contents |
|---|---|
| `/workspace/scratch/81ce3209d11c/carvera-voxel-sim` | Source tree matching the delivered ZIP |
| `/workspace/scratch/81ce3209d11c/carvera-voxel-sim.zip` | Delivered 0.1.1 archive |
| `/workspace/scratch/81ce3209d11c/research/venv314` | Clean Python 3.14.10 development/test environment |
| `/workspace/scratch/81ce3209d11c/research/tests314.xml` | Full 80-test JUnit output |
| `/workspace/scratch/81ce3209d11c/research/demo314.npy` and `.report.json` | Installed-package migration smoke output |
| `/workspace/scratch/81ce3209d11c/research/wheels314` | Built 0.1.1 wheel |
| `/workspace/scratch/81ce3209d11c/research/windows314-wheels` | Downloaded Windows x64 runtime/viewer/test wheels |
| `/workspace/scratch/81ce3209d11c/research/CarveraProfiles` | Pinned official Makera source checkout |

Older Python 3.12 GUI/import environments and research files may also be present. Use the project ZIP and current validation record to distinguish deliverables from temporary development material.

`research/makera_db_converter.txt` is an exploratory third-party converter reference, not the simulator's shipped importer. It contains guessed dimensions and a fallback to flat end mills for unknown types. Do not adopt those defaults into the strict verification path.

### Source material already consulted

- [Makera CarveraProfiles at the pinned commit](https://github.com/MakeraInc/CarveraProfiles/tree/de08a657bdc9c230a094dbdba792acd70bfcdf32): numeric cutter profiles, simplified CAD and example NC.
- Tool profiles under `CAM_Post_Processors/Fusion360-profiles/Tool Files/`, including Ball Endmills, Corn Bits, Drill Bits, Engraving Bits, O Flute Bits, Other Tools and Thread Mills.
- [Official simplified Carvera Air STEP](https://github.com/MakeraInc/CarveraProfiles/blob/de08a657bdc9c230a094dbdba792acd70bfcdf32/Machine_Design_Files/Carvera_Air_Simplified.step).
- [Official TopClamp NC example](https://github.com/MakeraInc/CarveraProfiles/blob/de08a657bdc9c230a094dbdba792acd70bfcdf32/Sample_Files/TopClamp.nc).
- [Makera CAM user/tool-library guide](https://wiki.makera.com/en/software/MakeraCAM_userguide).
- [Carvera Community G-code documentation](https://carvera-community.gitbook.io/docs/firmware/supported-commands/gcodes).
- [Carvera Community M-code documentation](https://carvera-community.gitbook.io/docs/firmware/supported-commands/mcodes).
- [Numba 0.63 release notes](https://numba.readthedocs.io/en/0.67.0/release/0.63.0-notes.html) and package metadata used when checking Python 3.14 support.
- [Qt for Python release notes](https://doc.qt.io/qtforpython-6/release_notes/pyside6_release_notes.html).
- [Shiboken6 6.12.0 package description](https://pypi.org/project/shiboken6/6.12.0/).

The Makera numerical data are pinned. The unversioned documentation links can change; recheck the exact firmware/library behavior when extending support. This handover records the existing implementation and tests rather than claiming to have revalidated every external source on the handover date.

## 17. Continuation brief

Continue from `carvera-voxel-sim` **0.1.1**, targeting standard x64 **Python 3.14**. Preserve the full 3D bool grid, continuous frustum sweeps, collision-before-removal timing, strict NC rejection, and explicit incomplete-model reporting. The highest-value next evidence is a native Windows run and a measured Carvera Air setup. Treat the 80 passing tests as a useful baseline, the nominal CAD/catalog as unverified geometry, and the old benchmark numbers as Linux/Python 3.12 observations. Do not present the tool as a physical safety guarantee or an exhaustive Studio/firmware emulator.
