# Validation records for 0.3.0 and earlier releases

`../VALIDATION.json` is the current summary. These files preserve the underlying
measurements and clearly separate historical results.

| File | Evidence |
|---|---|
| `tests_project_rename.xml` | 0.3.0, Linux / CPython 3.14.10: 98 passed, none skipped |
| `project_rename.json` | Installed wheel, CLI/module names, resources, config, catalog aliases and offscreen window labels; identical demo stock/metric arrays |
| `tests_metric_names.xml` | 0.2.2 terminology patch: 97 passed, none skipped |
| `tests_depth_fix.xml` | 0.2.1 patch, Linux / CPython 3.14.10: 97 passed, none skipped |
| `tests.xml` | 0.2.0 feature release, Linux / CPython 3.14.10: 97 passed, none skipped |
| `native_playback.json` | Actual viewport swaps and worker-frame delivery; 0.1 mm, 57.6 million voxels, 10× speed, Mesa software OpenGL |
| `headless_benchmark.json` | `scripts/benchmark.py` with metrics and collision checking enabled |
| `mesh_microbenchmarks.json` | Old whole-grid scan and local one-chunk edit timings; CPU meshing only |
| `demo_metrics.json` | Exact old/new bool-array equality, sample count, total removal and metric peaks |
| `history_0_1_1.json` | Previous release's validation, kept as history; not current runtime/performance evidence |

The 0.3.0 example report was regenerated with the generic machine template. Its
stock and all 426 metric rows match the previous result exactly. Original
performance measurements remain historical; renaming did not rerun those benchmarks.
The historical wheel filename in `history_0_1_1.json` is described generically;
its original identity remains available in Git history.

The 0.2.1 path-overlay fix was visually compared with the original draw order
in the native window, including playback, orbit and rewind. Numeric kernels and
output schemas were unchanged. Performance measurements below belong to 0.2.0.

Native playback measurements exclude initial simulation/JIT/full meshing and
arbitrary seeks. Mesh microbenchmark times are not desktop FPS. The temporary
microbenchmark's raw sample field was mislabeled `sample_ms`; this record uses
`sample_s` because those samples are seconds. Its reported median/p95 fields
were already correctly converted to milliseconds.

The native benchmark writes its main report while leaving the window open;
an export-hash equality field is appended only after closing it. This saved
measurement does not contain that optional close-time field. Export and metric
immutability through forward/backward replay are covered by the automated
regression in `tests/test_metrics.py`.

Native Windows execution was unavailable. The prior release resolved Windows
x64 dependency wheels, and this release adds no external dependencies. The
Windows/Linux CI workflow is included but has not been run on GitHub here.
